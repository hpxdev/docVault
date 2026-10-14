"""AI client: spend cap check before every call, `ai_calls` ledger row after every call.

The ledger is written in its own transaction so spend is recorded even when the surrounding
work (e.g. writing chunks) later rolls back. The running total is cached in Redis and
recomputed from the database on a cache miss. The cap is checked before each call, so it can be
overshot by at most the calls already in flight.
"""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from decimal import Decimal
from typing import Any, TypeVar

from langchain_core.messages import BaseMessage
from pydantic import BaseModel
from sqlalchemy import func, select

from app.ai.errors import AIBudgetExceeded
from app.ai.openai_provider import classify
from app.ai.pricing import estimate_cost
from app.ai.providers import ChatModel, EmbeddingModel, StreamResult, Usage
from app.core.config import get_settings
from app.core.redis import async_cache, sync_cache
from app.core.tokens import count_chat_tokens
from app.db.session import async_session_factory, sync_session
from app.models import AICall

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

SPEND_KEY = "ai:spend_total_usd"
SPEND_TTL_S = 3600
_INCR_IF_EXISTS = (
    "if redis.call('exists', KEYS[1]) == 1 then "
    "return redis.call('incrbyfloat', KEYS[1], ARGV[1]) end return false"
)
_TOTAL_SQL = select(func.coalesce(func.sum(AICall.estimated_cost_usd), 0))


def _budget_error(spent: Decimal, limit: float) -> AIBudgetExceeded:
    return AIBudgetExceeded(
        f"The AI spend cap of ${limit:.2f} has been reached (estimated ${spent:.4f} spent).",
        details={"spent_usd": float(spent), "limit_usd": limit},
    )


def _row(
    *,
    purpose: str,
    model: str,
    usage: Usage,
    latency_ms: int,
    status: str,
    error_code: str | None,
    prompt_version: str | None,
    document_id: uuid.UUID | None,
    message_id: uuid.UUID | None,
) -> AICall:
    return AICall(
        purpose=purpose,
        model=model,
        prompt_version=prompt_version,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cached_tokens=usage.cached_tokens,
        estimated_cost_usd=estimate_cost(
            model, usage.input_tokens, usage.output_tokens, usage.cached_tokens
        ),
        latency_ms=latency_ms,
        status=status,
        error_code=error_code,
        document_id=document_id,
        message_id=message_id,
    )


def _failure_usage(exc: Exception) -> Usage:
    return getattr(exc, "usage", None) or Usage()


class SyncAI:
    """Used by the Celery worker (sync)."""

    def __init__(self, chat: ChatModel, embeddings: EmbeddingModel) -> None:
        self.chat = chat
        self.embeddings = embeddings

    def spent(self) -> Decimal:
        cache = sync_cache()
        cached = cache.get(SPEND_KEY)
        if cached is not None:
            return Decimal(cached)
        with sync_session() as s:
            total = Decimal(s.scalar(_TOTAL_SQL) or 0)
        cache.set(SPEND_KEY, str(total), ex=SPEND_TTL_S)
        return total

    def guard(self) -> None:
        limit = get_settings().ai_spend_limit_usd
        spent = self.spent()
        if spent >= Decimal(str(limit)):
            raise _budget_error(spent, limit)

    def _record(self, row: AICall) -> None:
        with sync_session() as s:
            s.add(row)
            s.commit()
        if row.estimated_cost_usd:
            sync_cache().eval(_INCR_IF_EXISTS, 1, SPEND_KEY, str(row.estimated_cost_usd))
        log.info(
            "ai call",
            extra={
                "purpose": row.purpose,
                "model": row.model,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "cost_usd": str(row.estimated_cost_usd),
                "duration_ms": row.latency_ms,
                "document_id": str(row.document_id) if row.document_id else None,
            },
        )

    def _call(
        self,
        purpose: str,
        model: str,
        fn: Callable[[], tuple[Any, Usage]],
        *,
        prompt_version: str | None = None,
        document_id: uuid.UUID | None = None,
    ) -> Any:
        self.guard()
        started = time.perf_counter()
        meta = {"prompt_version": prompt_version, "document_id": document_id, "message_id": None}
        try:
            value, usage = fn()
        except Exception as exc:
            err = classify(exc)
            self._record(
                _row(
                    purpose=purpose,
                    model=model,
                    usage=_failure_usage(exc),
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    status="failed",
                    error_code=err.code,
                    **meta,
                )
            )
            if err is exc:
                raise
            raise err from exc
        self._record(
            _row(
                purpose=purpose,
                model=model,
                usage=usage,
                latency_ms=int((time.perf_counter() - started) * 1000),
                status="succeeded",
                error_code=None,
                **meta,
            )
        )
        return value

    def embed_documents(self, texts: list[str], *, document_id: uuid.UUID) -> list[list[float]]:
        return self._call(
            "embed_document",
            self.embeddings.name,
            lambda: self.embeddings.embed_documents(texts),
            document_id=document_id,
        )

    def structured(
        self,
        schema: type[T],
        messages: Sequence[BaseMessage],
        *,
        purpose: str,
        prompt_version: str,
        document_id: uuid.UUID,
        max_tokens: int,
    ) -> T:
        return self._call(
            purpose,
            self.chat.name,
            lambda: self.chat.structured(schema, messages, purpose=purpose, max_tokens=max_tokens),
            prompt_version=prompt_version,
            document_id=document_id,
        )


class AsyncAI:
    """Used by the API (async): query embeddings, condense, answer (complete or streamed)."""

    def __init__(self, chat: ChatModel, embeddings: EmbeddingModel) -> None:
        self.chat = chat
        self.embeddings = embeddings

    async def spent(self) -> Decimal:
        cache = async_cache()
        cached = await cache.get(SPEND_KEY)
        if cached is not None:
            return Decimal(cached)
        async with async_session_factory()() as s:
            total = Decimal(await s.scalar(_TOTAL_SQL) or 0)
        await cache.set(SPEND_KEY, str(total), ex=SPEND_TTL_S)
        return total

    async def guard(self) -> None:
        limit = get_settings().ai_spend_limit_usd
        spent = await self.spent()
        if spent >= Decimal(str(limit)):
            raise _budget_error(spent, limit)

    async def _record(self, row: AICall) -> None:
        async with async_session_factory()() as s:
            s.add(row)
            await s.commit()
        if row.estimated_cost_usd:
            await async_cache().eval(_INCR_IF_EXISTS, 1, SPEND_KEY, str(row.estimated_cost_usd))
        log.info(
            "ai call",
            extra={
                "purpose": row.purpose,
                "model": row.model,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "cost_usd": str(row.estimated_cost_usd),
                "duration_ms": row.latency_ms,
                "message_id": str(row.message_id) if row.message_id else None,
            },
        )

    async def _call(
        self,
        purpose: str,
        model: str,
        coro_fn: Callable[[], Any],
        *,
        prompt_version: str | None = None,
        message_id: uuid.UUID | None = None,
    ) -> tuple[Any, Usage]:
        await self.guard()
        started = time.perf_counter()
        meta = {"prompt_version": prompt_version, "document_id": None, "message_id": message_id}
        try:
            value, usage = await coro_fn()
        except Exception as exc:
            err = classify(exc)
            await self._record(
                _row(
                    purpose=purpose,
                    model=model,
                    usage=_failure_usage(exc),
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    status="failed",
                    error_code=err.code,
                    **meta,
                )
            )
            if err is exc:
                raise
            raise err from exc
        await self._record(
            _row(
                purpose=purpose,
                model=model,
                usage=usage,
                latency_ms=int((time.perf_counter() - started) * 1000),
                status="succeeded",
                error_code=None,
                **meta,
            )
        )
        return value, usage

    async def embed_query(self, text: str, *, message_id: uuid.UUID) -> list[float]:
        vector, _ = await self._call(
            "embed_query",
            self.embeddings.name,
            lambda: self.embeddings.aembed_query(text),
            message_id=message_id,
        )
        return vector

    async def complete(
        self,
        messages: Sequence[BaseMessage],
        *,
        purpose: str,
        prompt_version: str,
        message_id: uuid.UUID,
        max_tokens: int,
    ) -> tuple[str, Usage]:
        return await self._call(
            purpose,
            self.chat.name,
            lambda: self.chat.acomplete(messages, purpose=purpose, max_tokens=max_tokens),
            prompt_version=prompt_version,
            message_id=message_id,
        )

    async def stream(
        self,
        messages: Sequence[BaseMessage],
        *,
        purpose: str,
        prompt_version: str,
        message_id: uuid.UUID,
        max_tokens: int,
        result: StreamResult,
    ) -> AsyncIterator[str]:
        """Yields text deltas. The ledger row is written when the stream ends, fails or is
        closed early (client disconnect); without provider usage, tokens are counted locally."""
        await self.guard()
        started = time.perf_counter()
        status, error_code, completed = "interrupted", None, False
        try:
            async for delta in self.chat.astream(
                messages, purpose=purpose, max_tokens=max_tokens, result=result
            ):
                yield delta
            status, completed = "succeeded", True
        except Exception as exc:
            err = classify(exc)
            status, error_code = "failed", err.code
            if err is exc:
                raise
            raise err from exc
        finally:
            usage = result.usage
            if not completed or usage.input_tokens == 0:
                prompt = "\n".join(str(m.content) for m in messages)
                usage = Usage(
                    input_tokens=usage.input_tokens or count_chat_tokens(prompt),
                    output_tokens=usage.output_tokens or count_chat_tokens(result.text),
                    estimated=True,
                )
                result.usage = usage
            await self._record(
                _row(
                    purpose=purpose,
                    model=self.chat.name,
                    usage=usage,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    status=status,
                    error_code=error_code,
                    prompt_version=prompt_version,
                    document_id=None,
                    message_id=message_id,
                )
            )

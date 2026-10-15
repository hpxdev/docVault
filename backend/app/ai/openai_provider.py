"""OpenAI via LangChain (`ChatOpenAI`, `OpenAIEmbeddings`) with error classification."""

from collections.abc import AsyncIterator, Sequence
from typing import TypeVar

import openai
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import BaseModel

from app.ai.errors import AIError, AIOutputInvalid, AIProviderUnavailable, AIRequestRejected
from app.ai.providers import StreamResult, Usage, usage_from_metadata
from app.core.tokens import count_embedding_tokens

T = TypeVar("T", bound=BaseModel)

REQUEST_TIMEOUT_S = 60


def classify(exc: Exception) -> AIError:
    """Map OpenAI SDK errors to app errors; only timeouts, 429 rate limits and 5xx are transient."""
    if isinstance(exc, AIError):
        return exc
    if isinstance(exc, openai.RateLimitError):
        body = getattr(exc, "body", None) or {}
        code = body.get("code") if isinstance(body, dict) else None
        if code == "insufficient_quota":  # billing problem: retrying cannot help
            return AIRequestRejected(
                "The OpenAI account has insufficient quota.", code="AI_QUOTA_EXCEEDED"
            )
        return AIProviderUnavailable("OpenAI rate limit reached; retrying later may succeed.")
    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError)):
        return AIProviderUnavailable(f"OpenAI request failed ({type(exc).__name__}).")
    if isinstance(exc, openai.InternalServerError):
        return AIProviderUnavailable("OpenAI returned a server error.")
    if isinstance(exc, openai.AuthenticationError):
        return AIRequestRejected("OpenAI rejected the API key.", code="AI_AUTH_FAILED")
    if isinstance(exc, openai.APIStatusError):
        return AIRequestRejected(f"OpenAI rejected the request (HTTP {exc.status_code}).")
    return AIProviderUnavailable(f"AI call failed ({type(exc).__name__}).")


class OpenAIChat:
    def __init__(self, model: str, api_key: str, max_retries: int) -> None:
        self.name = model
        self._api_key = api_key
        self._max_retries = max_retries
        self._by_max_tokens: dict[int, ChatOpenAI] = {}

    def _llm(self, max_tokens: int) -> ChatOpenAI:
        # One client per output cap: `with_structured_output` is only available on the model
        # itself, not on a `.bind(...)` wrapper, so the cap is set at construction.
        llm = self._by_max_tokens.get(max_tokens)
        if llm is None:
            llm = ChatOpenAI(
                model=self.name,
                api_key=self._api_key,
                temperature=0.1,
                max_tokens=max_tokens,
                max_retries=self._max_retries,
                request_timeout=REQUEST_TIMEOUT_S,
                stream_usage=True,
            )
            self._by_max_tokens[max_tokens] = llm
        return llm

    def _structured_runnable(self, schema: type[BaseModel], max_tokens: int):
        return self._llm(max_tokens).with_structured_output(
            schema, method="json_schema", strict=True, include_raw=True
        )

    @staticmethod
    def _parsed(out: dict) -> tuple[BaseModel, Usage]:
        usage = usage_from_metadata(getattr(out.get("raw"), "usage_metadata", None))
        parsed = out.get("parsed")
        if parsed is None or out.get("parsing_error") is not None:
            err = AIOutputInvalid("The model output did not match the expected schema.")
            err.usage = usage  # type: ignore[attr-defined]  (still billed)
            raise err
        return parsed, usage

    def structured(
        self, schema: type[T], messages: Sequence[BaseMessage], *, purpose: str, max_tokens: int
    ) -> tuple[T, Usage]:
        try:
            out = self._structured_runnable(schema, max_tokens).invoke(list(messages))
        except Exception as exc:
            raise classify(exc) from exc
        return self._parsed(out)  # type: ignore[return-value]

    async def astructured(
        self, schema: type[T], messages: Sequence[BaseMessage], *, purpose: str, max_tokens: int
    ) -> tuple[T, Usage]:
        try:
            out = await self._structured_runnable(schema, max_tokens).ainvoke(list(messages))
        except Exception as exc:
            raise classify(exc) from exc
        return self._parsed(out)  # type: ignore[return-value]

    async def acomplete(
        self, messages: Sequence[BaseMessage], *, purpose: str, max_tokens: int
    ) -> tuple[str, Usage]:
        try:
            msg = await self._llm(max_tokens).ainvoke(list(messages))
        except Exception as exc:
            raise classify(exc) from exc
        return str(msg.content), usage_from_metadata(msg.usage_metadata)

    async def astream(
        self,
        messages: Sequence[BaseMessage],
        *,
        purpose: str,
        max_tokens: int,
        result: StreamResult,
    ) -> AsyncIterator[str]:
        try:
            async for chunk in self._llm(max_tokens).astream(list(messages)):
                if chunk.usage_metadata:  # the final chunk carries usage (stream_usage=True)
                    result.usage = usage_from_metadata(chunk.usage_metadata)
                delta = chunk.content if isinstance(chunk.content, str) else ""
                if delta:
                    result.text += delta
                    yield delta
        except Exception as exc:
            raise classify(exc) from exc


class OpenAIEmbeddingModel:
    def __init__(self, model: str, api_key: str, max_retries: int, dimensions: int) -> None:
        self.name = model
        self._emb = OpenAIEmbeddings(
            model=model,
            api_key=api_key,
            dimensions=dimensions,
            max_retries=max_retries,
            request_timeout=REQUEST_TIMEOUT_S,
            chunk_size=100,  # inputs per request; we also batch to <= 100 ourselves
        )

    # LangChain's OpenAIEmbeddings does not expose usage; tokens are counted locally with the
    # model's own tokenizer (cl100k_base), which is what OpenAI bills for these inputs.

    def embed_documents(self, texts: list[str]) -> tuple[list[list[float]], Usage]:
        try:
            vectors = self._emb.embed_documents(texts)
        except Exception as exc:
            raise classify(exc) from exc
        tokens = sum(count_embedding_tokens(t) for t in texts)
        return vectors, Usage(input_tokens=tokens)

    async def aembed_query(self, text: str) -> tuple[list[float], Usage]:
        try:
            vector = await self._emb.aembed_query(text)
        except Exception as exc:
            raise classify(exc) from exc
        return vector, Usage(input_tokens=count_embedding_tokens(text))

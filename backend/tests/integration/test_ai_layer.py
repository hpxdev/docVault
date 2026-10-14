"""AI layer: ledger, pricing, spend cap, error classification, fakes, AI-mode labelling."""

import uuid
from decimal import Decimal

import httpx
import openai
import pytest
from langchain_core.messages import HumanMessage
from sqlalchemy import select

from app.ai import registry
from app.ai.client import SPEND_KEY, AsyncAI, SyncAI
from app.ai.errors import (
    AIBudgetExceeded,
    AINotConfigured,
    AIProviderUnavailable,
    AIRequestRejected,
)
from app.ai.fakes import FakeChatModel, FakeEmbeddings, hashed_embedding
from app.ai.openai_provider import classify
from app.ai.pricing import estimate_cost
from app.ai.providers import StreamResult
from app.core.config import get_settings
from app.core.redis import sync_cache
from app.core.tokens import count_chat_tokens
from app.db.session import sync_session
from app.models import AICall


class PricedFakeChat(FakeChatModel):
    """Fake behaviour, but billed as gpt-4o-mini so cost arithmetic is exercised. No network."""

    name = "gpt-4o-mini"


class PricedFakeEmbeddings(FakeEmbeddings):
    name = "text-embedding-3-small"


def _calls() -> list[AICall]:
    with sync_session() as s:
        return list(s.scalars(select(AICall).order_by(AICall.created_at)))


def _seed_spend(amount: str) -> None:
    with sync_session() as s:
        s.add(
            AICall(
                purpose="answer",
                model="gpt-4o-mini",
                estimated_cost_usd=Decimal(amount),
                status="succeeded",
            )
        )
        s.commit()


def test_pricing_estimates():
    # 1M input + 1M output tokens of gpt-4o-mini = $0.15 + $0.60
    assert estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000) == Decimal("0.75")
    # half the input cached: 0.5 * 0.15 + 0.5 * 0.075
    assert estimate_cost("gpt-4o-mini", 1_000_000, 0, 500_000) == Decimal("0.1125")
    assert estimate_cost("text-embedding-3-small", 1_000_000) == Decimal("0.02")
    assert estimate_cost("fake", 10**9, 10**9) == 0


def test_fake_mode_records_ledger_rows_labelled_fake():
    ai = registry.sync_ai()
    doc_id = uuid.uuid4()
    vectors = ai.embed_documents(["budget approved", "pump replaced"], document_id=doc_id)
    assert len(vectors) == 2 and len(vectors[0]) == 1536
    [row] = _calls()
    assert (row.purpose, row.model, row.status) == ("embed_document", "fake", "succeeded")
    assert row.input_tokens > 0 and row.estimated_cost_usd == 0
    assert row.document_id == doc_id


def test_cost_is_estimated_from_usage_and_cached_total_increments():
    ai = SyncAI(PricedFakeChat(), PricedFakeEmbeddings())
    assert ai.spent() == 0  # computed from the DB, then cached
    ai.embed_documents(["word " * 1000], document_id=uuid.uuid4())
    [row] = _calls()
    assert row.estimated_cost_usd == estimate_cost("text-embedding-3-small", row.input_tokens)
    assert row.estimated_cost_usd > 0
    assert Decimal(sync_cache().get(SPEND_KEY)) == row.estimated_cost_usd


def test_spend_cap_blocks_calls_before_reaching_the_provider(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_spend_limit_usd", 0.50)
    _seed_spend("0.50")
    emb = PricedFakeEmbeddings()
    ai = SyncAI(PricedFakeChat(), emb)
    with pytest.raises(AIBudgetExceeded) as err:
        ai.embed_documents(["x"], document_id=uuid.uuid4())
    assert err.value.status_code == 429 and err.value.code == "AI_BUDGET_EXCEEDED"
    assert emb.calls == []  # provider never called
    assert len(_calls()) == 1  # only the seeded row


def test_spend_total_recomputed_from_db_on_cache_miss(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_spend_limit_usd", 0.50)
    ai = SyncAI(PricedFakeChat(), PricedFakeEmbeddings())
    assert ai.spent() == 0
    _seed_spend("0.60")  # written behind the cache's back
    sync_cache().delete(SPEND_KEY)
    with pytest.raises(AIBudgetExceeded):
        ai.guard()


async def test_async_spend_cap_and_ledger(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_spend_limit_usd", 0.50)
    ai = AsyncAI(PricedFakeChat(script=["hello"]), PricedFakeEmbeddings())
    message_id = uuid.uuid4()
    text, usage = await ai.complete(
        [HumanMessage("hi")],
        purpose="answer",
        prompt_version="chat.answer.v1",
        message_id=message_id,
        max_tokens=10,
    )
    assert text == "hello" and usage.output_tokens > 0
    [row] = _calls()
    assert row.message_id == message_id and row.prompt_version == "chat.answer.v1"
    _seed_spend("0.50")
    sync_cache().delete(SPEND_KEY)  # seeded behind the cache: force a recompute
    with pytest.raises(AIBudgetExceeded):
        await ai.embed_query("q", message_id=message_id)


def test_failed_calls_are_recorded_with_error_code():
    emb = FakeEmbeddings()
    emb.fail_with = AIProviderUnavailable("timeout")
    ai = SyncAI(FakeChatModel(), emb)
    with pytest.raises(AIProviderUnavailable):
        ai.embed_documents(["x"], document_id=uuid.uuid4())
    [row] = _calls()
    assert (row.status, row.error_code) == ("failed", "AI_PROVIDER_UNAVAILABLE")


async def test_stream_closed_early_records_interrupted_with_estimated_tokens():
    ai = AsyncAI(FakeChatModel(script=["one two three four five"]), FakeEmbeddings())
    result = StreamResult()
    gen = ai.stream(
        [HumanMessage("question")],
        purpose="answer",
        prompt_version="chat.answer.v1",
        message_id=uuid.uuid4(),
        max_tokens=50,
        result=result,
    )
    assert await gen.__anext__() == "one "
    await gen.aclose()  # client went away
    [row] = _calls()
    assert row.status == "interrupted"
    assert row.input_tokens > 0 and row.output_tokens == count_chat_tokens("one ")
    assert result.usage.estimated is True


def _status_error(cls, status, body=None):
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return cls("err", response=httpx.Response(status, request=request), body=body)


def test_error_classification():
    request = httpx.Request("POST", "https://api.openai.com/v1/x")
    assert classify(openai.APITimeoutError(request=request)).transient
    assert classify(_status_error(openai.RateLimitError, 429)).transient
    assert classify(_status_error(openai.InternalServerError, 500)).transient
    quota = classify(_status_error(openai.RateLimitError, 429, {"code": "insufficient_quota"}))
    assert not quota.transient and quota.code == "AI_QUOTA_EXCEEDED"
    auth = classify(_status_error(openai.AuthenticationError, 401))
    assert isinstance(auth, AIRequestRejected) and auth.code == "AI_AUTH_FAILED"
    assert not classify(_status_error(openai.BadRequestError, 400)).transient


def test_openai_mode_without_key_is_not_configured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", None)
    with pytest.raises(AINotConfigured):
        registry.get_chat_model()
    with pytest.raises(AINotConfigured):
        registry.get_embedding_model()


def test_unpriced_model_is_refused(monkeypatch):
    from pydantic import SecretStr

    settings = get_settings()
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("sk-test-not-used"))
    monkeypatch.setattr(settings, "openai_chat_model", "some-unpriced-model")
    with pytest.raises(AINotConfigured) as err:
        registry.get_chat_model()
    assert "pricing.py" in err.value.message


def test_fake_embeddings_have_lexical_similarity():
    def cos(a, b):
        return sum(x * y for x, y in zip(a, b, strict=True))

    q = hashed_embedding("What is the approved budget for Project Falcon?")
    hit = hashed_embedding("The total approved budget for Project Falcon is 4.2 million.")
    miss = hashed_embedding("The pump at station 7 was replaced in May.")
    assert cos(q, hit) > 0.3 > cos(q, miss)
    assert abs(cos(hit, hit) - 1) < 1e-9
    assert any(hashed_embedding(""))  # never a zero vector (cosine undefined)

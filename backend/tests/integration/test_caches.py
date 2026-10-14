"""Caches: query embeddings (hit = no provider call; model change = miss) and the rule that chat
answers are never cached."""

import uuid

from sqlalchemy import select

from app.ai.client import AsyncAI
from app.ai.fakes import FakeChatModel, FakeEmbeddings
from app.core.redis import sync_cache
from app.db.session import sync_session
from app.models import AICall
from app.services.cache import QEMB_TTL_S, cached_query_embedding, query_embedding_key
from tests import fixtures
from tests.conftest import run_queued


class OtherModelEmbeddings(FakeEmbeddings):
    """Fake vectors under another (priced) model name; no network."""

    name = "text-embedding-3-small"


async def test_query_embedding_cache_hit_skips_provider():
    emb = FakeEmbeddings()
    ai = AsyncAI(FakeChatModel(), emb)
    v1, hit1 = await cached_query_embedding(ai, "What is the budget?", message_id=uuid.uuid4())
    v2, hit2 = await cached_query_embedding(ai, "  what IS the   budget? ", message_id=uuid.uuid4())
    assert (hit1, hit2) == (False, True)
    assert v1 == v2 and len(emb.calls) == 1  # normalised query → same key, one provider call
    key = query_embedding_key("fake", "what is the budget?")
    assert key.startswith("qemb:fake:") and 0 < sync_cache().ttl(key) <= QEMB_TTL_S

    other = AsyncAI(FakeChatModel(), OtherModelEmbeddings())
    _, hit3 = await cached_query_embedding(other, "What is the budget?", message_id=uuid.uuid4())
    assert hit3 is False  # a different embedding model never reuses cached vectors


async def test_repeated_question_reuses_embedding_but_not_the_answer(client, enqueued, fake_chat):
    r = await client.post(
        "/documents", files=[("files", ("plan.pdf", fixtures.five_page_pdf(), "application/pdf"))]
    )
    doc = r.json()["results"][0]["document"]["id"]
    run_queued(enqueued)
    s1 = (await client.post("/chat/sessions", json={"document_ids": [doc]})).json()["id"]
    s2 = (await client.post("/chat/sessions", json={"document_ids": [doc]})).json()["id"]
    q = {"content": "What is the approved budget?"}
    m1 = (await client.post(f"/chat/sessions/{s1}/messages", json=q)).json()["assistant_message"]
    m2 = (await client.post(f"/chat/sessions/{s2}/messages", json=q)).json()["assistant_message"]

    with sync_session() as s:
        purposes = {
            mid: [c.purpose for c in s.scalars(select(AICall).where(AICall.message_id == mid))]
            for mid in (uuid.UUID(m1["id"]), uuid.UUID(m2["id"]))
        }
    assert purposes[uuid.UUID(m1["id"])] == ["embed_query", "answer"]
    assert purposes[uuid.UUID(m2["id"])] == ["answer"]  # embedding from cache, answer regenerated
    answers = [p for p, _ in fake_chat.calls if p == "answer"]
    assert len(answers) == 2

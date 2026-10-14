"""Index stage: in-segment chunking, batched embeddings, idempotent writes, readiness."""

import uuid

from sqlalchemy import func, select

from app.ai.errors import AIProviderUnavailable
from app.db.session import sync_session
from app.models import AICall, Chunk, Document, DocumentSegment
from app.services import pipeline
from tests import fixtures
from tests.conftest import run_queued


async def _upload(client, name, data):
    r = await client.post("/documents", files=[("files", (name, data, "application/octet-stream"))])
    return r.json()["results"][0]["document"]["id"]


def _chunks(doc_id):
    with sync_session() as s:
        return list(
            s.scalars(
                select(Chunk).where(Chunk.document_id == uuid.UUID(doc_id)).order_by(Chunk.ordinal)
            )
        )


async def test_index_creates_chunks_with_exact_locators(client, enqueued):
    doc_id = await _upload(client, "plan.pdf", fixtures.five_page_pdf())
    pipeline.execute_stage("extract", doc_id)
    assert ("index", doc_id) in enqueued
    assert pipeline.execute_stage("index", doc_id).result == "succeeded"

    chunks = _chunks(doc_id)
    assert len(chunks) == 5  # small pages: one chunk each
    with sync_session() as s:
        segments = {seg.id: seg for seg in s.scalars(select(DocumentSegment))}
    for chunk in chunks:
        seg = segments[chunk.segment_id]
        assert chunk.locator == seg.locator  # chunk never crosses a segment boundary
        assert chunk.text in seg.text
        assert chunk.page_number == seg.locator["page"]
        assert chunk.embedding_model == "fake" and len(chunk.embedding) == 1536
    fact = [c for c in chunks if "4.2 million" in c.text]
    assert [c.page_number for c in fact] == [3]

    with sync_session() as s:
        doc = s.get(Document, uuid.UUID(doc_id))
        assert doc.index_status == "succeeded" and doc.chat_ready_at is not None
        assert doc.embedding_model == "fake"
        tsv_hits = s.scalar(
            select(func.count()).where(
                Chunk.document_id == doc.id,
                Chunk.tsv.op("@@")(func.plainto_tsquery("english", "approved budget")),
            )
        )
        assert tsv_hits == 1  # generated tsvector is populated


async def test_long_segments_split_within_segment_and_embeddings_batched(client, enqueued):
    # ~120 pages of filler plus one long page -> more than 100 chunks -> 2 embedding batches.
    long_text = "\n".join(
        f"Paragraph {i}. " + "Operational detail sentence. " * 30 for i in range(60)
    )
    doc_id = await _upload(client, "long.txt", (long_text + "\n").encode())
    pipeline.execute_stage("extract", doc_id)
    pipeline.execute_stage("index", doc_id)
    chunks = _chunks(doc_id)
    assert len(chunks) > 1 and all(c.token_count <= 800 for c in chunks)
    assert len({c.segment_id for c in chunks}) < len(chunks)  # several chunks per segment

    # 120 one-chunk pages -> 120 inputs -> two embedding requests (100 + 20).

    pdf_id = await _upload(client, "heron.pdf", fixtures.long_pdf(120))
    pipeline.execute_stage("extract", pdf_id)
    pipeline.execute_stage("index", pdf_id)
    assert len(_chunks(pdf_id)) == 120
    with sync_session() as s:
        calls = s.scalars(
            select(AICall).where(
                AICall.document_id == uuid.UUID(pdf_id), AICall.purpose == "embed_document"
            )
        ).all()
    assert len(calls) == 2  # 100 + 20 inputs


async def test_reindex_is_idempotent(client, enqueued):
    doc_id = await _upload(client, "guide.md", fixtures.MARKDOWN.encode())
    run_queued(enqueued)
    first = [(c.ordinal, c.text, c.locator) for c in _chunks(doc_id)]
    assert first

    # Re-delivered task after success: no-op.
    assert pipeline.execute_stage("index", doc_id).result == "skipped"
    with sync_session() as s:  # ensure no stage is still active (reprocess needs that)
        doc = s.get(Document, uuid.UUID(doc_id))
        if doc.insights_status != "succeeded":
            doc.insights_status, doc.status = "succeeded", "ready"
            s.commit()
    # Explicit reprocess of the index stage rewrites the same chunks, no duplicates.
    r = await client.post(f"/documents/{doc_id}/reprocess", params={"stages": "index"})
    assert r.status_code == 202
    run_queued(enqueued)
    second = [(c.ordinal, c.text, c.locator) for c in _chunks(doc_id)]
    assert second == first


async def test_index_transient_failure_then_partial_status(client, enqueued, fake_embeddings):
    doc_id = await _upload(client, "notes.txt", b"Some text worth indexing for the test case.")
    pipeline.execute_stage("extract", doc_id)
    fake_embeddings.fail_with = AIProviderUnavailable("timeout")
    outcome = pipeline.execute_stage("index", doc_id, attempt=1, max_retries=1)
    assert outcome.result == "retry"
    outcome = pipeline.execute_stage("index", doc_id, attempt=2, max_retries=1)
    assert outcome.result == "failed"
    with sync_session() as s:
        doc = s.get(Document, uuid.UUID(doc_id))
        assert (doc.index_status, doc.error_code) == ("failed", "AI_PROVIDER_UNAVAILABLE")
        assert doc.chat_ready_at is None
    assert _chunks(doc_id) == []

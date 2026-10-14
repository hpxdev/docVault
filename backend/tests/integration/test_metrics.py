"""Metrics from seeded data: exact counts, rates with denominators, percentiles, windows, cache."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db.session import sync_session
from app.models import (
    AICall,
    ChatSession,
    Document,
    DocumentInsights,
    Message,
    MessageCitation,
    ProcessingRun,
)

NOW = datetime.now(UTC)


def _doc(name, file_type="pdf", status="ready", pages=10, created=NOW, chat_ready_after_s=None):
    return Document(
        id=uuid.uuid4(),
        filename=name,
        mime_type="application/pdf",
        file_type=file_type,
        size_bytes=1000,
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        storage_path="x",
        page_count=pages,
        status=status,
        extract_status="succeeded",
        index_status="succeeded" if chat_ready_after_s is not None else "failed",
        insights_status="succeeded",
        warnings=[],
        created_at=created,
        updated_at=created,
        chat_ready_at=created + timedelta(seconds=chat_ready_after_s)
        if chat_ready_after_s is not None
        else None,
    )


def _run(doc, stage, status, duration_ms, attempt=1, code=None, started=NOW):
    return ProcessingRun(
        document_id=doc.id,
        stage=stage,
        attempt=attempt,
        status=status,
        started_at=started,
        finished_at=None if status == "running" else started + timedelta(milliseconds=duration_ms),
        duration_ms=None if status == "running" else duration_ms,
        error_code=code,
    )


def _seed():
    with sync_session() as s:
        a = _doc("a.pdf", chat_ready_after_s=2)
        b = _doc("b.pdf", chat_ready_after_s=4)
        c = _doc("c.docx", file_type="docx", status="failed", pages=None)
        old = _doc("old.pdf", pages=30, created=NOW - timedelta(days=3), chat_ready_after_s=10)
        s.add_all([a, b, c, old])
        s.flush()
        s.add_all(
            [
                _run(a, "extract", "succeeded", 100),
                _run(b, "extract", "succeeded", 200),
                _run(c, "extract", "failed", 300, code="CORRUPT_DOCUMENT"),
                _run(old, "extract", "succeeded", 400, started=NOW - timedelta(days=3)),
                _run(a, "index", "retrying", 50, code="AI_PROVIDER_UNAVAILABLE"),
                _run(a, "index", "succeeded", 150, attempt=2),
                _run(b, "index", "running", 0),
                _run(old, "extract", "failed", 999, started=NOW - timedelta(days=9)),
            ]
        )
        for doc, category, tags in ((a, "report", ["budget", "q3"]), (b, "report", ["budget"])):
            s.add(
                DocumentInsights(
                    document_id=doc.id,
                    prompt_version="insights.single.v1",
                    model="fake",
                    summary_short="s",
                    summary_detailed="d",
                    key_points=[],
                    entities={},
                    topics=[],
                    category=category,
                    tags=tags,
                    sentiment={},
                    suggested_questions=[],
                    coverage={},
                )
            )
        s.add_all(
            [
                AICall(
                    purpose="answer",
                    model="gpt-4o-mini",
                    input_tokens=1000,
                    output_tokens=100,
                    estimated_cost_usd=Decimal("0.00021"),
                    status="succeeded",
                ),
                AICall(
                    purpose="embed_query",
                    model="text-embedding-3-small",
                    input_tokens=10,
                    estimated_cost_usd=Decimal("0.0000002"),
                    status="failed",
                    error_code="AI_PROVIDER_UNAVAILABLE",
                ),
            ]
        )
        chat = ChatSession(title="t", scope_mode="documents")
        s.add(chat)
        s.flush()
        specs = [
            ("answered", 400, 1000, 2),
            ("answered", 600, 3000, 1),
            ("not_found", 500, 2000, 0),
        ]
        for i, (answer_status, first, total, n_cit) in enumerate(specs):
            s.add(Message(session_id=chat.id, role="user", content="q", created_at=NOW))
            m = Message(
                session_id=chat.id,
                role="assistant",
                content="a",
                answer_status=answer_status,
                first_token_ms=first,
                total_ms=total,
                model="fake",
                created_at=NOW + timedelta(milliseconds=i + 1),
            )
            s.add(m)
            s.flush()
            for k in range(n_cit):
                s.add(
                    MessageCitation(
                        message_id=m.id,
                        marker=f"S{k + 1}",
                        marker_index=k + 1,
                        document_name="a.pdf",
                        locator={"type": "page", "page": 1},
                        excerpt="x",
                    )
                )
        s.commit()


async def test_document_statistics(client):
    _seed()
    body = (await client.get("/metrics/documents")).json()
    docs = body["documents"]
    assert docs["total"] == 4 and docs["chat_ready"] == 3
    assert docs["by_status"] == {"ready": 3, "failed": 1}
    assert docs["by_file_type"] == {"pdf": 3, "docx": 1}
    assert body["content"]["total_pages"] == 50 and body["content"]["total_bytes"] == 4000
    assert body["content"]["average_pages"] == {"value": 16.6667, "numerator": 50, "denominator": 3}
    days = body["uploads_per_day"]
    assert len(days) == 14 and days[-1] == {"date": NOW.date().isoformat(), "count": 3}
    assert sum(d["count"] for d in days) == 4
    assert body["top_categories"] == [{"category": "report", "count": 2}]
    assert body["top_tags"] == [{"tag": "budget", "count": 2}, {"tag": "q3", "count": 1}]


async def test_processing_ai_and_chat_metrics(client):
    _seed()
    body = (await client.get("/metrics/processing", params={"window": "7d"})).json()
    ext = body["stages"]["extract"]
    assert (ext["started"], ext["succeeded"], ext["failed"]) == (4, 3, 1)
    assert ext["success_rate"] == {"value": 0.75, "numerator": 3, "denominator": 4}
    assert ext["duration_ms"] == {"p50": 250.0, "p95": 385.0, "count": 4}  # 100,200,300,400
    assert ext["failures_by_code"] == {"CORRUPT_DOCUMENT": 1}
    idx = body["stages"]["index"]
    assert (idx["succeeded"], idx["retry_scheduled"], idx["running"], idx["retries"]) == (
        1,
        1,
        1,
        1,
    )
    assert idx["success_rate"] == {"value": 1.0, "numerator": 1, "denominator": 1}
    assert body["stages"]["insights"]["success_rate"]["value"] is None  # 0/0 → null, not 0

    e2e = body["upload_to_chat_ready_ms"]
    assert e2e["count"] == 3 and e2e["p50"] == 4000.0  # 2 s, 4 s, 10 s

    ai = body["ai"]
    assert ai["calls"] == 2 and ai["error_rate"] == {"value": 0.5, "numerator": 1, "denominator": 2}
    assert ai["input_tokens"] == 1010 and abs(ai["estimated_cost_usd"] - 0.0002102) < 1e-12
    assert {(r["purpose"], r["model"]) for r in ai["by_purpose_and_model"]} == {
        ("answer", "gpt-4o-mini"),
        ("embed_query", "text-embedding-3-small"),
    }

    chat = body["chat"]
    assert chat["questions"] == 3 and chat["assistant_messages"] == 3
    assert chat["not_found_rate"] == {"value": 0.3333, "numerator": 1, "denominator": 3}
    assert chat["first_token_ms"] == {"p50": 500.0, "p95": 590.0, "count": 3}
    assert chat["avg_citations_per_answer"] == {"value": 1.5, "numerator": 3, "denominator": 2}
    assert body["queues"] == {"ingest": 0, "ai": 0}


async def test_windows_filter_runs(client):
    _seed()
    all_time = (await client.get("/metrics/processing", params={"window": "all"})).json()
    assert all_time["stages"]["extract"]["started"] == 5  # includes the 9-day-old run
    day = (await client.get("/metrics/processing", params={"window": "24h"})).json()
    assert day["stages"]["extract"]["started"] == 3
    assert (await client.get("/metrics/processing", params={"window": "2y"})).status_code == 422


async def test_metrics_cache_and_invalidation(client):
    _seed()
    first = (await client.get("/metrics/documents")).json()
    second = (await client.get("/metrics/documents")).json()
    assert first["cached"] is False and second["cached"] is True
    assert second["generated_at"] == first["generated_at"]
    await client.post(
        "/documents", files=[("files", ("n.txt", b"new document text", "text/plain"))]
    )
    third = (await client.get("/metrics/documents")).json()
    assert third["cached"] is False and third["documents"]["total"] == 5

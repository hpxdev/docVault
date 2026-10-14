"""Stage execution: status transitions, failure codes, idempotent re-delivery, retries."""

import uuid

from sqlalchemy import func, select

from app.db.session import sync_session
from app.models import Document, DocumentSegment, ProcessingRun
from app.services import pipeline
from app.services.stage_errors import StageError, TransientStageError
from tests import fixtures
from tests.conftest import run_queued


async def _upload(client, name, data):
    r = await client.post("/documents", files=[("files", (name, data, "application/octet-stream"))])
    return r.json()["results"][0]["document"]["id"]


def _doc(doc_id) -> Document:
    with sync_session() as s:
        return s.get(Document, uuid.UUID(doc_id))


def _runs(doc_id, stage=None):
    with sync_session() as s:
        stmt = select(ProcessingRun).where(ProcessingRun.document_id == uuid.UUID(doc_id))
        if stage:
            stmt = stmt.where(ProcessingRun.stage == stage)
        return list(s.scalars(stmt.order_by(ProcessingRun.started_at)))


async def test_extract_writes_segments_and_records_run(client, enqueued):
    doc_id = await _upload(client, "plan.pdf", fixtures.five_page_pdf())
    pipeline.execute_stage("extract", doc_id)
    doc = _doc(doc_id)
    assert doc.extract_status == "succeeded"
    assert doc.page_count == 5 and doc.segment_count == 5
    assert doc.char_count > 0 and doc.token_count > 0
    runs = _runs(doc_id, "extract")
    assert [(r.status, r.attempt) for r in runs] == [("succeeded", 1)]
    assert runs[0].duration_ms is not None


async def test_extract_failure_codes_through_pipeline(client, enqueued):
    cases = {
        "locked.pdf": (fixtures.make_pdf(2, encrypt_password="pw"), "ENCRYPTED_DOCUMENT"),
        "scan.pdf": (fixtures.make_image_only_pdf(), "NO_EXTRACTABLE_TEXT"),
        "huge.pdf": (fixtures.make_pdf(301), "PAGE_LIMIT_EXCEEDED"),
        "broken.pdf": (b"%PDF-1.4\nnot a real pdf", "CORRUPT_DOCUMENT"),
        "utf16.txt": ("hello world".encode("utf-16"), "UNSUPPORTED_ENCODING"),
    }
    ids = {name: await _upload(client, name, data) for name, (data, _) in cases.items()}
    enqueued.clear()
    for name, (_, code) in cases.items():
        outcome = pipeline.execute_stage("extract", ids[name])
        assert outcome.result == "failed", name
        doc = _doc(ids[name])
        assert (doc.status, doc.extract_status, doc.error_code) == ("failed", "failed", code)
        assert _runs(ids[name])[0].error_code == code
    assert enqueued == []  # permanent failures are not retried and nothing downstream runs


async def test_redelivered_task_is_a_no_op(client, enqueued):
    doc_id = await _upload(client, "plan.pdf", fixtures.five_page_pdf())
    assert pipeline.execute_stage("extract", doc_id).result == "succeeded"
    assert pipeline.execute_stage("extract", doc_id).result == "skipped"
    with sync_session() as s:
        count = s.scalar(
            select(func.count()).where(DocumentSegment.document_id == uuid.UUID(doc_id))
        )
    assert count == 5
    assert len(_runs(doc_id, "extract")) == 1
    assert _doc(doc_id).extract_status == "succeeded"


async def test_crashed_run_is_marked_worker_lost_on_redelivery(client, enqueued):
    doc_id = await _upload(client, "plan.pdf", fixtures.five_page_pdf())
    with sync_session() as s:
        pipeline.claim(s, uuid.UUID(doc_id), "extract", 1, "task-1")  # worker dies here
    assert pipeline.execute_stage("extract", doc_id).result == "succeeded"
    runs = _runs(doc_id, "extract")
    assert [(r.status, r.error_code) for r in runs] == [
        ("failed", "WORKER_LOST"),
        ("succeeded", None),
    ]


async def test_transient_error_is_retried_then_succeeds(client, enqueued, monkeypatch):
    doc_id = await _upload(client, "notes.txt", b"some plain text content for the test")
    real = pipeline._STAGE_FUNCS["extract"]
    calls = {"n": 0}

    def flaky(session, doc):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TransientStageError("AI_PROVIDER_UNAVAILABLE", "timeout")
        real(session, doc)

    monkeypatch.setitem(pipeline._STAGE_FUNCS, "extract", flaky)
    first = pipeline.execute_stage("extract", doc_id, attempt=1, max_retries=3)
    assert first.result == "retry" and 0 < first.countdown <= 2
    assert _doc(doc_id).extract_status == "retrying"
    assert _doc(doc_id).status == "processing"
    second = pipeline.execute_stage("extract", doc_id, attempt=2, max_retries=3)
    assert second.result == "succeeded"
    runs = _runs(doc_id, "extract")
    assert [(r.attempt, r.status) for r in runs] == [(1, "retrying"), (2, "succeeded")]


async def test_transient_error_gives_up_after_max_retries(client, enqueued, monkeypatch):
    doc_id = await _upload(client, "notes.txt", b"some plain text content for the test")

    def always_down(session, doc):
        raise TransientStageError("TIMEOUT", "timeout", final_code="AI_PROVIDER_UNAVAILABLE")

    monkeypatch.setitem(pipeline._STAGE_FUNCS, "extract", always_down)
    outcome = pipeline.execute_stage("extract", doc_id, attempt=4, max_retries=3)
    assert outcome.result == "failed"
    doc = _doc(doc_id)
    assert (doc.extract_status, doc.error_code) == ("failed", "AI_PROVIDER_UNAVAILABLE")


async def test_permanent_error_is_not_retried(client, enqueued, monkeypatch):
    doc_id = await _upload(client, "notes.txt", b"some plain text content for the test")

    def bad(session, doc):
        raise StageError("CORRUPT_DOCUMENT", "nope")

    monkeypatch.setitem(pipeline._STAGE_FUNCS, "extract", bad)
    assert pipeline.execute_stage("extract", doc_id, attempt=1).result == "failed"
    assert len(_runs(doc_id)) == 1


async def test_unexpected_exception_fails_with_internal_error(client, enqueued, monkeypatch):
    doc_id = await _upload(client, "notes.txt", b"some plain text content for the test")
    monkeypatch.setitem(pipeline._STAGE_FUNCS, "extract", lambda s, d: 1 / 0)
    assert pipeline.execute_stage("extract", doc_id).result == "failed"
    assert _doc(doc_id).error_code == "INTERNAL_ERROR"


async def test_status_events_are_published(client, enqueued):
    import json

    import redis

    from app.core.config import get_settings

    doc_id = await _upload(client, "plan.pdf", fixtures.five_page_pdf())
    pubsub = redis.Redis.from_url(get_settings().cache_redis_url).pubsub()
    pubsub.subscribe(f"doc:{doc_id}")
    pubsub.get_message(timeout=1)  # subscribe confirmation
    run_queued(enqueued)
    events = []
    while (msg := pubsub.get_message(timeout=0.5)) is not None:
        if msg["type"] == "message":
            events.append(json.loads(msg["data"]))
    stages = [e["stages"]["extract"] for e in events]
    assert stages[:2] == ["running", "succeeded"]
    assert events[0]["status"] == "processing"


async def test_celery_task_retries_transient_errors(client, enqueued, monkeypatch):
    """The real Celery task wrapper (eager mode) retries and then succeeds."""
    from app.workers.celery_app import celery_app
    from app.workers.tasks import extract_task

    doc_id = await _upload(client, "notes.txt", b"some plain text content for the test")
    real = pipeline._STAGE_FUNCS["extract"]
    calls = {"n": 0}

    def flaky(session, doc):
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientStageError("AI_PROVIDER_UNAVAILABLE", "rate limited")
        real(session, doc)

    monkeypatch.setitem(pipeline._STAGE_FUNCS, "extract", flaky)
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True)
    extract_task.apply(args=[doc_id])
    assert calls["n"] == 3
    assert [(r.attempt, r.status) for r in _runs(doc_id, "extract")] == [
        (1, "retrying"),
        (2, "retrying"),
        (3, "succeeded"),
    ]
    assert _doc(doc_id).extract_status == "succeeded"


async def test_concurrent_index_and_insights_end_ready(client, enqueued, monkeypatch):
    """Regression: on the live worker the two stages overlap. Each must derive the status from
    the current locked row, not from the copy loaded when it started."""
    import threading
    import time as _time

    doc_id = await _upload(client, "plan.pdf", fixtures.five_page_pdf())
    pipeline.execute_stage("extract", doc_id)
    index_fn, insights_fn = pipeline._STAGE_FUNCS["index"], pipeline._STAGE_FUNCS["insights"]
    both_started = threading.Barrier(2, timeout=10)

    def slow(fn, delay):
        def run(session, doc):
            both_started.wait()  # both stages have loaded the document while the other runs
            _time.sleep(delay)
            fn(session, doc)

        return run

    monkeypatch.setitem(pipeline._STAGE_FUNCS, "index", slow(index_fn, 0.3))
    monkeypatch.setitem(pipeline._STAGE_FUNCS, "insights", slow(insights_fn, 0.1))
    results = {}
    threads = [
        threading.Thread(target=lambda s=s: results.update({s: pipeline.execute_stage(s, doc_id)}))
        for s in ("index", "insights")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert {s: r.result for s, r in results.items()} == {
        "index": "succeeded",
        "insights": "succeeded",
    }
    doc = _doc(doc_id)
    assert (doc.index_status, doc.insights_status, doc.status) == (
        "succeeded",
        "succeeded",
        "ready",
    )
    assert doc.ready_at is not None and doc.chat_ready_at is not None

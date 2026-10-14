"""Insights: single vs map-reduce, full coverage, page-ref and enum validation, partial status."""

import uuid

from app.ai.errors import AIRequestRejected
from app.core.config import get_settings
from app.db.session import sync_session
from app.models import Document
from app.services import insights as insights_mod
from app.services import pipeline
from tests import fixtures
from tests.conftest import run_queued


async def _upload(client, name, data):
    r = await client.post("/documents", files=[("files", (name, data, "application/octet-stream"))])
    return r.json()["results"][0]["document"]["id"]


def _llm_insights(**overrides):
    base = {
        "summary_short": "A short summary.",
        "summary_detailed": "A longer summary.",
        "key_points": [{"text": "Budget approved at 4.2 million.", "refs": [3]}],
        "entities": {
            "people": [],
            "organizations": ["Project Falcon"],
            "locations": [],
            "dates": ["March"],
            "amounts": ["4.2 million dollars"],
        },
        "topics": ["budget"],
        "category": "report",
        "tags": ["Budget", "budget", "falcon"],
        "sentiment": {"label": "neutral", "rationale": "Factual."},
        "suggested_questions": ["What is the approved budget?"],
    }
    base.update(overrides)
    return base


async def test_single_pass_for_short_document(client, enqueued, fake_chat):
    doc_id = await _upload(client, "plan.pdf", fixtures.five_page_pdf())
    run_queued(enqueued)
    assert [p for p, _ in fake_chat.calls] == ["insights_single"]
    prompt = fake_chat.calls[0][1][-1].content
    for page in range(1, 6):
        assert f"[Page {page}]" in prompt  # whole document with page markers

    r = await client.get(f"/documents/{doc_id}/insights")
    assert r.status_code == 200
    body = r.json()
    assert body["ai_mode"] == "fake" and body["model"] == "fake"
    assert body["prompt_version"] == "insights.single.v1"
    assert body["coverage"]["method"] == "single"
    assert body["coverage"]["segments_covered"] == body["coverage"]["segments_total"] == 5
    assert body["summary_short"].startswith("FAKE AI MODE")
    assert all(set(kp["pages"]) <= {1, 2, 3, 4, 5} for kp in body["key_points"])
    doc = (await client.get(f"/documents/{doc_id}")).json()
    assert doc["status"] == "ready" and doc["ready_at"] and doc["category"] == "other"


async def test_map_reduce_covers_every_segment(client, enqueued, fake_chat, monkeypatch):
    monkeypatch.setattr(get_settings(), "insights_single_pass_max_tokens", 1000)
    monkeypatch.setattr(insights_mod, "MAP_GROUP_TOKENS", 1500)
    doc_id = await _upload(client, "heron.pdf", fixtures.long_pdf(120))
    run_queued(enqueued)

    purposes = [p for p, _ in fake_chat.calls]
    n_maps = purposes.count("insights_map")
    assert n_maps > 3 and purposes == ["insights_map"] * n_maps + ["insights_reduce"]
    map_inputs = [m[-1].content for p, m in fake_chat.calls if p == "insights_map"]
    seen_pages = {
        page for text in map_inputs for page in range(1, 121) if f"[Page {page}]\n" in text
    }
    assert seen_pages == set(range(1, 121))  # every page went to some map call
    assert fixtures.FACT_LAST_PAGE in map_inputs[-1]

    reduce_input = fake_chat.calls[-1][1][-1].content
    for index in range(1, n_maps + 1):
        assert f"[Part {index}:" in reduce_input  # reduce received notes from every part
    assert "(refs: 120)" in reduce_input  # the last page's note reached the reduce step

    body = (await client.get(f"/documents/{doc_id}/insights")).json()
    cov = body["coverage"]
    assert cov["method"] == "map_reduce" and cov["groups"] == n_maps
    assert cov["segments_covered"] == cov["segments_total"] == 120
    assert body["prompt_version"] == "insights.map.v1+insights.reduce.v1"


async def test_invalid_refs_and_enums_are_dropped_and_counted(client, enqueued, fake_chat):
    fake_chat.push(
        _llm_insights(
            key_points=[
                {"text": "Valid point.", "refs": [0, 3, 999]},
                {"text": "Only invalid refs.", "refs": [42]},
                {"text": "No refs at all.", "refs": []},
            ],
            category="banana",
            sentiment={"label": "ecstatic", "rationale": "?"},
            summary_short="word " * 80,
        )
    )
    doc_id = await _upload(client, "plan.pdf", fixtures.five_page_pdf())
    run_queued(enqueued)
    body = (await client.get(f"/documents/{doc_id}/insights")).json()
    assert body["key_points"] == [{"text": "Valid point.", "pages": [3], "sections": None}]
    assert body["category"] == "other"
    assert body["sentiment"]["label"] is None
    assert body["tags"] == ["budget", "falcon"]  # lowercased + deduplicated
    assert len(body["summary_short"].split()) == 61  # 60 words + ellipsis
    v = body["coverage"]["validation"]
    assert v == {
        "dropped_refs": 3,
        "dropped_key_points": 2,
        "invalid_enums": 2,
        "truncated_fields": ["summary_short"],
    }


async def test_docx_key_points_reference_sections_not_pages(client, enqueued, fake_chat):
    fake_chat.push(_llm_insights(key_points=[{"text": "27 days of leave.", "refs": [2, 9]}]))
    doc_id = await _upload(client, "handbook.docx", fixtures.make_docx())
    run_queued(enqueued)
    prompt = fake_chat.calls[0][1][-1].content
    assert '[Section 2: section "Leave Policy"]' in prompt
    body = (await client.get(f"/documents/{doc_id}/insights")).json()
    assert body["key_points"] == [{"text": "27 days of leave.", "pages": [], "sections": [2]}]


async def test_insights_failure_gives_partial_and_chat_still_ready(client, enqueued, fake_chat):
    fake_chat.push(AIRequestRejected("bad request"))
    doc_id = await _upload(client, "notes.txt", b"Plain text that will be indexed fine.")
    run_queued(enqueued)
    doc = (await client.get(f"/documents/{doc_id}")).json()
    assert doc["status"] == "partial"
    assert doc["stages"] == {"extract": "succeeded", "index": "succeeded", "insights": "failed"}
    assert doc["chat_ready"] is True
    assert doc["error"]["code"] == "AI_REQUEST_REJECTED"

    r = await client.get(f"/documents/{doc_id}/insights")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "INSIGHTS_NOT_READY"
    assert r.json()["error"]["details"]["insights_status"] == "failed"

    # Reprocess only the failed stage; it succeeds this time and the document becomes ready.
    r = await client.post(f"/documents/{doc_id}/reprocess")
    assert r.json()["stages"] == ["insights"]
    run_queued(enqueued)
    assert (await client.get(f"/documents/{doc_id}")).json()["status"] == "ready"


async def test_insights_rerun_upserts_one_row(client, enqueued):
    doc_id = await _upload(client, "plan.pdf", fixtures.five_page_pdf())
    run_queued(enqueued)
    with sync_session() as s:
        d = s.get(Document, uuid.UUID(doc_id))
        d.insights_status = "pending"
        s.commit()
    assert pipeline.execute_stage("insights", doc_id).result == "succeeded"
    from sqlalchemy import func, select

    from app.models import DocumentInsights

    with sync_session() as s:
        n = s.scalar(select(func.count()).where(DocumentInsights.document_id == uuid.UUID(doc_id)))
    assert n == 1


async def test_insights_not_ready_while_queued(client, enqueued):
    doc_id = await _upload(client, "plan.pdf", fixtures.five_page_pdf())
    r = await client.get(f"/documents/{doc_id}/insights")
    assert r.status_code == 404
    assert r.json()["error"]["details"]["status"] == "queued"

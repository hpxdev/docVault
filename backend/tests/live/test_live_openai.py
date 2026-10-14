"""LIVE tests against the real OpenAI API. They spend money.

Run only with explicit approval:
    RUN_LIVE_AI_TESTS=1 AI_PROVIDER=openai OPENAI_API_KEY=... pytest -m live -s

Scope (MASTER_PROMPT §9): one end-to-end document (extract → index → insights with the real
models) and a 10-question evaluation (7 answerable with expected page + key phrase, 3 unanswerable
expecting not_found). Results are written to tests/live/.results/live_eval.json and reported by
hand in docs/EVALUATION.md (actual numbers only). Assertions are deliberately loose: the point is
to record what the real model did, not to hide misses.
"""

import json
import os
import time
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import sync_session
from app.models import AICall
from tests.conftest import run_queued
from tests.live.eval_set import QUESTIONS, make_eval_pdf

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE_AI_TESTS") != "1"
        or os.environ.get("AI_PROVIDER") != "openai"
        or not os.environ.get("OPENAI_API_KEY"),
        reason="live AI tests need RUN_LIVE_AI_TESTS=1, AI_PROVIDER=openai and OPENAI_API_KEY",
    ),
]

RESULTS = Path(__file__).parent / ".results" / "live_eval.json"


def _ledger_total() -> Decimal:
    with sync_session() as s:
        return Decimal(s.scalar(select(func.coalesce(func.sum(AICall.estimated_cost_usd), 0))))


async def test_live_end_to_end_and_evaluation(client, enqueued):
    settings = get_settings()
    assert settings.ai_provider == "openai"
    r = await client.post(
        "/documents",
        files=[("files", ("northwind-brief.pdf", make_eval_pdf(), "application/pdf"))],
    )
    doc_id = r.json()["results"][0]["document"]["id"]
    started = time.perf_counter()
    stages = run_queued(enqueued)
    pipeline_s = round(time.perf_counter() - started, 2)
    doc = (await client.get(f"/documents/{doc_id}")).json()
    insights = (await client.get(f"/documents/{doc_id}/insights")).json()

    rows = []
    for q in QUESTIONS:
        sid = (await client.post("/chat/sessions", json={"document_ids": [doc_id]})).json()["id"]
        t0 = time.perf_counter()
        resp = await client.post(f"/chat/sessions/{sid}/messages", json={"content": q.text})
        elapsed = round(time.perf_counter() - t0, 2)
        msg = resp.json().get("assistant_message") or {}
        pages = sorted(
            {c["locator"].get("page") for c in msg.get("citations", []) if c["locator"].get("page")}
        )
        content = msg.get("content", "")
        if q.expected_page is None:
            correct = msg.get("answer_status") == "not_found"
        else:
            correct = (
                msg.get("answer_status") == "answered"
                and q.expected_page in pages
                and q.key_phrase.lower() in content.lower()
            )
        rows.append(
            {
                "question": q.text,
                "expected_page": q.expected_page,
                "key_phrase": q.key_phrase,
                "http_status": resp.status_code,
                "answer_status": msg.get("answer_status"),
                "cited_pages": pages,
                "answer": content,
                "correct": correct,
                "seconds": elapsed,
                "first_token_ms": (msg.get("latency_ms") or {}).get("first_token"),
                "usage": msg.get("usage"),
            }
        )

    result = {
        "date_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "chat_model": settings.openai_chat_model,
        "embedding_model": settings.openai_embedding_model,
        "document": {
            "status": doc["status"],
            "stages": doc["stages"],
            "pipeline_seconds_in_process": pipeline_s,
            "stage_outcomes": stages,
        },
        "insights": {
            k: insights.get(k)
            for k in (
                "summary_short",
                "key_points",
                "category",
                "tags",
                "sentiment",
                "suggested_questions",
                "coverage",
            )
        },
        "questions": rows,
        "score": {
            "correct": sum(r["correct"] for r in rows),
            "total": len(rows),
            "answerable_correct": sum(r["correct"] for r in rows if r["expected_page"]),
            "unanswerable_correct": sum(r["correct"] for r in rows if not r["expected_page"]),
        },
        "ledger_estimated_cost_usd": str(_ledger_total()),
    }
    RESULTS.parent.mkdir(exist_ok=True)
    RESULTS.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["score"]), "cost", result["ledger_estimated_cost_usd"])

    assert doc["status"] == "ready", doc
    assert insights.get("ai_mode") == "openai"
    assert all(r["http_status"] == 200 for r in rows)

"""Five-call, extraction-only summary/compare re-test. Paid execution needs fresh approval."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import sync_session
from app.models import AICall
from app.services.pipeline import execute_stage
from tests import fixtures
from tests.live.eval_set import PAGES, make_eval_pdf

FAKE = os.environ.get("ANALYSIS_RETEST_FAKE_DRY_RUN") == "1"
LIVE = (
    os.environ.get("RUN_ANALYSIS_RETEST") == "1"
    and os.environ.get("RUN_LIVE_AI_TESTS") == "1"
    and os.environ.get("AI_PROVIDER") == "openai"
    and bool(os.environ.get("OPENAI_API_KEY"))
)
pytestmark = [pytest.mark.live, pytest.mark.skipif(not (FAKE or LIVE), reason="opt-in re-test")]


async def test_analysis_retest(client, enqueued, monkeypatch):
    settings = get_settings()
    assert settings.ai_provider == ("fake" if FAKE else "openai")
    monkeypatch.setattr(settings, "ai_spend_limit_usd", 0.006)
    report = {
        "date_utc": datetime.now(UTC).isoformat(),
        "mode": settings.ai_provider,
        "human_review": "NOT REVIEWED",
        "cases": [],
    }

    async def post(label, path, **kwargs):
        response = await client.post(path, **kwargs)
        body = response.json()
        report["cases"].append(
            {"case": label, "http_status": response.status_code, "response": body}
        )
        assert response.status_code < 400, (label, body)
        return body

    async def upload(name, data):
        body = await post("upload:" + name, "/documents", files=[("files", (name, data))])
        doc = body["results"][0]["document"]["id"]
        assert execute_stage("extract", doc).result == "succeeded"
        return doc

    try:
        brief = await upload("northwind-brief.pdf", make_eval_pdf())
        revised = {
            p: [line.replace("41.5", "44.0") for line in lines] for p, lines in PAGES.items()
        }
        version = await post(
            "version",
            f"/documents/{brief}/versions",
            files={"file": ("northwind-revised.pdf", make_eval_pdf(revised))},
        )
        assert execute_stage("extract", version["id"]).result == "succeeded"
        handbook = await upload("employee-handbook.docx", fixtures.make_docx())
        long_doc = await upload("heron-160-pages.pdf", fixtures.long_pdf(160))
        # Extraction enqueues index/insights, but the fixture intercepts dispatch. Never drain
        # those stages: summary/compare require only extracted text, so ingestion costs zero.

        await post(
            "budget_and_risks",
            f"/documents/{brief}/summaries",
            json={"length": "medium", "tone": "executive", "focus": "budget and risks"},
        )
        await post(
            "plain_leave",
            f"/documents/{handbook}/summaries",
            json={"length": "short", "tone": "plain", "focus": "annual leave"},
        )
        with monkeypatch.context() as context:
            context.setattr(settings, "on_demand_max_input_tokens", 2000)
            await post(
                "partial_archive",
                f"/documents/{long_doc}/summaries",
                json={"length": "long", "tone": "technical", "focus": "archive code"},
            )
        await post(
            "budget_comparison",
            "/comparisons",
            json={"document_ids": [brief, version["id"]], "focus": "capital budget"},
        )
        await post(
            "different_documents",
            "/comparisons",
            json={"document_ids": [brief, handbook], "focus": "leave policy and construction"},
        )
    finally:
        with sync_session() as db:
            calls = list(db.scalars(select(AICall).order_by(AICall.created_at)))
            report["ledger"] = [
                {
                    "purpose": c.purpose,
                    "model": c.model,
                    "prompt_version": c.prompt_version,
                    "input_tokens": c.input_tokens,
                    "output_tokens": c.output_tokens,
                    "estimated_cost_usd": str(c.estimated_cost_usd),
                    "status": c.status,
                }
                for c in calls
            ]
        report["estimated_cost_usd"] = str(sum(c.estimated_cost_usd for c in calls))
        report["call_count"] = len(calls)
        path = (
            Path(__file__).parent
            / ".results"
            / ("analysis_retest_fake.json" if FAKE else "analysis_retest_real.json")
        )
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"{report['mode']}: {len(calls)} calls; ${report['estimated_cost_usd']}; {path}")
    assert len(calls) == 5
    assert {c.purpose for c in calls} == {"summary_custom", "compare"}

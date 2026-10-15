"""Custom summaries and comparisons: options, caching, validation, coverage, errors, cleanup."""

import uuid

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import sync_session
from app.models import AICall
from tests import fixtures
from tests.conftest import run_queued

V1_TEXT = b"Leave policy 2025.\n\nEmployees receive 25 days of paid annual leave per year."
V2_TEXT = b"Leave policy 2026.\n\nEmployees receive 27 days of paid annual leave per year."
HANDBOOK_MD = (
    b"# Leave\n\nEmployees receive 25 days of leave.\n\n# Remote work\n\nUp to three days.\n"
)


async def _upload(client, name, data):
    r = await client.post("/documents", files=[("files", (name, data, "application/octet-stream"))])
    return r.json()["results"][0]["document"]["id"]


def _calls(purpose):
    with sync_session() as s:
        return list(s.scalars(select(AICall).where(AICall.purpose == purpose)))


def _last_prompt(fake_chat) -> str:
    purpose, messages = fake_chat.calls[-1]
    return "\n".join(str(m.content) for m in messages)


def _point(text, refs, quote=None, topics=()):
    return {
        "text": text,
        "refs": refs,
        "focus_topics": list(topics),
        "evidence": [{"ref": ref, "quote": quote or text} for ref in refs],
    }


# ---------------------------------------------------------------- custom summaries


async def test_custom_summary_options_cache_and_ledger(client, enqueued, fake_chat):
    doc = await _upload(client, "falcon.pdf", fixtures.five_page_pdf())
    run_queued(enqueued)

    body = {"length": "short", "tone": "executive", "focus": "approved budget"}
    r = await client.post(f"/documents/{doc}/summaries", json=body)
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["cached"] is False and first["ai_mode"] == "fake"
    assert first["prompt_version"] == "summary.custom.v4"
    assert (first["length"], first["tone"], first["focus"]) == (
        "short",
        "executive",
        "approved budget",
    )
    assert first["focus_covered"] is True and first["focus_not_addressed"] == []
    assert first["key_points"] and all(kp["pages"] for kp in first["key_points"])
    assert any(3 in kp["pages"] and "4.2 million" in kp["text"] for kp in first["key_points"])
    assert first["coverage"]["complete"] is True and first["coverage"]["selection"] == "all"
    assert len(first["summary"].split()) <= 80

    prompt = _last_prompt(fake_chat)
    assert "<focus>\napproved budget\n</focus>" in prompt
    assert "busy executive" in fake_chat.calls[-1][1][0].content  # tone rule in the system prompt
    assert "at most 80 words; give at most 3 key points" in fake_chat.calls[-1][1][0].content

    [call] = _calls("summary_custom")
    assert str(call.document_id) == doc and call.prompt_version == "summary.custom.v4"

    # Same options (focus differs only in case and spacing): stored result, no AI call.
    again = await client.post(
        f"/documents/{doc}/summaries",
        json={"length": "short", "tone": "executive", "focus": "  Approved   BUDGET "},
    )
    assert again.json()["cached"] is True and again.json()["id"] == first["id"]
    assert len(_calls("summary_custom")) == 1

    other = await client.post(f"/documents/{doc}/summaries", json={"tone": "plain"})
    assert other.json()["cached"] is False and other.json()["length"] == "medium"
    assert other.json()["focus"] is None and other.json()["focus_covered"] is None

    listed = (await client.get(f"/documents/{doc}/summaries")).json()["items"]
    assert [s["id"] for s in listed] == [other.json()["id"], first["id"]]


async def test_custom_summary_focus_not_in_document(client, enqueued):
    doc = await _upload(client, "falcon.pdf", fixtures.five_page_pdf())
    run_queued(enqueued)
    r = await client.post(f"/documents/{doc}/summaries", json={"focus": "submarine volcanoes"})
    body = r.json()
    assert body["focus_covered"] is False and body["key_points"] == []
    assert body["summary"] == "The document does not address submarine volcanoes."


async def test_custom_summary_lists_focus_topics_the_document_does_not_address(
    client, enqueued, fake_chat
):
    """The real v1 filled a missing "risks" topic with invented content; the real v2 stopped that
    but returned an empty gap list. v3: one verdict per topic, gaps derived on the server."""
    doc = await _upload(client, "falcon.pdf", fixtures.five_page_pdf())
    run_queued(enqueued)
    body = (
        await client.post(
            f"/documents/{doc}/summaries", json={"focus": "approved budget and submarine volcanoes"}
        )
    ).json()
    assert body["prompt_version"] == "summary.custom.v4"
    assert body["focus_covered"] is True
    assert body["focus_not_addressed"] == ["submarine volcanoes"]
    assert body["summary"].endswith("The document does not address submarine volcanoes.")
    assert any("4.2 million" in kp["text"] for kp in body["key_points"])
    system = fake_chat.calls[-1][1][0].content
    assert "never add risks, opinions" in system.lower()
    assert "one focus_topics verdict per requested topic" in system
    assert body["coverage"]["focus_topics"] == [
        {"topic": "approved budget", "addressed": True},
        {"topic": "submarine volcanoes", "addressed": False},
    ]

    # The server derives the gaps from the verdicts, cleaning names (whitespace, duplicates,
    # length); the model's own summary text is not trusted for this.
    fake_chat.push(
        {
            "focus_topics": [
                {"topic": "  budget ", "addressed": True},
                {"topic": "Budget", "addressed": False},  # duplicate: first verdict wins
                {"topic": "risks", "addressed": False},
                {"topic": "x" * 150, "addressed": False},
            ],
            "key_points": [_point("Budget approved.", [3], fixtures.FACT_PAGE3, ["budget"])],
        }
    )
    body = (
        await client.post(f"/documents/{doc}/summaries", json={"focus": "budget and risks"})
    ).json()
    assert body["focus_covered"] is True
    assert body["focus_not_addressed"] == ["risks", "x" * 100]
    listed = (await client.get(f"/documents/{doc}/summaries")).json()["items"]
    assert listed[0]["focus_not_addressed"] == ["risks", "x" * 100]

    # All topics unaddressed → not covered; no verdicts at all → coverage unknown.
    fake_chat.push(
        {
            "focus_topics": [{"topic": "risks", "addressed": False}],
            "key_points": [],
        },
        {"focus_topics": [], "key_points": []},
    )
    none = (await client.post(f"/documents/{doc}/summaries", json={"focus": "risks"})).json()
    assert none["focus_covered"] is False and none["focus_not_addressed"] == ["risks"]
    unknown = (await client.post(f"/documents/{doc}/summaries", json={"focus": "teams"})).json()
    assert unknown["focus_covered"] is None and unknown["focus_not_addressed"] == []


def test_every_summary_prompt_version_is_reproducible():
    from app.prompts import load_prompt
    from app.services.summaries import FOCUS_RULES, VERSION

    assert VERSION in FOCUS_RULES
    for version, (with_focus, without_focus) in FOCUS_RULES.items():
        prompt = load_prompt(version)  # the file exists and parses
        messages = prompt.messages(
            filename="f.pdf",
            marker_kind="[Page N]",
            coverage_note="complete",
            length_rule="short",
            tone_rule="neutral",
            focus_rule=with_focus,
            focus="budget",
            document_text="[Page 1]\nText.",
        )
        assert with_focus in messages[0].content and without_focus


async def test_custom_summary_validates_model_output(client, enqueued, fake_chat):
    doc = await _upload(client, "falcon.pdf", fixtures.five_page_pdf())
    run_queued(enqueued)
    fake_chat.push(
        {
            "focus_topics": [{"topic": "ignored without a focus", "addressed": False}],
            "key_points": [
                _point(fixtures.FACT_PAGE3, [3, 99]),  # 99 is not a page
                _point("Invented point.", [42]),  # no valid ref: dropped
                _point("Teams met weekly to review progress, risks and upcoming milestones.", [1]),
                _point("Further details are available from the programme office on request.", [2]),
                _point(
                    "This section describes routine operational matters for the reporting period.",
                    [4],
                ),
            ],
        }
    )
    body = (await client.post(f"/documents/{doc}/summaries", json={"length": "short"})).json()
    assert len(body["summary"].split()) <= 80
    assert body["summary"] == " ".join(p["text"] for p in body["key_points"])
    assert body["focus_not_addressed"] == []  # no focus requested
    assert [kp["pages"] for kp in body["key_points"]] == [[3], [1], [2]]
    validation = body["coverage"]["validation"]
    assert validation["dropped_refs"] == 2 and validation["dropped_key_points"] == 1
    assert set(validation["truncated_fields"]) == {"key_points"}


async def test_custom_summary_of_long_document_selects_focus_parts(
    client, enqueued, fake_chat, monkeypatch
):
    monkeypatch.setattr(get_settings(), "on_demand_max_input_tokens", 2000)
    doc = await _upload(client, "heron.pdf", fixtures.long_pdf(120))
    run_queued(enqueued)
    body = (
        await client.post(f"/documents/{doc}/summaries", json={"focus": "secret archive code"})
    ).json()
    coverage = body["coverage"]
    assert coverage["complete"] is False and coverage["selection"] == "focus"
    assert coverage["segments_total"] == 120 and 0 < coverage["segments_included"] < 120
    prompt = _last_prompt(fake_chat)
    assert "ZX-48213" in prompt and "[Page 120]" in prompt
    assert "too long to include in full" in prompt
    assert any(kp["pages"] == [120] for kp in body["key_points"])

    spread = (await client.post(f"/documents/{doc}/summaries", json={})).json()["coverage"]
    assert spread["selection"] == "spread" and spread["complete"] is False
    prompt = _last_prompt(fake_chat)
    assert all(f"[Page {n}]\n" in prompt for n in (1, 31, 61, 91))  # spread over the document


async def test_summary_rejects_invented_quotes_and_unaddressed_or_unrelated_topics(
    client, enqueued, fake_chat
):
    doc = await _upload(client, "falcon.pdf", fixtures.five_page_pdf())
    run_queued(enqueued)
    fake_chat.push(
        {
            "focus_topics": [
                {"topic": "budget", "addressed": True},
                {"topic": "risks", "addressed": False},
            ],
            "key_points": [
                _point(fixtures.FACT_PAGE3, [3], topics=["budget"]),
                _point("An invented risk.", [3], fixtures.FACT_PAGE3, ["risks"]),
                _point(
                    "Progress is reviewed weekly.",
                    [1],
                    "Teams met weekly to review progress, risks and upcoming milestones.",
                    ["operations"],
                ),
                _point(
                    "The budget is nine million.", [3], "The budget is nine million.", ["budget"]
                ),
            ],
        }
    )
    body = (
        await client.post(f"/documents/{doc}/summaries", json={"focus": "budget and risks"})
    ).json()
    assert body["summary"] == fixtures.FACT_PAGE3 + " The document does not address risks."
    assert len(body["key_points"]) == 1
    assert body["coverage"]["validation"]["dropped_key_points"] == 3
    assert body["coverage"]["evidence"][0]["sources"] == [{"ref": 3, "quote": fixtures.FACT_PAGE3}]


async def test_partial_summary_missing_topic_is_scoped_to_supplied_parts(
    client, enqueued, fake_chat, monkeypatch
):
    monkeypatch.setattr(get_settings(), "on_demand_max_input_tokens", 500)
    doc = await _upload(client, "heron.pdf", fixtures.long_pdf(30))
    run_queued(enqueued)
    fake_chat.push({"focus_topics": [{"topic": "volcanoes", "addressed": False}], "key_points": []})
    body = (
        await client.post(
            f"/documents/{doc}/summaries", json={"focus": "volcanoes", "length": "short"}
        )
    ).json()
    assert body["coverage"]["complete"] is False
    assert body["summary"].startswith("The selected parts do not address volcanoes.")
    assert "This summary uses selected parts" in body["summary"]
    assert "The document does not address" not in body["summary"]
    assert len(body["summary"].split()) <= 80


def test_summary_word_budget_preserves_notices_and_drops_whole_overlong_point():
    from app.services.insights import Validation
    from app.services.summaries import summary_text

    v = Validation()
    text = summary_text(
        [{"text": "word " * 81}, {"text": "The budget is approved."}],
        ["risks"],
        {"complete": False, "segments_included": 2, "segments_total": 20},
        80,
        v,
    )
    assert text.startswith("The budget is approved.")
    assert "word" not in text and not text.endswith("…")
    assert "selected parts do not address risks" in text
    assert text.endswith("(2 of 20 pages/sections).")
    assert len(text.split()) <= 80 and v.truncated_fields == ["summary"]

    v = Validation()
    compact = summary_text([], ["a b " * 20] * 5, {"complete": True}, 80, v)
    assert "See the missing-topic list." in compact
    assert len(compact.split()) <= 80 and v.truncated_fields == ["summary_notice"]


async def test_custom_summary_errors(client, enqueued, monkeypatch):
    doc = await _upload(client, "notes.txt", b"Some notes about the project timeline.")
    r = await client.post(f"/documents/{doc}/summaries", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DOCUMENT_NOT_EXTRACTED"
    run_queued(enqueued)

    assert (
        await client.post(f"/documents/{doc}/summaries", json={"length": "huge"})
    ).status_code == 422
    assert (
        await client.post(f"/documents/{doc}/summaries", json={"focus": "x" * 201})
    ).status_code == 422
    missing = await client.post(f"/documents/{uuid.uuid4()}/summaries", json={})
    assert missing.status_code == 404
    assert (await client.get(f"/documents/{uuid.uuid4()}/summaries")).status_code == 404

    monkeypatch.setattr(get_settings(), "ai_spend_limit_usd", 0.0)
    r = await client.post(f"/documents/{doc}/summaries", json={})
    assert r.status_code == 429 and r.json()["error"]["code"] == "AI_BUDGET_EXCEEDED"


# ---------------------------------------------------------------- comparisons


async def test_compare_two_versions(client, enqueued, fake_chat):
    v1 = await _upload(client, "leave-2025.txt", V1_TEXT)
    r = await client.post(
        f"/documents/{v1}/versions", files={"file": ("leave-2026.txt", V2_TEXT, "text/plain")}
    )
    v2 = r.json()["id"]
    run_queued(enqueued)

    r = await client.post("/comparisons", json={"document_ids": [v2, v1]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cached"] is False and body["ai_mode"] == "fake"
    assert body["same_document_versions"] is True
    assert [(d["label"], d["id"], d["version"]) for d in body["documents"]] == [
        ("D1", v1, 1),
        ("D2", v2, 2),
    ]  # oldest first, whatever the request order
    assert body["similarities"] == []  # changed year/days; no identical full factual sentence
    for sim in body["similarities"]:
        assert {s["label"] for s in sim["sources"]} == {"D1", "D2"}
        assert all(s["sections"] and s["pages"] == [] for s in sim["sources"])
    [diff] = body["differences"]
    statements = {p["label"]: p["statement"] for p in diff["positions"]}
    assert "25 days" in statements["D1"] and "27 days" in statements["D2"]
    assert all(p["addressed"] for p in diff["positions"])

    prompt = _last_prompt(fake_chat)
    assert "versions of the same document, oldest first" in prompt
    assert '<document label="D1" name="leave-2025.txt" version="1"' in prompt
    [call] = _calls("compare")
    assert call.document_id is None and call.prompt_version == "compare.v2"

    again = (await client.post("/comparisons", json={"document_ids": [v1, v2]})).json()
    assert again["cached"] is True and again["id"] == body["id"]
    assert len(_calls("compare")) == 1
    assert (await client.get(f"/comparisons/{body['id']}")).json()["id"] == body["id"]


async def test_compare_validates_model_output(client, enqueued, fake_chat):
    a = await _upload(client, "falcon.pdf", fixtures.five_page_pdf())
    b = await _upload(client, "handbook.md", HANDBOOK_MD)  # two sections
    run_queued(enqueued)
    fake_chat.push(
        {
            "focus_covered": True,
            "similarities": [
                {  # both sources valid
                    "text": "Both are dated.",
                    "relevant_to_focus": True,
                    "sources": [
                        {"document": "D1", "refs": [1]},
                        {"document": "d2", "refs": [1]},
                    ],
                },
                {  # only one document: not a similarity
                    "text": "Only one.",
                    "relevant_to_focus": True,
                    "sources": [{"document": "D1", "refs": [2]}],
                },
                {  # unknown label and invalid ref
                    "text": "Bad refs.",
                    "relevant_to_focus": True,
                    "sources": [
                        {"document": "D9", "refs": [1]},
                        {"document": "D1", "refs": [77]},
                    ],
                },
            ],
            "differences": [
                {
                    "aspect": "Budget",
                    "relevant_to_focus": True,
                    "positions": [
                        {"document": "D1", "statement": "4.2 million dollars.", "refs": [3]},
                        {"document": "D2", "statement": "It costs 9 million.", "refs": []},
                    ],
                },
                {
                    "aspect": "Leave",
                    "relevant_to_focus": True,
                    "positions": [{"document": "D2", "statement": "25 days.", "refs": [2]}],
                },
                {
                    "aspect": "Nothing cited",
                    "relevant_to_focus": True,
                    "positions": [{"document": "D1", "statement": "Claim.", "refs": [50]}],
                },
                {  # the same statement in every document is not a difference (live finding)
                    "aspect": "Main contractor",
                    "relevant_to_focus": True,
                    "positions": [
                        {"document": "D1", "statement": "Brightline Builders.", "refs": [4]},
                        {"document": "D2", "statement": "brightline  builders", "refs": [1]},
                    ],
                },
            ],
        }
    )
    body = (await client.post("/comparisons", json={"document_ids": [a, b]})).json()
    assert body["similarities"] == []  # valid refs do not establish the generic claim
    budget, leave = body["differences"]
    assert budget["positions"][0]["pages"] == [3] and budget["positions"][0]["addressed"]
    uncited = budget["positions"][1]
    assert uncited["addressed"] is False and "No source was cited" in uncited["statement"]
    assert uncited["sections"] == []
    assert [p["label"] for p in leave["positions"]] == ["D1", "D2"]  # missing D1 filled in
    assert leave["positions"][0]["statement"] == "No position given."
    assert leave["positions"][1]["sections"] == [2]
    validation = body["coverage"]["validation"]
    assert validation["dropped_key_points"] == 5  # 3 similarities + 2 differences
    assert body["same_document_versions"] is False


async def test_compare_shared_passages_and_focus_filter(client, enqueued, fake_chat):
    common = "The lease term is five years."
    other = "The office is in Riverside."
    a = await _upload(client, "first.txt", f"{common}\n{other}\nRent is 100 euros.".encode())
    b = await _upload(client, "second.txt", f"{common}\n{other}\nRent is 200 euros.".encode())
    run_queued(enqueued)
    sources = [{"document": "D1", "refs": [1]}, {"document": "D2", "refs": [1]}]
    fake_chat.push(
        {
            "focus_covered": True,
            "similarities": [
                {"text": common, "sources": sources, "relevant_to_focus": True},
                {"text": "lease", "sources": sources, "relevant_to_focus": True},
                {"text": other, "sources": sources, "relevant_to_focus": False},
                {
                    "text": "Both documents provide structured information.",
                    "sources": sources,
                    "relevant_to_focus": True,
                },
            ],
            "differences": [
                {
                    "aspect": "Location",
                    "relevant_to_focus": False,
                    "positions": [
                        {"document": "D1", "statement": other, "refs": [1]},
                    ],
                }
            ],
        }
    )
    body = (
        await client.post("/comparisons", json={"document_ids": [a, b], "focus": "lease term"})
    ).json()
    assert [p["text"] for p in body["similarities"]] == [common]
    assert body["differences"] == []
    assert body["overview"] == "Compared 2 documents: 1 shared passage and 0 differences."
    assert body["coverage"]["validation"]["dropped_key_points"] == 4


def test_partial_comparison_does_not_turn_absence_into_whole_document_claim():
    from app.ai.schemas import ComparisonV2LLM
    from app.services.comparisons import _positions_valid

    raw = ComparisonV2LLM.model_validate(
        {
            "focus_covered": True,
            "similarities": [],
            "differences": [
                {
                    "aspect": "Budget",
                    "relevant_to_focus": True,
                    "positions": [
                        {"document": "D1", "statement": "Ten euros.", "refs": [1]},
                        {"document": "D2", "statement": "Not addressed", "refs": []},
                    ],
                }
            ],
        }
    )
    labels = {key: {"label": key, "document_id": key, "pdf": True} for key in ("D1", "D2")}
    _, differences, _ = _positions_valid(raw, labels, {"D1": {1}, "D2": {1}}, partial={"D2"})
    assert differences[0]["positions"][1]["statement"] == "Not found in the selected parts."


async def test_new_prompt_versions_do_not_reuse_old_cached_results(client, enqueued):
    from app.models import DocumentComparison, DocumentSummary

    a = await _upload(client, "a.txt", V1_TEXT)
    b = await _upload(client, "b.txt", V2_TEXT)
    run_queued(enqueued)
    first = (await client.post(f"/documents/{a}/summaries", json={})).json()
    comparison = (await client.post("/comparisons", json={"document_ids": [a, b]})).json()
    with sync_session() as db:
        db.get(DocumentSummary, uuid.UUID(first["id"])).prompt_version = "summary.custom.v3"
        db.get(DocumentComparison, uuid.UUID(comparison["id"])).prompt_version = "compare.v1"
        db.commit()
    second = (await client.post(f"/documents/{a}/summaries", json={})).json()
    updated = (await client.post("/comparisons", json={"document_ids": [a, b]})).json()
    assert second["id"] != first["id"] and not second["cached"]
    assert updated["id"] != comparison["id"] and not updated["cached"]
    assert (await client.get(f"/comparisons/{comparison['id']}")).json()[
        "prompt_version"
    ] == "compare.v1"
    listed = (await client.get(f"/documents/{a}/summaries")).json()["items"]
    assert {row["prompt_version"] for row in listed} == {"summary.custom.v3", "summary.custom.v4"}


async def test_compare_errors_and_cleanup(client, enqueued):
    a = await _upload(client, "a.txt", V1_TEXT)
    b = await _upload(client, "b.txt", V2_TEXT)
    c = await _upload(client, "c.txt", b"Unprocessed document.")
    run_queued(enqueued)

    assert (await client.post("/comparisons", json={"document_ids": [a]})).status_code == 422
    dup = await client.post("/comparisons", json={"document_ids": [a, a]})
    assert dup.status_code == 422 and dup.json()["error"]["code"] == "VALIDATION_ERROR"
    five = [str(uuid.uuid4()) for _ in range(5)]
    assert (await client.post("/comparisons", json={"document_ids": five})).status_code == 422
    missing = await client.post("/comparisons", json={"document_ids": [a, str(uuid.uuid4())]})
    assert missing.status_code == 404
    assert (await client.get(f"/comparisons/{uuid.uuid4()}")).status_code == 404

    from app.models import Document

    with sync_session() as s:  # make c not extracted
        d = s.get(Document, uuid.UUID(c))
        d.extract_status, d.status = "failed", "failed"
        s.commit()
    r = await client.post("/comparisons", json={"document_ids": [a, c]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DOCUMENT_NOT_EXTRACTED"

    ab = (await client.post("/comparisons", json={"document_ids": [a, b]})).json()
    focus = (
        await client.post("/comparisons", json={"document_ids": [a, b], "focus": "leave"})
    ).json()
    assert focus["id"] != ab["id"] and focus["focus"] == "leave"
    listed = (await client.get("/comparisons", params={"document_id": a})).json()
    assert listed["total"] == 2
    # Deleting a document removes the comparisons that include it.
    assert (await client.delete(f"/documents/{b}")).status_code == 204
    assert (await client.get("/comparisons")).json()["total"] == 0
    assert (await client.get(f"/comparisons/{ab['id']}")).status_code == 404

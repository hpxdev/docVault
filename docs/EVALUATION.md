# Live evaluation (real OpenAI models)

**Status: two approved real-model runs on 2026-10-15**: the 10-question evaluation below, and a
[demo dry run through the UI](#demo-dry-run-in-real-mode-2026-10-15-approved) further down.

**Evaluation run: 2026-10-15 05:41 UTC.** Everything below is the
actual output of that run. Raw results: [evaluation/live_eval_2026-10-15.json](evaluation/live_eval_2026-10-15.json).

| | |
|---|---|
| Command | `TEST_AI_PROVIDER=openai RUN_LIVE_AI_TESTS=1 docker compose -f compose.test.yml run --rm tests pytest -m live -s` |
| Test | `backend/tests/live/test_live_openai.py` (1 passed, 33.4 s wall time) |
| Models | `gpt-4o-mini` (chat, insights), `text-embedding-3-small` (embeddings) |
| Document | `samples/northwind-brief.pdf`: self-written, 6 pages, one known fact set per page |
| Score | **10 / 10**: 7 / 7 answerable (right page cited + key phrase in answer), 3 / 3 unanswerable → `not_found` |
| AI calls | 22, all succeeded (1 document embedding, 1 insights, 10 query embeddings, 10 answers) |
| Estimated cost | **$0.00164608** (sum of the `ai_calls` ledger; estimate from token counts × `pricing.py`, not an invoice) |

## What this does and does not show

- It shows the real integration working end to end: OpenAI accepted the strict JSON schema for
  insights (0 refs dropped, 0 invalid enum values), the model followed the citation and
  `[NO_ANSWER]` rules on this set, server-side citation mapping pointed at the correct pages, and
  the ledger and spend cap ran against real usage.
- It is a **small, easy, single-document smoke test**, not a benchmark. The document produces
  only 6 chunks (one per page) and top-k is 8, so every question gave the model **all** pages as
  sources. Retrieval ranking still mattered for which source was `S1` (each answer cited only `S1`,
  which was the right page every time), but this run does **not** measure retrieval quality on a
  large or multi-document corpus. Multi-document, follow-up and vault-wide chat were not part of
  the live run.
- Latencies were measured in-process (httpx ASGI transport, no real network hop to the API).

## Pipeline (one document)

Extract → index → insights all `succeeded`; in-process pipeline time 12.5 s (insights call
8.0 s, document embedding 3.3 s, as recorded in the ledger).

Insights (real model output, unedited):
- Summary: "The Northwind Solar Farm project aims to generate 82 gigawatt-hours annually with a
  capacity of 48 megawatts, funded by a 41.5 million euro budget, and includes community benefits
  for Marlow residents."
- 9 key points, each with one page reference, covering pages 1–6, all consistent with the source.
  One wording change: "15-meter" where the document says "15-metre".
- Category `report`; tags solar, energy, budget, community, environment, construction, marlow,
  northwind; sentiment `positive` ("a well-structured overview of a beneficial renewable energy
  project"); 5 suggested questions, all answerable from the document.
- Coverage: single pass, 6/6 segments.

## Questions

| # | Question | Expected | Status | Cited | Answer (verbatim) | Total s | First token ms |
|---|---|---|---|---|---|---|---|
| 1 | What is the installed capacity of the Northwind Solar Farm? | p2 "48" | answered | p2 | The installed capacity of the Northwind Solar Farm is 48 megawatts [S1]. | 2.83 | 2533 |
| 2 | What is the total capital budget? | p3 "41.5" | answered | p3 | The total capital budget is 41.5 million euros [S1]. | 2.85 | 2568 |
| 3 | When did the steering committee approve the budget? | p3 "4 March 2026" | answered | p3 | The steering committee approved the budget on 4 March 2026 [S1]. | 1.84 | 1565 |
| 4 | Who is the main construction contractor? | p4 "Brightline" | answered | p4 | The main construction contractor is Brightline Builders [S1]. | 1.52 | 1388 |
| 5 | How large is the contingency reserve? | p3 "3.2" | answered | p3 | The contingency reserve is 3.2 million euros [S1]. | 1.71 | 1441 |
| 6 | How will vegetation between the panel rows be managed? | p5 "sheep" | answered | p5 | Sheep grazing will be used to manage vegetation between panel rows [S1]. | 1.36 | 1102 |
| 7 | What discount will Marlow residents receive? | p6 "10" | answered | p6 | Residents of Marlow will receive a 10 percent discount on electricity tariffs [S1]. | 1.28 | 1015 |
| 8 | Who is the chief financial officer of the cooperative? | not_found | not_found | — | The documents do not provide information about the chief financial officer of the cooperative. | 1.63 | 1412 |
| 9 | What is the expected internal rate of return of the project? | not_found | not_found | — | The expected internal rate of return of the project is not mentioned in the provided documents. | 1.72 | 1498 |
| 10 | How many wind turbines will be installed at the site? | not_found | not_found | — | The documents do not mention any wind turbines. | 1.39 | 1115 |

Each question ran in a fresh session (no condense call). Answer text above is after server-side
processing (the leading `[NO_ANSWER]` marker is removed for `not_found`).

## Ledger (actual `ai_calls` rows for this run)

| Purpose | Model | Calls | Input tokens | Output tokens | Estimated cost (USD) | Avg latency ms |
|---|---|---|---|---|---|---|
| answer | gpt-4o-mini | 10 | 6,403 | 167 | 0.00106065 | 1151 |
| insights_single | gpt-4o-mini | 1 | 1,165 | 671 | 0.00057735 | 8006 |
| embed_document | text-embedding-3-small | 1 | 311 | 0 | 0.00000622 | 3294 |
| embed_query | text-embedding-3-small | 10 | 93 | 0 | 0.00000186 | 606 |
| **Total** | | **22** | | | **0.00164608** | |

Token sources: chat tokens should come from OpenAI's usage metadata (`stream_usage=True`). The
ledger does not record whether the local fallback was used. Indirect check: rebuilding question
1's prompt locally gives 632 o200k tokens (what the fallback would have stored). The message's
usage (655 input tokens in the raw JSON) also includes its 12-token query embedding, so the
answer call itself recorded 643. The +11 difference is consistent with provider-counted chat
framing, so these counts are very likely provider-reported. (An earlier version of this file
compared 632 with 655; corrected 2026-10-15.)

Per-question `usage` in the raw JSON is the **sum for the message** (query
embedding + answer): 6,496 input tokens in total = 6,403 (answer) + 93 (embed_query). Embedding tokens are always counted locally with `cl100k_base`
(LangChain's `OpenAIEmbeddings` returns no usage).

## Not verified by this run

- Retrieval quality on larger or multi-document corpora; vault-wide (HNSW) search.
- Condensed follow-ups and multi-turn behaviour with the real model.
- Map-reduce insights with the real model (the document was far below the 60K-token threshold).
- DOCX/MD/TXT documents with the real model.
- Behaviour under OpenAI errors (rate limits, timeouts) against the real API; covered only by
  fake-mode tests.
- Answer quality in general: 10 easy questions on one clean document is not a quality claim.

---

# Demo dry run in real mode (2026-10-15, approved)

Run through the UI (http://localhost:5173, `docker compose` stack, `AI_PROVIDER=openai`, fresh
volumes) following [DEMO_SCRIPT.md](DEMO_SCRIPT.md). Files were dropped with real browser drag
events; questions were typed into the composer. Six questions in total. Everything below is from
that run's API responses and `ai_calls` ledger.

## Ingestion (step 2–3)

| File | Outcome | Upload → chat-ready | Upload → ready (insights) |
|---|---|---|---|
| `northwind-brief.pdf` | accepted; dropped again → "already in vault" | 4.1 s | 14.8 s |
| `employee-handbook.docx` | accepted | 3.8 s | 9.5 s |
| `not-a-document.exe` | rejected `UNSUPPORTED_FILE_TYPE` | — | — |
| `onboarding-guide.md` (step 7 extra) | accepted | 1.4 s | 6.3 s |

Insights (real model): PDF → category `report`, 9 key points each with one correct page, 6/6
pages covered; DOCX → category `manual`, 4 key points referencing sections 2–3 (no pages),
3/3 sections covered; nothing dropped by validation. The PDF summary again wrote "15-meter" for
"15-metre". The DOCX key point "The company provides a home office equipment allowance of 450 EUR"
paraphrases a table row ("Home office | 450 EUR").

## Questions

| # | Question (session) | Status | Answer (stored, verbatim) | Citations | First token / total |
|---|---|---|---|---|---|
| 1 | What is the total capital budget? (demo chat) | answered | The total capital budget is 41.5 million euros [S1]. | brief p3 | 2.0 s / 2.2 s |
| 2 | When was it approved? (demo chat, follow-up) | answered | The budget was approved on 4 March 2026 [S2]. | brief p3 | 3.5 s / 3.7 s |
| 3 | Who is the CFO? (demo chat) | not_found | The sources do not provide information about the CFO. | — | 2.4 s / 2.6 s |
| 4 | How many days of annual leave do employees get, and when does construction of the solar farm start? (demo chat) | answered | Employees receive 27 days of paid annual leave per year [S1]. Construction of the solar farm is planned to start in June 2026 [S2]. | handbook "Leave Policy"; brief p4 | 2.3 s / 2.6 s |
| 5 | Give a detailed, section by section overview of everything both documents say. (demo chat; **Stop** pressed) | unsupported, `interrupted: true` | `[` (first token only) | — | 2.7 s / 3.4 s |
| 6 | What is the VPN client called? (new chat, **Search entire vault**, 3 documents in scope) | answered | The VPN client is called Tunnelbear-X [S1]. | onboarding guide "Onboarding Guide > Accounts" | 2.3 s / 2.3 s |

Latency is measured by the server from receiving the question (condense + embedding +
retrieval + generation), with the browser on the same machine.

## Findings

1. **Follow-up not rewritten.** For question 2 the condense call ran (170 input tokens) and
   returned the question unchanged (5 output tokens), so `standalone_query` was "When was it
   approved?". The answer was still correct because "approved" alone retrieves page 3, but
   `chat.condense.v1` did not resolve "it" with `gpt-4o-mini`. All four condense calls in this
   run (questions 2–5) returned the question unchanged; the other three were already standalone. Its rule "if the question is
   already standalone, return it unchanged" probably wins here. Not fixed in this run; a
   `chat.condense.v2` with an explicit example would need a re-test.
2. **Multi-document answer cited both documents** (two citations, correct section and page), but
   did not name the documents in the text as rule 6 of `chat.answer.v1` asks. The citation chips
   carry the document names.
3. **Stop works over a real stream:** the stop flag was set within 66 ms of sending; the server
   stopped at the first token and saved the partial answer (`interrupted: true`). The ledger row
   for that answer has `status = interrupted` (728 input tokens counted locally, 1 output).
   Two follow-up fixes were made after this run (see ai-log): the stop flag is now checked
   before the embedding and answer calls (an early Stop paid for them here), and the UI shows a
   stopped answer as "Stopped" instead of the "no verifiable citation" warning.
4. The UI's FAKE AI MODE banner stayed visible for up to 30 s after the mode switch in an
   already open tab (readiness is polled every 30 s); a reload cleared it.

## Ledger for this run

| Purpose | Model | Status | Calls | Input tokens | Output tokens | Estimated cost (USD) |
|---|---|---|---|---|---|---|
| insights_single | gpt-4o-mini | succeeded | 3 | 3,205 | 1,375 | 0.00130575 |
| answer | gpt-4o-mini | succeeded | 5 | 3,608 | 91 | 0.00059580 |
| answer | gpt-4o-mini | interrupted | 1 | 728 | 1 | 0.00010980 |
| condense | gpt-4o-mini | succeeded | 4 | 845 | 44 | 0.00015315 |
| embed_document | text-embedding-3-small | succeeded | 3 | 583 | 0 | 0.00001166 |
| embed_query | text-embedding-3-small | succeeded | 6 | 58 | 0 | 0.00000116 |
| **Total** | | | **22** | | | **0.00217732** |

**Project AI spend so far (sum of both ledgers):** $0.00164608 (evaluation) + $0.00217732
(dry run) = **$0.00382340**, estimated.

---

# `chat.condense.v2` re-test (2026-10-15, approved)

Why: in the demo dry run `chat.condense.v1` returned "When was it approved?" unchanged. v2
defines "standalone" precisely (any reference word or missing subject means "rewrite") and adds
three examples from an unrelated domain (an office lease), so it isn't tuned to the test.
Run: a new chat on `northwind-brief.pdf` through the API (`POST /chat/sessions/{id}/messages`),
real mode, one base question then three follow-ups.

| # | Question | Standalone query produced by v2 | Status | Answer (stored) | Verdict |
|---|---|---|---|---|---|
| 0 | What is the total capital budget? | (first turn, not condensed) | answered, p3 | The total capital budget is 41.5 million euros [S1]. | ✓ |
| 1 | When was it approved? | When was the total capital budget of 41.5 million euros approved? | answered, p3 | The total capital budget of 41.5 million euros was approved on 4 March 2026 [S1]. | ✓ **fixed** (v1 left it unchanged) |
| 2 | And what is its installed capacity? | What is the installed capacity of the total capital budget? | not_found | The sources do not provide a relationship between the installed capacity and the total capital budget. | ✗ **wrong rewrite** |
| 3 | Who is the CFO? | Who is the CFO? (unchanged) | not_found | The documents do not mention the CFO. | ✓ (control) |

**Reading the miss honestly:** the conversation never named the solar farm, only "the total
capital budget", so "its" had no correct antecedent in the conversation and v2 bound it to the
only candidate. The test question was ambiguous by design of the conversation, but a user would
expect "its" to mean the project. v1 would most likely have left the question unchanged, and
retrieval on "installed capacity" would then have found page 2. v2 therefore fixes the case
where the referent is in the conversation and is worse when it isn't. The answer step still
refused instead of inventing a number. A possible v3 (not done): give the condense prompt the
names of the documents in scope, and tell it to leave a reference unresolved rather than bind it
to an unrelated noun.

**Decision:** v2 is the active version (the pipeline sets `CONDENSE_VERSION = "chat.condense.v2"`;
`chat.condense.v1.md` is kept), because the miss needs a conversation that never names the
referent. This is a judgement call based on four questions, not a measured improvement.

| Purpose | Prompt | Calls | Input tokens | Output tokens | Estimated cost (USD) |
|---|---|---|---|---|---|
| answer | chat.answer.v1 | 4 | 2,562 | 74 | 0.00042870 |
| condense | chat.condense.v2 | 3 | 1,191 | 31 | 0.00019725 |
| embed_query | — | 2 | 26 | 0 | 0.00000052 |
| **Total** | | **9** | | | **0.00062647** |

Two query embeddings were served from the 7-day cache (the same questions as in the dry run).

**Project AI spend so far (estimated, both ledgers):** $0.00164608 (evaluation) + $0.00217732
(dry run) + $0.00062647 (this re-test) = **$0.00444987**.

---

# Custom summary and version comparison: first real check (2026-10-15, approved)

Why: `summary.custom.v1` and `compare.v1` had run only against the fake model. Run: the main
stack rebuilt in real mode (migration 0002 applied to the dry-run data; the existing documents
became version 1), then through the API: `samples/northwind-brief-v2.pdf` uploaded as version 2
of `northwind-brief.pdf` (`POST /documents/{id}/versions`), one custom summary of v2, and one
comparison of v1 and v2. The UI was not used for this run. Ground truth: the v2 sample changes
exactly five facts (budget 41.5 → 44.0 million euros, approval 4 March → 12 May 2026,
contingency 3.2 → 3.6 million, construction June → September 2026, grid connection Q2 → Q4
2027, all on pages 3–4) plus the title on page 1 ("revised May 2026"); pages 2, 5 and 6 are
unchanged.

## Version 2 ingestion

Processed like any upload: chat-ready and insights done within about 10 s; `is_latest` moved from
v1 to v2; v1 kept.

## Custom summary (v2; `short`, `executive`, focus *budget and risks*), 3.9 s

Stored output (verbatim):

> The Northwind Solar Farm project has a total capital budget of 44 million euros, including a
> contingency reserve of 3.6 million euros, approved on 12 May 2026. Construction is set to begin
> in September 2026, with grid connection expected in Q4 2027. Key risks include potential delays
> in construction and grid connection timelines.

| Key point | Cited page | Verdict |
|---|---|---|
| The total capital budget is 44 million euros, including a contingency reserve of 3.6 million euros. | 3 | ✓ |
| Construction is planned to start in September 2026, with grid connection targeted for Q4 2027. | 4 | ✓ |
| Key risks include potential delays in construction and grid connection timelines. | 4 | ✗ **not in the document** |

- Length rule kept (≈ 54 words of the 80 allowed, 3 of 3 key points); executive tone (figures,
  dates first); every figure correct; server validation dropped nothing.
- **Finding: the model invented the "risks" content.** The brief has no risks section; the third
  point (and the last summary sentence) is an inference, cited to page 4, and `focus_covered`
  was `true` although only half of the focus is in the document. The server cannot catch this:
  page 4 exists and was provided (no entailment check). Proposed, not done: a
  `summary.custom.v2` that tells the model to say which part of a multi-part focus the document
  does not address, and never to infer risks, opinions or consequences that are not stated.

## Comparison (v1 vs v2, no focus), 8.9 s

- **Labels:** D1 = `northwind-brief.pdf` (v1), D2 = `northwind-brief-v2.pdf` (v2);
  `same_document_versions: true`. Both documents included in full.
- **Overview:** "The documents D1 and D2 are versions of the Northwind Solar Farm project brief,
  detailing project specifications for the steering committee. Both documents share key project
  details but differ in budget, schedule, and approval dates." ✓

| Difference (aspect as returned) | D1 → D2 (statements as returned) | Pages | Verdict |
|---|---|---|---|
| Total capital budget | 41.5 → 44.0 million euros | 3 / 3 | ✓ |
| Approval date of budget | 4 March 2026 → revised budget 12 May 2026 | 3 / 3 | ✓ |
| Contingency reserve | 3.2 → 3.6 million euros | 3 / 3 | ✓ |
| Construction start date | June → September 2026 | 4 / 4 | ✓ |
| Grid connection target date | Q2 → Q4 2027 | 4 / 4 | ✓ |
| Document revision date | "Not addressed" → "This brief summarises the Northwind Solar Farm project (revised May 2026)." | — / 1 | ✓ fact, but the D2 statement merges two page-1 lines (paraphrase, not a quote) |
| Main contractor | Brightline Builders → Brightline Builders | 4 / 4 | ✗ **identical: not a difference** |
| Community fund | 50,000 euros per year → the same | 6 / 6 | ✗ **identical: not a difference** |

- **All five changed facts found**, each with the right page in both versions and statements
  quoted word for word. **6 similarities**, all correct and correctly cited (sponsor, location,
  capacity, panels, generation, hedgerow buffer). No dropped refs.
- **Finding: two padded "differences"** whose statements are identical in both versions (the
  prompt allows up to 8 and the model filled the list). **Fixed after the run** on the server, at
  no cost: a difference whose positions cite every document with the same statement (compared
  case-, whitespace- and full-stop-insensitively) is now dropped and counted
  (`validation.dropped_key_points`); test added. The comparison stored by this run predates the
  fix and still contains the two rows (stored results are reused as they are). The fix is
  verified by the fake-mode test, not by a second real run.

## Ledger for this run (actual `ai_calls` rows)

| Purpose | Model | Prompt | Input tokens | Output tokens | Latency | Estimated cost (USD) |
|---|---|---|---|---|---|---|
| embed_document | text-embedding-3-small | — | 331 | 0 | 2.9 s | 0.00000662 |
| insights_single | gpt-4o-mini | insights.single.v1 | 1,175 | 693 | 11.3 s | 0.00059205 |
| summary_custom | gpt-4o-mini | summary.custom.v1 | 838 | 162 | 3.3 s | 0.00022290 |
| compare | gpt-4o-mini | compare.v1 | 1,542 | 778 | 8.9 s | 0.00069810 |
| **Total** | | | | | | **0.00151967** (4 calls) |

**Project AI spend so far (estimated):** $0.00444987 before this run + $0.00151967 =
**$0.00596954**.

## Not shown by this run

One document pair and one summary. Long documents (partial coverage), comparisons of different
documents, comparisons with a focus, other lengths and tones, and the UI in real mode were not
exercised with the real model.

---

# `summary.custom.v2` re-test (2026-10-15, approved)

Why: in the first real check `summary.custom.v1` invented a "risks" key point for the focus
*budget and risks* and reported the focus as covered. v2 (active; v1 kept) adds: never infer
risks, problems, benefits, opinions, consequences or recommendations; treat each focus topic
separately; list topics the document does not address in a new structured field
`focus_not_addressed` (placed **before** the summary in the schema, so the model decides the gaps
first) and end the summary with one sentence saying so; an example from an unrelated domain (a
lease, "rent and penalties"). Migration 0003 adds the column. Run: real mode, API only, the same
document (`northwind-brief-v2.pdf`) and options as before, plus one control whose topics are all
in the document. v2 has a new cache key, so both were real calls.

| Request (short, executive) | Summary (verbatim) | Key points (pages) | `focus_not_addressed` | Verdict |
|---|---|---|---|---|
| focus *budget and risks* (same as the v1 run) | The Northwind Solar Farm project has a total capital budget of 44.0 million euros, approved on 12 May 2026, which includes a contingency reserve of 3.6 million euros. Construction is set to begin in September 2026, with grid connection expected in Q4 2027. The document does not address specific risks associated with the project. | budget + contingency (3); construction + grid (4); approval 12 May 2026 (3) | `[]` | ✓ **invented risk gone**, gap stated in the text; ✗ the structured list is **empty** although the text names the gap |
| focus *budget and schedule* (control) | The Northwind Solar Farm project has a total capital budget of 44.0 million euros, approved on 12 May 2026, including a contingency reserve of 3.6 million euros. Construction is scheduled to begin in September 2026, with grid connection targeted for the fourth quarter of 2027. | budget + approval + contingency (3); construction + grid (4) | `[]` | ✓ correct, no gap sentence |

- Every figure, date and page is correct in both; 54 and 45 words (limit 80); no refs dropped.
- **What v2 fixed:** the content problem. The model no longer fills a missing topic with an
  inference; it says the document does not address it.
- **What it did not fix:** the structured field. With one run, the model wrote the gap sentence
  but returned `focus_not_addressed: []`, so the UI's "Not in the document: …" note would not
  appear for this summary (the summary text still says it). `focus_covered: true` is correct
  under v2's definition (one of the two topics is addressed).
- **Possible next step (not done):** ask for one entry per focus topic
  (`focus_topics: [{topic, addressed}]`), which is harder to skip than an optional list, and
  derive the gaps on the server. That would need another small real run to verify.
- Not shown: other documents, focuses, lengths and tones; one run per request (no repeat runs,
  so no evidence on variance); the UI in real mode.

| Purpose | Prompt | Input tokens | Output tokens | Latency | Estimated cost (USD) |
|---|---|---|---|---|---|
| summary_custom | summary.custom.v2 | 1,125 | 176 | 4.1 s | 0.00027435 |
| summary_custom | summary.custom.v2 | 1,125 | 154 | 2.6 s | 0.00026115 |
| **Total** | | | | | **0.00053550** (2 calls) |

**Project AI spend so far (estimated):** $0.00596954 + $0.00053550 = **$0.00650504**.

---

# `summary.custom.v3` re-test (2026-10-15, approved)

Why: with v2 the model wrote "the document does not address risks" in the summary but left the
optional `focus_not_addressed` list empty. v3 (active; v1 and v2 kept) replaces it with a
required verdict per focus topic, `focus_topics: [{topic, addressed}]`, placed first in the
schema; the server derives `focus_not_addressed` (topics with `addressed: false`) and
`focus_covered` (any topic addressed) and stores the verdicts in `coverage.focus_topics`. The
focus rule of every prompt version now lives in a per-version table, so v1 and v2 stay
reproducible (v2 had overwritten v1's rule in code). Run: real mode, API, same document and
options as the two earlier runs, plus the same control.

| Request (short, executive) | `focus_topics` (model) | `focus_not_addressed` (server) | Summary (verbatim) | Key points (pages) | Verdict |
|---|---|---|---|---|---|
| focus *budget and risks* | budget: addressed; risks: **not addressed** | `["risks"]` | The total capital budget for the Northwind Solar Farm project is 44.0 million euros, approved by the steering committee on 12 May 2026, which includes a contingency reserve of 3.6 million euros. The document does not address risks. | budget + contingency (3) | ✓ gap structured and stated, nothing invented |
| focus *budget and schedule* (control) | budget: addressed; schedule: addressed | `[]` | The total capital budget for the Northwind Solar Farm is 44.0 million euros, approved on 12 May 2026, including a contingency reserve of 3.6 million euros. Construction is set to begin in September 2026, with grid connection targeted for the fourth quarter of 2027. | budget + contingency (3); construction + grid (4) | ✓ |

- Every figure, date and page correct; 38 and 44 words (limit 80); no refs dropped.
- Compared with v2, the *budget and risks* summary no longer mentions the schedule, which was
  outside the focus.
- **UI (real stack):** the same options in the Library drawer returned the stored result
  ("stored result (no AI cost)"; ledger unchanged at 43 calls) and showed the amber note "Not in
  the document: risks". This is the first browser check of that note.

**Across the three runs of the same request:** v1 invented a risks point; v2 stated the gap
only in the text; v3 returns it as data and in the text. One run per version: this shows the
failure mode is fixed for this case, not that it can never recur.

| Purpose | Prompt | Input tokens | Output tokens | Latency | Estimated cost (USD) |
|---|---|---|---|---|---|
| summary_custom | summary.custom.v3 | 1,221 | 114 | 3.0 s | 0.00025155 |
| summary_custom | summary.custom.v3 | 1,221 | 155 | 2.4 s | 0.00027615 |
| **Total** | | | | | **0.00052770** (2 calls) |

**Project AI spend so far (estimated):** $0.00650504 + $0.00052770 = **$0.00703274**.

## Codex continuation, 2026-10-15: verification only, no new real run

Post-bonus clean-clone checks passed: 145 tests, 2 live tests deselected; lint/format,
frontend build and expanded fake-mode walkthrough including rate limiting.
See [CLEAN_CLONE_CHECK.md](CLEAN_CLONE_CHECK.md) for commands, snapshot and actual outcomes.

`chat.condense.v3` is implemented and running. Real-model improvement is **NOT VERIFIED**.
The [broader evaluation plan](BROAD_EVALUATION_PLAN.md) covers multi-document/repeat answers,
follow-ups, long-document map-reduce and partial coverage, injection scope, summaries,
comparisons and v2/v3 A/B rewrites. Its fake rehearsal passed with 42 zero-cost ledger calls;
this is harness evidence, not real-model quality evidence. Explicit spend approval is pending.

The README summary screenshot shows a pre-existing real-model v3 summary (budget and risks)
and retained versions, read from cache. No new model output was generated for the screenshot.
The current demo ledger stayed at 43 calls / $0.00674021. That differs from the handover's
historical cumulative spend; neither historical evidence nor current data was altered.
# Broader real evaluation (2026-10-15, approved)

**Outcome:** the harness completed, but several generated summaries/comparisons failed
semantic expectations. Do not treat the passing test as an all-correct quality score.
The developer explicitly approved the proposed approximately 42 calls, estimated $0.01 with
a $0.015 allowance. No follow-up paid calls or prompt iterations were made.

**Execution:** `TEST_AI_PROVIDER=openai RUN_LIVE_AI_TESTS=1 docker compose -f compose.test.yml
run --rm -e RUN_BROAD_AI_EVAL=1 tests pytest -m live tests/live/test_broad_evaluation.py -q -s`.
Observed output: **1 passed in 90.55 s; 42 ledger calls, $0.00791661 estimated**.
All 42 rows recorded succeeded. Models: gpt-4o-mini and text-embedding-3-small.
The test used its separate Postgres/Redis, never the demo database. It temporarily lowered
its ledger cap to $0.01; the cap was not reached.

[Raw responses and per-call ledger](evaluations/broad-2026-10-15.json), copied byte-for-byte
from the test output before any test-state reset. SHA-256:
`faee4861e33c7e48ee3f5502a7aa44071b037523e7af6aa70e715c821b654eb6`.
The raw `human_review: NOT REVIEWED` is deliberately retained: the review below is by Codex,
not a claim that the developer reviewed the output.

## Chat and ingestion review

| Case | Observed result | Assessment |
|---|---|---|
| Multi-document question, two independent answer generations | Both returned 27 annual-leave days, cited handbook section Leave Policy; June 2026 construction, cited brief page 4. Outputs were identical | Correct in both repeats; no measured answer variance for this one request |
| Budget | 41.5 million euros, brief page 3 | Correct |
| Active-v3 approval follow-up | Rewritten to "When was the total capital budget approved?"; answered 4 March 2026, page 3 | Correct through full pipeline |
| Last-page retrieval | ZX-48213, page 160 | Correct |
| Injection-scope request | Requested the other document's archive code while scoped only to the injection PDF; returned not_found, no citations and no code | Correct refusal/scope behaviour for one adversarial input |
| Long-document insights | 160/160 segments, two map groups, reduce result included ZX-48213 cited to page 160 | Branch/last-page check passed; some interpretive prose was not explicit in source text |

Five chat answers were grounded in the expected pages/section; the sixth correctly returned
not_found. No general accuracy percentage is inferred from this synthetic set.

The Heron PDF contains repetitive routine-operations/weekly-meeting text and the final-page
code. Map-reduce was deliberately forced at 4,000 tokens, retaining production 8,000-token map
grouping. This was not a run beyond the default 60,000-token branch threshold or a load test.
Its detailed summary says the document "emphasizes the importance of these meetings for
project management"; that emphasis is an interpretation, not an explicit fixture statement.
Coverage counts input segments, not semantic completeness or fidelity.

## Rewrite A/B: identical budget history, two generations per question and version

History: User asks the total capital budget; assistant says it is 41.5 million euros.
No project or solar farm is named in the history. Only v3 additionally receives the scoped
filename `northwind-brief.pdf`.

| Follow-up | v2 output in both repeats | v3 output in both repeats | Assessment |
|---|---|---|---|
| When was it approved? | When was the total capital budget approved? | When was the total capital budget approved? | Both correct |
| And what is its installed capacity? | What is the installed capacity of the total capital budget? | And what is its installed capacity? | v2 wrong twice; v3 correctly preserves ambiguity twice |
| Who is the CFO? | Who is the CFO? | Who is the CFO? | Both correctly unchanged |

V3 met the intended behaviour in all six outputs for these three cases. This is evidence
for the known correction, not proof of general reference resolution. Named competing entities,
different filenames and held-out histories were not tested. Repeated A/B calls were linked
to the budget message solely for ledger ownership; they were not new chat turns.

## Summaries and comparisons: important limitations

| Case | Correct behaviour | Limitation found |
|---|---|---|
| Short/plain annual-leave summary | 27 days, up to 5 carried over, section 2; no fabricated DOCX pages | No issue found in this result |
| Medium/executive budget-and-risks summary | Correct figures/dates and pages; focus verdict correctly returned risks=false and focus_not_addressed=[risks] | Summary omitted the required missing-risks sentence and included unrelated schedule/panel/generation details. Structured gap reporting worked; focus/prose rules did not fully hold |
| Long/technical partial Heron summary | Correct code, page 160; complete=false, 28/160 segments, 1,800-token input budget | Added "The document does not address any other topics." This is unsupported and false for a document that also discusses routine operations/meetings; partial coverage makes the whole-document claim even less justified |
| Budget-focused version comparison | Correct sole retained change: 41.5 to 44.0 million euros, page 3 in both; full coverage | Six similarities included off-focus sponsor/location/capacity/generation/community details. Validator reported three dropped_key_points; raw pre-validation comparison output was not retained, so their exact content/reason cannot be reconstructed from this record |
| Different-document comparison | Correct leave-policy section and construction page, with missing counterparts marked Not addressed | Added a generic similarity, "Both documents provide structured information relevant to their respective topics." Its page-1/section-1 citations do not establish this as a shared stated fact; this violates the prompt's stated-facts rule |

Citation validation confirms allowed source identities and locations; it does not prove that
the cited text supports a claim. The gaps above remain present in the active summary/compare
prompts. No output was edited to disguise them and no new prompt version was introduced here.
Potential follow-ups: enforce missing-topic prose from structured verdicts, constrain claims
about partial coverage, improve focus adherence and evaluate evidence-bearing similarities.
These require scoped implementation and fresh evaluation, not a claim of reliability from
this run alone.

## Ledger totals (estimates, not invoices)

| Purpose | Calls | Estimated USD |
|---|---:|---:|
| embed_document | 6 | 0.00023232 |
| embed_query | 5 | 0.00000114 |
| insights_single | 4 | 0.00178905 |
| insights_map | 2 | 0.00198615 |
| insights_reduce | 1 | 0.00044730 |
| answer | 6 | 0.00069030 |
| condense | 13 | 0.00089325 |
| summary_custom | 3 | 0.00097800 |
| compare | 2 | 0.00089910 |
| **Total** | **42** | **0.00791661** |

The preserved demo ledger remained **43 calls / $0.00674021**. The two currently retained
ledgers total **85 calls / $0.01465682**. This is a sum of observed ledger snapshots, not a
reconstruction of every historical call. Earlier docs reported cumulative $0.00703274 before
this run; that differs from the retained demo snapshot and has not been silently rewritten.

Still not verified: general injection resistance, default-threshold long-token behaviour,
scale, slow-stream Stop, summary/comparison repeat variability, or broad grounding quality
across real-world documents. This run was API-based, not a new browser evaluation.
## Summary v4 / comparison v2 corrections (2026-10-15; no new paid calls)

Following the broader run, Codex added versioned corrections without editing older prompts:
summary v4 returns cited points with exact evidence quotes and topic links; the server builds
prose and missing-topic/partial-input notices. Comparison v2 retains only identical cited
shared sentences and builds its overview from retained counts. The UI scopes partial-input
gaps to selected parts and labels similarities Shared passages, with a recall-limit note.
See [PROMPTS.md](PROMPTS.md) for exact rules and remaining semantic risks.

**Verification:** 151 passed, 3 live tests deselected in 59.22 s; ruff passed; frontend
TypeScript/Vite build passed. The targeted extraction-only re-test harness passed in fake
mode (5 calls, $0, 3.91 s). Integration regressions cover invented evidence quotes, unrelated
or unaddressed topic links, missing-gap prose, partial-input notices/word limits, generic
similarities, shared-heading fragments, relevance flags, partial absence wording and cache
version isolation. Old results/prompts are preserved and historical keys are not reused.

The expanded walkthrough passed on a separate fake stack. Browser inspection showed the
selected-parts gap note and full server notice (43/101 sections) on a generated Markdown
fixture, plus the shared-passage UI. Screenshot: `.checks/summary-v4-fake-ui.png` (clearly fake).
The final shared-sentence syntax refinement was subsequently covered by the full suite and
five-call fake re-test. No test double output is evidence of real-model quality.

Main API/worker/web rebuilt; readiness ready, real mode, worker OK; running API imports report
summary.custom.v4 / compare.v2. Main ledger remained 43 calls / $0.00674021. New paid spend: $0.
The prior real evaluation evidence is unchanged. Temporary fake containers, volumes and
image tags were removed; main demo data was preserved.

**NOT VERIFIED:** acceptance/quality of the new internal schemas with the real model, actual
focus adherence or paraphrase entailment. Quote matches prove occurrence, not support for a
paraphrase. Focus verdicts/relevance flags still come from the model. A conservative literal
shared-sentence check can omit real similarities expressed differently; sentence punctuation
is not a factuality proof. Map/reduce insight prompts were not changed.

A five-call real re-test is prepared in [ANALYSIS_RETEST_PLAN.md](ANALYSIS_RETEST_PLAN.md),
estimated about $0.003 with proposed allowance $0.008. It needs fresh explicit approval.
# Targeted summary v4 / comparison v2 re-test (2026-10-15, approved)

**Actual execution:** the developer approved five calls with an estimated $0.003 and $0.008
allowance. `TEST_AI_PROVIDER=openai RUN_LIVE_AI_TESTS=1 docker compose -f compose.test.yml
run --rm -e RUN_ANALYSIS_RETEST=1 tests pytest -m live tests/live/test_analysis_retest.py -q -s`
completed **1 passed in 15.93 s; 5 real calls, $0.00156255 estimated**. All rows succeeded,
all were gpt-4o-mini: three summary_custom and two compare. Extraction-only setup made no
embedding/insights calls. This confirms schema acceptance/transport, not all quality checks.

[Raw responses and ledger](evaluations/analysis-2026-10-15-v4-v2.json) are preserved unchanged;
`human_review: NOT REVIEWED` remains the developer-owned status. Codex's review follows.

| Case | Observed outcome | Review |
|---|---|---|
| Medium/executive budget and risks | Correct 41.5m budget and 3.2m contingency, p3 and matching evidence quotes; no unrelated schedule/generation claims. But one verdict `budget and risks: true`, empty missing-topic list and no gap sentence | **Failed independent-topic/gap expectation.** The model merged two requested topics into one. Server rendering cannot recover a missing verdict from this output |
| Short/plain leave | 27 days, up to 5 carried over, section 2, matching quotes | Correct in this run |
| Long/technical partial Heron | ZX-48213, p160; explicit selected-parts notice, 31/160 coverage, no invented whole-document absence claim | Correct in this run |
| Capital-budget version comparison | Exactly one changed amount, 41.5m to 44.0m, p3. Two legitimate budget-related shared sentences (approval date and contingency). No off-focus retained content | Correct in this run |
| Brief vs handbook | No retained shared passages; correct leave/construction positions and absent counterparts, section 2 / p4 | Correct retained result. Validator reported one dropped point; pre-validation model content was not saved, so its exact identity is unknown |

The five output lengths/tones/locations were inspected; no additional content was invented
in the retained results reviewed here. The missing risks classification remains a meaningful
failure: a passing API test must not conceal it. One generation per request is not evidence
about repeat stability or general grounding quality. Literal evidence still does not prove
paraphrase entailment. No extra paid iteration was made.

| Purpose / case | Input tokens | Output tokens | Estimated USD |
|---|---:|---:|---:|
| summary_custom / budget and risks | 1115 | 138 | 0.00025005 |
| summary_custom / plain leave | 936 | 121 | 0.00021300 |
| summary_custom / partial archive | 2756 | 76 | 0.00045900 |
| compare / budget versions | 1574 | 175 | 0.00034110 |
| compare / different documents | 1388 | 152 | 0.00029940 |
| **Total** | | | **0.00156255** |

Main demo ledger stayed 43 calls / $0.00674021. Retained evidence across demo + broader run +
this re-test totals 90 real calls / $0.01621937 estimated. These are observed snapshots;
historical-accounting discrepancies described above were not rewritten. Next correction:
make requested-topic identities server-owned and require one independent verdict per identity.
## V5 follow-up to the merged-topic failure (unpaid, 2026-10-15)

Under the existing summary-correction scope, Codex added summary.custom.v5 after recording the
v4 failure. Requested topic identities now come from the server: explicit commas, semicolons
and standalone and/or delimit a literal list, with case-insensitive deduplication. Each topic
gets one required boolean field in a strict dynamic schema. Merged, missing or extra verdict
keys are rejected; no-focus has its own required flag and public focus coverage remains None.
The model still judges each boolean and may judge incorrectly. This is not semantic topic
parsing (research and development splits; research & development does not).

**Unpaid checks:** ruff passed; 152 tests passed / 3 live tests deselected in 52.05 s. A regression
checks required schema fields and rejects merged/omitted/invented keys. The two-call fake
rehearsal passed in 14.96 s, zero cost: separate budget=true and risks=false, missing-risks
notice, and no-focus control. This proves transport/schema behavior only, not real v5 quality.
Main API/worker rebuilt; readiness ready / real mode / worker OK. No frontend changes were
needed. Existing prompts/results remain, with a new cache key for v5.

**NOT VERIFIED:** v5 OpenAI schema acceptance, independent verdict quality and point selection
on the real model. A fresh two-call check (budget and risks plus no-focus control) is prepared
in ANALYSIS_RETEST_PLAN.md, estimated $0.001, allowance $0.003. No additional paid call was
made. Comparison v2 was not changed after its two correct targeted retained results.
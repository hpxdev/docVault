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

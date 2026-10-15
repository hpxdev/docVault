# Live evaluation (real OpenAI models)

**Status: run once, 2026-10-15 05:41 UTC, with the user's approval.** Everything below is the
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
1's prompt locally gives 632 o200k tokens (what the fallback would have stored), while the ledger
has 655. The +23 difference is consistent with provider-counted chat framing, so these are very
likely provider-reported. Embedding tokens are always counted locally with `cl100k_base`
(LangChain's `OpenAIEmbeddings` returns no usage).

## Not verified by this run

- Retrieval quality on larger or multi-document corpora; vault-wide (HNSW) search.
- Condensed follow-ups and multi-turn behaviour with the real model.
- Map-reduce insights with the real model (the document was far below the 60K-token threshold).
- DOCX/MD/TXT documents with the real model.
- Behaviour under OpenAI errors (rate limits, timeouts) against the real API; covered only by
  fake-mode tests.
- Answer quality in general: 10 easy questions on one clean document is not a quality claim.

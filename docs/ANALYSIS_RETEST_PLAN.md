# Summary v4 / comparison v2 and v5 re-tests: completed

Prepared by OpenAI Codex on 2026-10-15 after the approved broader run exposed prose/focus
failures. The developer approved the five-call re-test, which completed in 15.93 s at
$0.00156255 estimated cost. Four retained results met their checks, but v4 merged budget and
risks and missed the risks gap. See EVALUATION.md and evaluations/analysis-2026-10-15-v4-v2.json.
The original five-call plan below records that completed run; the new proposal follows here.

## V5 check: two calls, approved and completed

The developer explicitly approved the two-call proposal. Actual output: **1 passed in
8.72 s; 2 succeeded calls, $0.00050400 estimated**. Budget/risks had separate correct verdicts,
the missing-risks notice and p3 facts. The no-focus handbook control had correct section
citations and focus_covered=None. Raw evidence: [summary-v5-2026-10-15.json](evaluations/summary-v5-2026-10-15.json).
No further paid call followed. The proposal/command below record exactly what was approved;
future paid reruns still require their own authorization.

V5 defines requested-topic IDs on the server and requires one independent boolean field per
ID. Merged/missing/extra keys cannot validate. The server's list grammar splits commas,
semicolons and standalone `and`/`or`; it does not infer semantic topic boundaries. Existing
evidence checks/rendering remain. The two calls above followed the separately approved five.

Proposed **two summary_custom calls**: (1) medium/executive budget and risks, requiring
separate budget=true / risks=false and the gap notice; (2) a short/plain no-focus handbook
control, checking the no-focus schema branch. Estimated **$0.001**, allowance **$0.003**.
The isolated guard is $0.002 and checks before calls, so a final call may exceed its threshold.
No comparison rerun, embedding or insight generation is needed. No automatic paid iteration.

```bash
TEST_AI_PROVIDER=openai RUN_LIVE_AI_TESTS=1 \
docker compose -f compose.test.yml run --rm -e RUN_ANALYSIS_RETEST=1 -e SUMMARY_V5_ONLY=1 tests \
  pytest -m live tests/live/test_analysis_retest.py -q -s
```

Fake rehearsal substitutes `-e ANALYSIS_RETEST_FAKE_DRY_RUN=1 -e SUMMARY_V5_ONLY=1`, without
the live switches. Results go to `summary_v5_retest_real.json` (or `_fake.json`) under
backend/tests/live/.results, preserving the earlier five-call result file.

## Concrete changes ready for review

- Summary v4 returns topic verdicts and cited points with exact supporting quotes; no
  independent model-authored summary paragraph. The server rejects unmatched quotes and
  points not linked to an addressed focus topic, renders retained points, and adds gap and
  partial-coverage notices. Notices refer only to selected parts when input is incomplete.
- Comparison v2 retains shared factual sentences only when the same text occurs in cited
  parts of at least two distinct documents. It rejects heading/keyword fragments and
  model-flagged off-focus items. Its overview is built from retained-item counts.
- Existing API response fields and database schema remain compatible. Old prompt files,
  output schemas and stored results remain; versioned keys prevent old cache reuse.
- UI wording distinguishes selected-part gaps and calls v2 similarities "Shared passages",
  explaining that valid differently worded facts may be omitted.

These checks are conservative. Quote occurrence does not establish semantic entailment of a
paraphrase, and topic/relevance judgements remain model-dependent. The targeted real results
are documented above; general quality and repeat stability remain unverified.
The insight map/reduce prompts are outside this correction and retain their documented limits.

## Proposed paid run

**Five logical calls:** three `summary_custom` and two `compare`. Estimated incremental cost
about **$0.003**, proposed allowance **$0.008** for output/retry variation. The isolated ledger
guard is temporarily $0.006 and checks before each call, so a final in-flight call can exceed
that threshold. Prices are the application's dated estimates, not invoice amounts.

Fixtures run extraction only: embeddings and insights are not needed for these endpoints.
Queued index/insights dispatch is intercepted by the test harness and is not drained.
The fake rehearsal asserts exactly five ledger rows, all for summary/compare.

1. Medium/executive, budget and risks: inspect correct numbers, actual budget focus, server
   gap sentence and structured risks verdict. Check evidence quotes and source locations.
2. Short/plain handbook annual leave: check 27 days/up to 5 carried over and section locators.
3. Long/technical Heron archive-code summary, 2,000-token input budget: inspect the page-160
   code, partial coverage, no unrequested absence claims and no statement about omitted parts.
4. Capital-budget comparison of v1/v2: inspect the single changed figure, page 3, and absence
   of unrelated similarities. An identical contingency sentence is a legitimate shared fact.
5. Brief vs handbook: inspect leave/construction positions and missing counterparts; generic
   shared-purpose/structure claims should not survive as shared passages.

Inspect every retained point; a passing transport test is not a quality score. Store the raw
responses/ledgers and report misses. No automatic paid prompt iteration follows this run.

## Commands after explicit approval

Run only against the separate test database, which fixtures reset/truncate. Keep the key in
the existing ignored `.env`; never print or copy it into a command.

```bash
TEST_AI_PROVIDER=openai RUN_LIVE_AI_TESTS=1 \
docker compose -f compose.test.yml run --rm -e RUN_ANALYSIS_RETEST=1 tests \
  pytest -m live tests/live/test_analysis_retest.py -q -s
```

The result is saved to `backend/tests/live/.results/analysis_retest_real.json`, including
partial results on failure. Its developer-owned `human_review` field remains NOT REVIEWED.

Fake-only rehearsal (zero spend, verifies harness/plumbing only):

```bash
docker compose -f compose.test.yml run --rm -e ANALYSIS_RETEST_FAKE_DRY_RUN=1 tests \
  pytest -m live tests/live/test_analysis_retest.py -q -s
```

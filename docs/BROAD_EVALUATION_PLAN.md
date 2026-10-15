# Broader evaluation: prepared, awaiting spend approval

Prepared by OpenAI Codex on 2026-10-15. **No real run yet.**
Harness: `backend/tests/live/test_broad_evaluation.py`.

The fake rehearsal completed with 42 ledger calls and zero cost. This verifies the harness
and API contracts only. The real run is expected to make about 42 calls (query caching and
provider retries can change that). Estimated incremental spend is about $0.01, using the
application's dated price table and expected output lengths; allow up to $0.015 for variance.
This is an estimate, not an invoice or guaranteed upper bound. Stop and reassess if the
recorded cost approaches the approved allowance. The harness temporarily lowers its isolated
ledger cap to $0.01; the existing guard checks before each call, so the final in-flight call
can exceed that threshold. No new dependencies are required.

## Cases and evidence

- Two independent multi-document answers: annual leave from the handbook, construction date
  from the brief. Record both answers and both document citations to inspect variance.
- Budget answer followed by approval-date follow-up through the complete active-v3 pipeline.
- A 160-page generated Heron PDF: archive code on page 160. Force the map-reduce branch at
  4,000 tokens, keeping the production map grouping size of 8,000 tokens. The fake rehearsal
  must show multiple map groups. This checks the branch cheaply; it does not validate the
  default 60,000-token threshold or model behaviour on a genuinely large token volume.
- Injection PDF scoped separately from the Heron PDF: request the hidden archive code.
  Check no cross-scope code leaks and all citations stay in the selected document. Also
  inspect the response for instruction-following; one case cannot prove general resistance.
- Focused comparison of two versions with one known budget change, and a comparison of the
  brief and handbook with different subject matter. Inspect all facts and cited locations.
- Short/plain handbook summary; medium/executive budget-and-risks summary; long/technical
  Heron summary with a 1,800-token input budget to exercise honest partial coverage.
- v2/v3 rewrite A/B: approval date, unnamed "its installed capacity", standalone CFO question.
  Two actual generations per question and version (12 calls), using identical conversation
  histories. Check that v3 preserves ambiguous and standalone questions while resolving the
  approval question correctly. These calls are linked to the evaluation budget message for
  ledger ownership; they are isolated prompt experiments, not additional chat turns.

The harness saves complete responses, rewrite outputs and per-call token/cost ledgers to
`backend/tests/live/.results/broad_eval_real.json`, including partial results after failures.
Heuristic pass fields cover selected checks only. Human inspection of grounding, omissions,
invention, scope, citations and rewrite quality remains necessary before reporting results.

## Execution after explicit approval

Run only against the isolated **test** database, never the demo database: the test fixtures
reset and truncate their database. Use `AI_PROVIDER=openai` via `TEST_AI_PROVIDER=openai`,
`RUN_LIVE_AI_TESTS=1`, and `RUN_BROAD_AI_EVAL=1`; the latter is passed to the container with
`-e`. The existing ignored `.env` supplies the key without printing it.

```bash
TEST_AI_PROVIDER=openai RUN_LIVE_AI_TESTS=1 \
docker compose -f compose.test.yml run --rm -e RUN_BROAD_AI_EVAL=1 tests \
  pytest -m live tests/live/test_broad_evaluation.py -q -s
```

The default suite deselects this test. A fake-only rehearsal is available without a key:

```bash
docker compose -f compose.test.yml run --rm -e BROAD_EVAL_FAKE_DRY_RUN=1 tests \
  pytest -m live tests/live/test_broad_evaluation.py -q -s
```

Review the real results, update EVALUATION.md and the development log with actual outcomes,
and sum costs from isolated ledgers separately from the preserved demo ledger.

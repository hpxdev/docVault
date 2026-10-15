# Clean-clone verification, 2026-10-15

OpenAI Codex verified committed snapshot `2222d9e` after the bonus features and v3 changes.
The subsequent commit adds verification records and documentation corrections only.

## Isolation

- Local `git clone --no-hardlinks . .checks/clean-clone-20261015`; clean tracked files.
- `.env` created from the committed `.env.example`, with `AI_PROVIDER=fake`; no key copied.
- Compose override explicitly set fake mode and an empty key on API and worker.
- Project `ai-vault-cleancheck`, fresh volumes, images `ai-vault-backend:cleancheck` and
  `ai-vault-web:cleancheck`, ports 18000 and 15173 (`ports: !override`).
- Test project `ai-vault-cleancheck-test`, separate Postgres/Redis and test image
  `ai-vault-backend:cleancheck-test`; fake provider and empty key forced by override.
- Docker reused cached dependency layers. This was a fresh source checkout/database check,
  not a test of installing every dependency without a Docker cache.

## Commands and observed outcomes

From the clone, with the temporary overrides stored in its parent directory:

```bash
docker compose -p ai-vault-cleancheck -f compose.yml -f ../cleancheck.override.yml \
  up -d --build --wait --wait-timeout 180

docker compose -p ai-vault-cleancheck-test -f compose.test.yml \
  -f ../cleancheck-test.override.yml run --build --rm tests \
  sh -c 'ruff check . && ruff format --check . && pytest -q'

API=http://localhost:18000/api/v1 CHECK_RATE_LIMIT=1 bash scripts/walkthrough.sh

docker compose -p ai-vault-cleancheck-test -f compose.test.yml \
  -f ../cleancheck-test.override.yml run --rm -e BROAD_EVAL_FAKE_DRY_RUN=1 tests \
  pytest -m live tests/live/test_broad_evaluation.py -q -s
```

- Compose build/start succeeded; frontend ran `tsc -b && vite build` successfully.
- Migration revision `0003`; all five services running/healthy as reported by Compose wait.
- Ruff passed, 104 tracked Python files formatted; **145 passed, 2 deselected in 71.05 s**.
- Expanded walkthrough exited 0, including summary cached reuse, new-version processing,
  comparison POST/GET/list and **429 RATE_LIMITED; Retry-After: 33**.
- Database checks: both versions ready, only v2 latest, one summary and one comparison.
  Ledger: **14 fake calls, $0.00000000**, no other model names.
- Web returned HTTP 200; its API proxy reported fake mode and `key_present: false`.
- Broader harness: **1 passed in 6.43 s**, **42 zero-cost fake ledger calls**. The 160-page
  fixture used two map groups and reported coverage 160/160. This is harness evidence only.

The expanded script was also invoked against real-mode readiness without its opt-in. It
exited 1 with its refusal before uploading anything. The main demo ledger remained at
43 calls and $0.00674021 before/after. This current snapshot differs from the handover's
historical cumulative $0.00703274; the historical runs were not reconstructed or altered.

The main API and worker were rebuilt afterward. Readiness reported `ready`, real mode,
worker OK; an import inside the API container reported `chat.condense.v3`. No paid call was
made, so v3 real-model behaviour remains **NOT VERIFIED**.

Temporary Compose projects were removed with their own `down -v`; the three dedicated
image tags were removed. Clone/config/log artifacts remain under ignored `.checks/` for
inspection. The original demo volumes, documents, cached summaries and comparison remain.

## Limits

No paid evaluation, load test, default-60,000-token map-reduce evaluation, or slow real-stream
Stop test was run. The broader paid run is prepared in [BROAD_EVALUATION_PLAN.md](BROAD_EVALUATION_PLAN.md)
and awaits explicit approval.

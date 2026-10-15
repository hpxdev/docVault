# Final submission verification

Date: 15 October 2026. Checked by OpenAI Codex.

## Snapshot and isolation

The application snapshot checked was `91369b06bc33d66f5d5be270073e83e55e2962b9`.
A separate local clone was created with `git clone --no-hardlinks . .checks/submission-20261015`.
It had no tracked changes. Later submission commits update documentation only; the backend
and frontend trees are unchanged from the checked snapshot.

- Backend tree: `5212f7636461f866e5d7ca562a9c3fecc479a862`.
- Frontend tree: `454a528fe6ffe1b1a0bc1132963a62cf2555321f`.
- Configuration was copied from `.env.example`, with fake mode selected. Overrides explicitly
  set `AI_PROVIDER=fake`, an empty `OPENAI_API_KEY` and `RUN_LIVE_AI_TESTS=0`.
- Runtime project: `docvault-submission`, API port 18001, web port 15174, separate database
  and storage volumes. Image tags used the `submission` suffix.
- Test project: `docvault-submission-test`, separate PostgreSQL and Redis containers, test
  image `ai-vault-backend:submission-test`.
- The successful runtime retry used one worker process to reduce local resource use. The
  application's normal worker default remains two.
- Existing app and demo stacks were not stopped or modified by these checks.
- No new paid model calls were made. This verifies application behavior with fake providers,
  not the quality of new real-model answers.

## Results

| Check | Observed result |
|---|---|
| Clean frontend install | `npm ci --no-audit --no-fund`: 200 packages installed. Some downloads needed automatic integrity retries; the install finished successfully without lockfile changes. |
| Frontend build | `npm run build`: TypeScript and Vite production build passed, 232 modules transformed. |
| Docker application build | Backend and frontend images built from the clean checkout. Cached dependency layers were reused. This was not a fully uncached installation test. |
| Backend lint | `ruff check .`: all checks passed. |
| Backend formatting | `ruff format --check .`: 109 files already formatted. |
| Full backend suite, successful rerun | `pytest -q`: **152 passed, 3 live tests deselected**, in 98.44 seconds. |
| Runtime startup, successful retry | Compose completed its wait successfully; database migrations ran and readiness reported `ready`, including the worker heartbeat. |
| Scripted API walkthrough | Exit code 0, including `429 RATE_LIMITED` and a `Retry-After` header. |
| Browser inspection | Dark default and fake-mode banner visible, no horizontal overflow at the inspected desktop width, Library loaded the ready version-2 document. No captured browser warning/error logs at inspection. |
| Documentation | Local file links in the main reviewer-facing documents resolve. README and AI_USAGE.md contain no em dashes. |
| Publication hygiene | No `.env` in tracked history; common credential-pattern scan of 749 Git objects, including 400 blobs, found no matches. This is a limited pattern scan, not a comprehensive security audit. |

The API walkthrough covered accepted, duplicate and rejected uploads; live processing events;
insights; a cited answer; streamed follow-up; a not-found response; saved history; custom-summary
reuse; a new document version; stored comparison reuse; metrics; and rate limiting. Fake
answers are deliberately labelled and are not assessed here for real-model accuracy.

## Commands used

From the clean checkout, the temporary override files lived one level above it. They changed
image tags and ports and forced fake mode, leaving the source configuration unchanged.

```bash
docker compose -p docvault-submission-test -f compose.test.yml \
  -f ../submission-test.override.yml run --build --rm tests \
  sh -c 'ruff check . && ruff format --check . && pytest -q'

cd frontend
npm ci --no-audit --no-fund
npm run build
cd ..

docker compose -p docvault-submission -f compose.yml \
  -f ../submission.override.yml up -d --build --wait --wait-timeout 180

# After the initial infrastructure failure, tests and runtime ran sequentially.
docker compose -p docvault-submission-test -f compose.test.yml \
  -f ../submission-test.override.yml run --rm tests \
  sh -c 'ruff check . && ruff format --check . && pytest -q'

docker compose -p docvault-submission-test -f compose.test.yml \
  -f ../submission-test.override.yml stop -t 5

docker compose -p docvault-submission -f compose.yml \
  -f ../submission.override.yml up -d --wait --wait-timeout 300

API=http://localhost:18001/api/v1 CHECK_RATE_LIMIT=1 bash scripts/walkthrough.sh
```

## Initial failure and retry

The first run overlapped the runtime startup and tests on a busy Docker host. Runtime health
checks exceeded their five-second timeout and startup failed. One stop attempt also failed to
receive a container exit event; a subsequent stop succeeded.

The first suite result was **151 passed, 3 deselected, 1 setup error** in 339.84 seconds.
The error was a closed PostgreSQL connection during
`test_budget_exceeded_is_429_and_kept_in_history`. Database logs show a server process exiting,
followed by recovery. The exact cause of that PostgreSQL process exit was not established.

The extra runtime stack was stopped, the database recovered, and the complete suite was rerun.
It passed without source changes. The test services were then stopped before starting the
runtime again with one worker process. That startup and the full walkthrough passed. These
results are functional checks, not performance measurements under controlled load.

## Delivery status and remaining limits

The source and documentation are prepared for GitHub. The developer is responsible for the
final video review and YouTube upload; no video URL or human video approval has been invented.
The README will receive that link when it is supplied.

No new real-model evaluation, load test, general injection-resistance assessment, production
hosting or automated UI regression suite was added. Earlier real-model evidence and its
limitations remain in [EVALUATION.md](EVALUATION.md). The narrated recording and replay labels
are described in [VIDEO_DELIVERY.md](VIDEO_DELIVERY.md).

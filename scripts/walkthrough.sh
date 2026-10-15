#!/usr/bin/env bash
# README curl walkthrough, scripted. Runs against a stack started with `docker compose up`.
#   bash scripts/walkthrough.sh            (API defaults to http://localhost:8000/api/v1)
# Needs curl and Python (only to pull IDs out of JSON). Prints every response it gets.
set -euo pipefail

API="${API:-http://localhost:8000/api/v1}"
PY="${PYTHON:-$(command -v python3 || command -v python)}"
cd "$(dirname "$0")/.."

json() { "$PY" -c 'import json,sys; d=json.load(sys.stdin)
for k in sys.argv[1].split("."):
    d = d[int(k)] if k.isdigit() else d[k]
print(d)' "$1"; }
pretty() { "$PY" -c 'import json,sys; print(json.dumps(json.load(sys.stdin), indent=2, ensure_ascii=False))'; }
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

step "0. Readiness (real AI requires explicit opt-in)"
READY=$(curl -fsS "$API/health/ready")
echo "$READY" | pretty
MODE=$(echo "$READY" | json checks.ai.ai_mode)
if [[ "$MODE" != fake && "${ALLOW_REAL_AI:-0}" != 1 ]]; then
  echo 'Refusing to spend money. Use a fake stack, or obtain approval then set ALLOW_REAL_AI=1.' >&2
  exit 1
fi
if [[ "${CHECK_RATE_LIMIT:-0}" == 1 && "$MODE" != fake ]]; then
  echo 'CHECK_RATE_LIMIT is allowed only in fake mode.' >&2
  exit 1
fi

step "1. Upload 3 files: a PDF, the same PDF again (duplicate), and a renamed binary (invalid)"
UPLOAD=$(curl -fsS -X POST "$API/documents" \
  -F "files=@samples/northwind-brief.pdf" \
  -F "files=@samples/northwind-brief.pdf;filename=northwind-brief-copy.pdf" \
  -F "files=@samples/not-a-document.exe;filename=report.pdf")
echo "$UPLOAD" | pretty
DOC=$(echo "$UPLOAD" | json results.0.document.id)

step "2. Watch status live (SSE) until the document settles"
curl -fsS -N "$API/documents/events?ids=$DOC&close_when_settled=true"
curl -fsS "$API/documents/$DOC" | pretty

step "3. Read insights"
curl -fsS "$API/documents/$DOC/insights" | pretty

step "4. Ask a cited question"
SESSION=$(curl -fsS -X POST "$API/chat/sessions" -H 'Content-Type: application/json' \
  -d "{\"document_ids\": [\"$DOC\"]}" | json id)
curl -fsS -X POST "$API/chat/sessions/$SESSION/messages" -H 'Content-Type: application/json' \
  -d '{"content": "What is the total capital budget?"}' | pretty

step "5. Ask a follow-up (condensed using the conversation), streamed over SSE"
curl -fsS -N -X POST "$API/chat/sessions/$SESSION/messages/stream" \
  -H 'Content-Type: application/json' -d '{"content": "When was it approved?"}'

step "6. Ask something the document does not contain"
curl -fsS -X POST "$API/chat/sessions/$SESSION/messages" -H 'Content-Type: application/json' \
  -d '{"content": "Who is the CFO?"}' | pretty

step "7. History"
curl -fsS "$API/chat/sessions/$SESSION/messages?limit=10" | "$PY" -c 'import json,sys
for m in json.load(sys.stdin)["items"]:
    pages = [c["location"] for c in m["citations"]]
    print("%-9s %-11s %s %r" % (m["role"], m["answer_status"], pages, m["content"][:90]))'

step "8. Custom summary and cached reuse"
OPTIONS='{"length":"short","tone":"executive","focus":"budget and risks"}'
SUMMARY=$(curl -fsS -X POST "$API/documents/$DOC/summaries" \
  -H 'Content-Type: application/json' -d "$OPTIONS")
echo "$SUMMARY" | pretty
CACHED=$(curl -fsS -X POST "$API/documents/$DOC/summaries" \
  -H 'Content-Type: application/json' -d "$OPTIONS")
echo "$CACHED" | pretty
[[ "$(echo "$CACHED" | json cached)" == True ]]
[[ "$(echo "$CACHED" | json id)" == "$(echo "$SUMMARY" | json id)" ]]
curl -fsS "$API/documents/$DOC/summaries" | pretty

step "9. Upload version 2 and wait for processing"
NEW=$(curl -fsS -X POST "$API/documents/$DOC/versions" \
  -F 'file=@samples/northwind-brief-v2.pdf' | json id)
curl -fsS -N "$API/documents/events?ids=$NEW&close_when_settled=true"
curl -fsS "$API/documents/$NEW" | pretty
curl -fsS "$API/documents/$DOC/versions" | pretty

step "10. Compare the versions and read the stored comparison"
COMPARISON=$(curl -fsS -X POST "$API/comparisons" -H 'Content-Type: application/json' \
  -d "{\"document_ids\":[\"$DOC\",\"$NEW\"]}")
echo "$COMPARISON" | pretty
COMPARISON_ID=$(echo "$COMPARISON" | json id)
curl -fsS "$API/comparisons/$COMPARISON_ID" | pretty
curl -fsS "$API/comparisons?document_id=$DOC" | pretty

step "11. Metrics"
curl -fsS "$API/metrics/documents" | pretty
curl -fsS "$API/metrics/processing?window=24h" | pretty

if [[ "${CHECK_RATE_LIMIT:-0}" == 1 ]]; then
  step "12. Rate limit: invalid requests trigger 429 without creating AI output (fake only)"
  "$PY" - "$API" "$SESSION" <<'PY'
import json
import sys
import urllib.error
import urllib.request

url = f"{sys.argv[1]}/chat/sessions/{sys.argv[2]}/messages"
for attempt in range(100):
    request = urllib.request.Request(
        url, data=b'{"content":""}', headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as exc:
        body = json.load(exc)
        if exc.code == 429:
            assert body["error"]["code"] == "RATE_LIMITED", body
            assert int(exc.headers["Retry-After"]) > 0
            print("429 RATE_LIMITED; Retry-After:", exc.headers["Retry-After"])
            break
        assert exc.code == 422, (exc.code, body)
    else:
        raise AssertionError("Empty message unexpectedly accepted")
else:
    raise AssertionError("No 429: enable rate limiting on the fake stack")
PY
fi

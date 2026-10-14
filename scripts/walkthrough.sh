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

step "0. Readiness"
curl -s "$API/health/ready" | pretty

step "1. Upload 3 files: a PDF, the same PDF again (duplicate), and a renamed binary (invalid)"
UPLOAD=$(curl -s -X POST "$API/documents" \
  -F "files=@samples/northwind-brief.pdf" \
  -F "files=@samples/northwind-brief.pdf;filename=northwind-brief-copy.pdf" \
  -F "files=@samples/not-a-document.exe;filename=report.pdf")
echo "$UPLOAD" | pretty
DOC=$(echo "$UPLOAD" | json results.0.document.id)

step "2. Watch status live (SSE) until the document settles"
curl -s -N "$API/documents/events?ids=$DOC&close_when_settled=true"
curl -s "$API/documents/$DOC" | pretty

step "3. Read insights"
curl -s "$API/documents/$DOC/insights" | pretty

step "4. Ask a cited question"
SESSION=$(curl -s -X POST "$API/chat/sessions" -H 'Content-Type: application/json' \
  -d "{\"document_ids\": [\"$DOC\"]}" | json id)
curl -s -X POST "$API/chat/sessions/$SESSION/messages" -H 'Content-Type: application/json' \
  -d '{"content": "What is the total capital budget?"}' | pretty

step "5. Ask a follow-up (condensed using the conversation), streamed over SSE"
curl -s -N -X POST "$API/chat/sessions/$SESSION/messages/stream" \
  -H 'Content-Type: application/json' -d '{"content": "When was it approved?"}'

step "6. Ask something the document does not contain"
curl -s -X POST "$API/chat/sessions/$SESSION/messages" -H 'Content-Type: application/json' \
  -d '{"content": "Who is the CFO?"}' | pretty

step "7. History"
curl -s "$API/chat/sessions/$SESSION/messages?limit=10" | "$PY" -c 'import json,sys
for m in json.load(sys.stdin)["items"]:
    pages = [c["location"] for c in m["citations"]]
    print("%-9s %-11s %s %r" % (m["role"], m["answer_status"], pages, m["content"][:90]))'

step "8. Metrics"
curl -s "$API/metrics/documents" | pretty
curl -s "$API/metrics/processing?window=24h" | pretty

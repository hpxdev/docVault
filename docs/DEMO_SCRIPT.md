# Demo script (5–7 minutes)

For recording the demo video. It uses only the self-written sample files in
[`samples/`](../samples/), whose facts are known:

| File | Known facts used below |
|---|---|
| `northwind-brief.pdf` (6 pages) | p2: 48 MW capacity · p3: budget 41.5 million euros, approved 4 March 2026, contingency 3.2 million · p4: construction starts June 2026, contractor Brightline Builders |
| `employee-handbook.docx` | "Leave Policy": 27 days paid annual leave, up to 5 carried over · "Remote Work": up to three days per week |
| `onboarding-guide.md` | "Accounts": VPN client Tunnelbear-X · "Staging": deploys every Tuesday at 14:00 UTC |
| `not-a-document.exe` | Not a document (shows the rejection path) |

**Real-mode dry run (2026-10-15, approved): steps 2–7 were run through the UI with
`gpt-4o-mini`, about $0.0022 estimated; actual results are in
[EVALUATION.md](EVALUATION.md#demo-dry-run-in-real-mode-2026-10-15-approved).** Every step
behaved as written, except the follow-up rewrite (step 5, note in the table). Expect about
4 s to chat-ready and 10–15 s to insights per sample file, and about 2–4 s per answer.

**Earlier fake-mode rehearsal:** steps 2 and 4–7 were rehearsed in the UI on a fresh clean-clone stack in
**fake mode** (2026-10-15, see ai-log T25); step 3 was checked through the API on that stack
(DOCX key points reference sections, coverage 3/3), and the Metrics page and test run (steps 8–9)
were checked during T20–T23 and T25. In the rehearsal: chips went Queued → Processing → Ready, the binary was
rejected, the re-dropped PDF showed "already in vault", the budget answer cited page 3, the
follow-up was rewritten, "Who is the CFO?" was not found, and for the multi-document question
retrieval ranked the handbook's "Leave Policy" section and the brief's page 4 as S1 and S2.
The fake model quotes a single best sentence, so it cited only S1; the real-mode dry run then
showed two citations from the two documents. Cost of a real run-through: about $0.0022
estimated for three documents and six questions (dry-run ledger).

## Before recording

1. In `.env`: `AI_PROVIDER=openai` and your key (on its own line). Start fresh:
   `docker compose down -v` then `docker compose up --build -d`.
2. Wait until http://localhost:8000/api/v1/health/ready says `"status": "ready"`. The FAKE AI
   MODE banner must **not** be visible in the UI.
3. Open http://localhost:5173 in one browser tab, http://localhost:8000/docs in a second, and a
   file explorer window on the `samples/` folder.
4. Optional terminal for the last segment:
   `docker compose -f compose.test.yml run --rm tests` (takes about 30 s; run it once beforehand
   so the image is built).

## Script

| Time | Segment | Do | Say / point out |
|---|---|---|---|
| 0:00–0:40 | 1. Problem and architecture | Show the diagram in README §5 or docs/ARCHITECTURE.md | "ChatGPT for your documents": FastAPI, Celery worker in a Linux container, Postgres + pgvector as the single source of truth, Redis for the queue, cache and live events, OpenAI for embeddings and answers. Answers must cite pages, and the server checks the citations |
| 0:40–1:40 | 2. Multi-file drag-and-drop with live status | New chat → drag `northwind-brief.pdf`, `employee-handbook.docx` and `not-a-document.exe` together onto the chat | Three chips appear: the binary is rejected at once ("Unsupported file type": the type is detected from the bytes); the others move from Processing to Ready live over SSE; Send stays disabled with a hint until they are ready. Then drag `northwind-brief.pdf` again → "already in vault" (SHA-256 dedupe, no reprocessing or AI cost) |
| 1:40–2:30 | 3. Insights | Library → click `northwind-brief.pdf` | Summaries, key points each tagged with its page, category, tags, tone, suggested questions; coverage line (all 6 pages). DOCX key points show sections (§), never invented pages |
| 2:30–3:30 | 4. Streamed cited answer | Back to the chat → ask *What is the total capital budget?* → click the citation chip | Tokens stream in; the chip opens the source panel: document, page 3, the original text (not model text). Live-run answer: "The total capital budget is 41.5 million euros [S1]." |
| 3:30–4:00 | 5. Follow-up | Ask *When was it approved?* | The answer uses the conversation: "The budget was approved on 4 March 2026", page 3 (real dry run). Be accurate if you point at "searched: …": in the dry run the condense step returned the question unchanged (a known weakness, see EVALUATION.md), so say the conversation is used and don't claim a visible rewrite |
| 4:00–4:30 | 6. Not found | Ask *Who is the CFO?* | Amber "Not found in the selected documents" box and no citations: the model must say so instead of guessing |
| 4:30–5:15 | 7. Multi-document answer | Ask *How many days of annual leave do employees get, and when does construction of the solar farm start?* | Two citations from two documents: the handbook's "Leave Policy" section (27 days) and the brief's page 4 (June 2026). Optional: tick "Search entire vault" and ask *What is the VPN client called?* after uploading `onboarding-guide.md` |
| 5:15–6:00 | 8. Swagger and metrics | Swagger tab: show the endpoint groups and an example; then the UI's Metrics page | Every endpoint has examples and one error format. Metrics: AI calls and **estimated** cost by purpose and model against the $0.50 cap; not-found rate with numerator/denominator; first-token latency; stage success rates and durations |
| 6:00–6:45 | 9. Tests, AI usage, limitations | Show the test run summary (124 passed); open AI_USAGE.md and docs/EVALUATION.md | Fake-mode tests prove the plumbing (real Postgres/Redis); one live evaluation, 10/10 on a small set. Built with Claude Code, every step logged, bugs it caused and how they were caught. Limitations: no OCR, single user, no auth, English full-text search, gpt-4o-mini shutdown 2027-01-14 |

## If something goes wrong on camera

- A document stays "Processing": check `docker compose logs worker`. Reprocess from the Library.
- `AI_BUDGET_EXCEEDED`: the app cap ($0.50) was reached; check the Metrics page.
- The answer differs from the "expected" text above: that is the real model; the citation chip
  still shows exactly which page it used.

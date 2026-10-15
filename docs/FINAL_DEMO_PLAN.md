# Six-minute narrated case-study demo plan

Status: planning only, 15 October 2026. Supersedes the proposed 12–15 minute main video in
VIDEO_WALKTHROUGH.md. The earlier 47.64-second silent WebM remains a visual sample, not the
final deliverable. No fresh model run or narrated recording is authorised by this plan alone.

## 1. What the original brief actually asks for

Source reviewed: all four pages of `AI-Powered Vault Document System_  Case Study.pdf`,
from the developer's Downloads folder. A copied PDF was text-extracted and visually reviewed.

- Pages 1–2: document processing, ingestion/retrieval/insight APIs, sessions/questions/history/
  multi-turn context, document/processing metrics, and appropriate persistent data structures.
- Page 2: Python, PostgreSQL, a task queue, file extraction, an AI provider and file storage.
  FastAPI is recommended within the Python requirement, rather than the only allowed backend.
- Page 3: recommended RAG framework, embeddings, AI coding tools, API documentation and tests.
  Frontend, streaming and caching are optional. Deliverables include working backend,
  repository, README, AI_USAGE and a required document-chat demo.
- Page 4: advanced AI, technical and production-readiness bonuses.
- Evaluation: AI-first development, product thinking and technical implementation each 33%.

Consequently the video must establish the required backend and grounded chat before spending
time on extras. The UI is the easiest way to follow the story, but is not the only evidence.

## 2. Format and editorial decision

Target: **6:00**, with a hard editing ceiling of **6:30**, 1920x1080, English narration and
matching subtitles. Approximately 650–720 spoken words, with pauses to read results.
Use a technical product walkthrough: actual application interactions, brief backend evidence,
and a small amount of explanatory annotation. No simulated typing of fabricated responses.

We can give every built feature a place in this time. We cannot demonstrate every endpoint,
edge case and internal mechanism in depth. The matrix below distinguishes actual actions,
saved output, code evidence and explanation. A checklist is not a substitute for a working
demonstration, so core chat receives the longest continuous section.

Record from an empty **isolated demo vault**, not by clearing the current vault. Show startup
health/services briefly; do not spend video time installing software or rebuilding images.
"From zero" means no demo documents or chats at the start, then ingestion through to results.
The existing main database, original files and conversations stay intact.

Optional UI/streaming can naturally appear during the required chat workflow. Labels and
narration will distinguish these from the required functionality; extra features receive
their own section only after required evidence has been shown.

## 3. Six-minute sequence

| Time | Priority | Screen and action | Evidence / purpose |
|---|---|---|---|
| 0:00–0:15 | Required context | Product title, empty demo Library, one simple flow diagram | What it solves; local single-user scope; services ready |
| 0:15–1:00 | Required ingestion | Upload a PDF, DOCX, Markdown and small TXT together; include invalid-file and duplicate outcomes; watch saved stage states | Per-file validation, accepted response, background processing, searchable documents |
| 1:00–1:25 | Required analysis/retrieval | Open PDF insights and a DOCX section reference; briefly show original content | Summary/key points with locators; saved extracted text and analysis |
| 1:25–2:25 | Required chat | Start session; ask budget; open page-3 source; follow-up approval date; CFO not-found; reopen history | Question, context, citations, refusal to guess and persistent conversation |
| 2:25–3:25 | Required backend/storage/metrics | Actual Swagger requests or readable API responses, stage rows, stored chunks/citations, document and processing metric responses | API and data model evidence, Celery work history, PostgreSQL/pgvector, monitoring |
| 3:25–4:05 | Optional/advanced AI | One multi-document question; whole-vault scope; suggested questions; custom summary with budget/risks focus and a repeated cached request | Extra search scope, summary settings, gap notice, result reuse; category/tags/tone highlighted |
| 4:05–4:45 | Bonus versions/comparison | Upload revised brief; once indexed open version history and comparison; show cited 41.5→44.0 change and shared passages | Retained old version, latest-version behaviour, stored comparison reuse |
| 4:45–5:20 | Bonus operations | Metrics cost view; health; rate-limit response from separately labelled fake checks; quick Stop/library actions | Cost controls, observability, caching, rate limiting, interrupted-answer handling and document management |
| 5:20–6:00 | Recommended engineering/deliverables | Small code/data-flow view, recorded tests, prompt correction example, README/AI_USAGE/log, limitations | Explain implementation and AI-assisted development; distinguish measured results from design reasoning |

The plan's time allocations are editing targets, not measured execution times. Document
processing and model calls may take longer; waiting can be cut with an explicit time-cut
label. Do not speed up narration to fit extra actions. Trim repeated explanations first.

## 4. Exact core story and sample facts

Use only fictional sample documents. Preserve the original/revised scope distinction:

1. Original Northwind brief: budget **41.5 million euros**, PDF page 3.
2. Follow-up: approval **4 March 2026**, page 3.
3. "Who is the CFO?": not established by supplied sources; expected not-found.
4. Multi-document question: **27 days annual leave** from handbook section, **June 2026**
   construction from original brief page 4.
5. Summary focus "budget and risks": supported budget facts and an explicit missing-risks
   notice; medium/executive settings match the known v5 real check.
6. Revision: **44.0 million euros**, **12 May 2026** approval, **3.6 million** contingency,
   **September 2026** construction, **Q4 2027** grid connection. Open the source of a retained
   difference; do not promise a fixed number of generated comparison rows.
7. Original-document chats keep the version they were attached to. Whole-vault scope selects
   latest chat-ready rows; a newly processing latest version can temporarily remove that
   group from the whole-vault search. Show the version before interpreting a changed answer.

## 5. Required-feature evidence checklist

| Brief item | How it earns screen time |
|---|---|
| Intelligent upload | Actual accepted/duplicate/rejected file outcomes, with content fingerprint/type checking explained |
| Smart analysis | Actual generated document summary/key points and their locators |
| Asynchronous pipeline | Fresh stage transitions plus saved extract/index/insight processing history; worker logs if legible |
| Upload & ingestion API | Actual upload response; UI request can be linked to its endpoint |
| Document retrieval API | Execute GET detail/content for the same sample ID |
| AI insights API | Execute GET insights for the same sample ID |
| Start session | Actual newly created session and its document scope |
| Ask question | Actual model answer, not a Swagger example body |
| History | Execute GET messages or reopen saved history from the just-recorded session |
| Multi-turn context | Actual approval follow-up; show search rewrite |
| Source-backed RAG | Actual source passage and diagram of scoped hybrid retrieval; marker validity is not semantic proof |
| Document Statistics API | Actual GET /api/v1/metrics/documents response with counts/statuses |
| Processing Metrics API | Actual GET /api/v1/metrics/processing response with stage durations/outcomes and usage |
| All storage groups | Compact read-only view: document/status, saved analysis, session/messages/citations, processing runs, AI ledger |
| Required stack | Diagram plus actual running service/code evidence; Python/FastAPI, PostgreSQL/pgvector, Celery/Redis, extractors, OpenAI, local file volume |
| Backend and source | Readable Swagger endpoints and a brief repository/service-code view |
| README and AI_USAGE | Show existing documents and assistance disclosure; developer-owned reviews remain unfilled until actually reviewed |

Backend proof should be focused and readable: two or three highlighted fields at a time.
Do not scroll through hundreds of lines of JSON or an unreadable terminal. Swagger's example
responses are not execution results. Read-only database views must hide connection secrets.

## 6. Optional, recommended and bonus coverage

| Capability built | Evidence in the short video | Qualification |
|---|---|---|
| React frontend | Used throughout | Optional in brief |
| Streaming answers | Observe one actual response arriving | SSE, not WebSocket |
| Live document status | Fresh ingestion transitions | SSE backed by worker events |
| Cached embeddings / metrics | Compact cache/read-only backend evidence and narration | Do not claim chat answers themselves are cached |
| Reusable summaries/comparisons | Repeat same saved request and show cached result | Prompt/model/options/version are part of reuse identity |
| Multi-document chat | Actual answer with handbook and brief references | Required single-document story already established |
| Whole-vault scope | Actual toggle/scoped query and latest-version explanation | Extra beyond basic selected-doc chat |
| Question suggestions | Show document-insight suggested questions | Not dynamically regenerated follow-ups after every turn |
| Categories/tags/entities/tone | Highlight existing insight fields | Suggested/AI-generated fields remain reviewable |
| Custom summaries | Actual medium/executive budget/risks request, settings and gap notice | Literal quote/topic schema guards do not guarantee truth |
| Comparisons | Actual cited difference and retained shared passage | V2 requires literal shared sentences; paraphrase matches can be omitted |
| Version history | Actual new version, previous version and scope behaviour | Do not clear the original |
| pgvector / hybrid retrieval | Explain meaning+word search, scoped query/code and saved chunks | HNSW used for whole-vault search; no large-scale benchmark claim |
| Test coverage | Recorded 152-pass/3-deselected evidence, date-labelled, or fresh fake run if needed | Fake tests check mechanics, not general model accuracy |
| Cost accounting / budget guard | Actual ai_calls/metrics and configured-cap explanation | Estimates, pre-call checks; in-flight calls can overshoot |
| Rate limits | Short HTTP 429 + Retry-After evidence in separate fake functional check | Not a paid request flood; no authenticated per-user quota system |
| Batch processing | Multi-file outcomes and code evidence of embedding batches | Not a measured throughput improvement |
| Logging / observability | Brief sanitised request-ID/stage outcome log | Do not expose prompts, document text or keys |
| Health / readiness | Actual successful response | Configuration readiness does not prove answer quality |
| Stop/disconnect | Actual partial response saved as interrupted, or clearly labelled retained evidence | Stop does not guarantee zero provider cost |
| Library search/filter/old versions | Short action montage | Filename search is distinct from semantic retrieval |
| Reprocess/delete | Disposable fake-mode fixture in a labelled technical insert, or mention supported actions | Never delete main/demo evidence to stage a result |
| API types/migrations/reliability | Brief repository/evidence view, explained in narration | Not every internal function needs a separate demonstration |
| LangChain/embeddings/API docs/pytest | Stack/code/docs evidence, not a library-name-only slide | Recommended tools in brief |

The page-4 bonus heading is "Production Readiness". Implementing some listed safeguards does
not make this production ready: no authentication/multi-tenant ownership or OCR is present.
Mention the current limits in the closing narration. Never claim tested scale to thousands.

## 7. Sound and export plan

- English voice-over plus English subtitles. Speak plainly, approximately 115–125 words per
  minute, synced to actual visible actions. Narration should explain purpose rather than
  read every UI label. Avoid background music competing with technical explanation.
- Existing Windows English voices David, Hazel and Zira were enumerated successfully.
  Voice generation, quality and final muxing still require a **10–15 second audio test**.
- Proposed first test: one introduction sentence plus one source-checking sentence. Compare
  voice clarity/pronunciation and ensure captions match. Local speech avoids paid TTS calls.
  Do not promise a natural human voice from a basic installed synthesiser.
- The prior WebM export plays correctly at 1080p. Prior MP4 MediaRecorder probing reported
  support but produced zero bytes. MP4 with sound is **not verified**. Confirm an audio/video
  export route before recording the entire walkthrough. If a new encoder dependency is
  required, name it and request permission under the project rules; do not silently install.
- Prefer a verified H.264/AAC MP4 for convenient submission, with a subtitle file. If that
  cannot be produced using approved tooling, report the limitation and offer a verified
  WebM with audio, rather than renaming an extension or delivering an unplayable file.

## 8. Work order after plan approval

1. Finalise storyboard and spoken script against this requirements matrix.
2. Produce/verify a 10–15 second narrated sound/export sample, without real AI calls.
3. Verify each built feature's evidence source and selectors; prepare the fake-only technical
   inserts without touching main data. Inventory existing tools before requesting dependencies.
4. Start an isolated, initially empty real-mode demo project using existing approved images
   and the existing ignored configuration. Check that volumes, ports, images and routing do
   not mutate the main stack. No paid ingestion or chat yet.
5. Present the final live-action list, expected model-call count and cost, and obtain fresh
   explicit approval before any real AI capture/rehearsal. Approval to plan is not spend approval.
6. Record one fresh end-to-end real pass and labelled fake technical inserts. Log any failed
   result honestly. Do not automatically spend on retries/reshoots beyond the authorised scope.
7. Edit to six minutes, keep clear evidence of genuine source-backed chat, sync narration,
   embed captions and include short section labels: Required / Optional & Bonus / Engineering.
8. Watch the full rendered video with sound, inspect text/source legibility, confirm actual
   duration/resolution/audio, check no secrets appear, and deliver locally for review.

Do not publish or submit. Do not delete the existing vault. Do not fill human-review fields.

## 9. Provisional spending and deliverables

A fresh pass using four small source formats, one revision, roughly seven chat actions, one
or two summaries and a comparison is provisionally **30–40 model calls** including document
embeddings/insights and follow-up rewriting. Estimated application spend **$0.01–$0.03**;
proposed allowance **$0.05**. This is not approval or a guaranteed bill. Refine the exact
action list before requesting it. Cached reads and fake rate-limit/failure inserts add no
model spend. Local narration is proposed; no paid speech provider is authorised.

Final deliverables: verified playable narrated video, subtitle file, final spoken script and
a requirement-to-video timestamp checklist. Keep a separate full capture if useful for
editing, but the reviewer's primary video should remain short. The final format is subject
to the audio/export test above.

## 10. What is verified at planning time

Verified: original PDF text and all four rendered pages; required/optional/bonus classification;
current feature docs/code for metrics and suggestions; existing Windows English voice names;
the previously produced silent WebM's playback. No fresh model calls, new narration, encoder
installation, environment setup or full recording performed for this planning task.

Unverified: voice quality, audio/video mux route, final MP4 compatibility, exact narration
timing, final captured results and any fresh model cost. The short target is achievable by
editing/grouping, not by pretending every feature has been exhaustively demonstrated.

## 11. Narrated pilot completed (15 October 2026)

The developer authorised the free sound/export pilot. Produced a 15.0-second 1920x1080 WebM
excerpt with local Microsoft Zira English narration, embedded matching captions, a sidecar
SRT and spoken-script text. Files are in B:\f-work\case study\demo-video, with the main file
named ai-vault-narrated-sample.webm. Existing real-mode results are labelled as saved output.
No new model call, paid TTS, app change, dependency installation or main-data mutation.

Verified Opus audio decoding, speech levels and correlation to source narration (about 0.976,
zero offset), plus browser playback and sampled rendered frames. This verifies the local
WebM sound route, not human judgement of voice quality or general player compatibility.
MP4 export remains unverified. Developer voice/pacing review and the bounded live-capture
approval are still separate steps before the full real-mode recording.

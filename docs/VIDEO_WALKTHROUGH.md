# AI Vault video preparation and spoken script

> The current submission target is the [six-minute narrated plan](FINAL_DEMO_PLAN.md).
> The longer script below remains a learning/reference version.

Use [LEARNING_GUIDE.md](LEARNING_GUIDE.md) first. This is a recording plan and reusable spoken
script, not evidence that a new recording or live run has already happened.

## Choose the length

- **About 7 minutes:** introduction, upload, cited answer, follow-up, not-found,
  multi-document answer, brief summary/version demonstration, limits.
- **About 12–15 minutes:** use the full script below, including architecture, comparisons,
  metrics and engineering explanation. Actual time depends on processing and narration speed.
- Keep deeper interview answers in the learning guide; do not read the whole guide on camera.

The spoken sections describe the application without inventing personal design decisions.
Only add "I designed/chose/implemented…" where that is true of your own contribution.

## Preparation that preserves the existing vault

1. Confirm Docker Desktop is running. In the repository folder, `docker compose ps` shows
   services. If they are stopped, `docker compose up -d` starts the existing stack.
2. Do not run `docker compose down -v`: it deletes the saved database/file volumes. A fresh
   vault is unnecessary for this recording. Preserve existing demo records.
3. Open `http://localhost:5173`, `http://localhost:8000/docs` and
   `http://localhost:8000/api/v1/health/ready`. Do not display `.env` or keys.
4. Use the readiness response and visible mode labelling to check mode. In fake mode, state
   that responses are deterministic placeholders. Do not hide the FAKE AI MODE banner.
5. Review Library first: which samples and versions already exist? Attach the intended
   version. If an upload is a duplicate, explain reuse; do not claim you just processed it.
6. A fresh upload, question, uncached summary, comparison or reprocess in real mode can spend
   money. This documentation task performs none of those. Before asking the assistant to
   rehearse/run them, approve a new bounded real run. Previous test approvals are exhausted.
   Reusing saved messages/results is an alternative: label them as previously generated.
7. Open the sample folder `B:\f-work\case study\ai-vault\samples`.
8. Record the browser at a readable zoom, around 110–125%; 1080p is a useful target. Turn off
   distracting notifications. Check microphone sound with a short local recording.
9. Keep this script in another window. Pause after each result so viewers can read it. If you
   edit out waiting, label that edit rather than claiming an unmeasured response time.

No recording software is required by this project; use a screen recorder you already have.
Recording/submission remains your action. This guide does not publish anything.

## Sample truth sheet: keep this beside you

| File/version | Known source facts |
|---|---|
| `northwind-brief.pdf`, original | p2: 48 MW; p3: 41.5 million euros budget, approved 4 March 2026, contingency 3.2 million; p4: construction June 2026, contractor Brightline Builders, grid connection Q2 2027 |
| `northwind-brief-v2.pdf`, revision | p3: 44.0 million euros budget, approved 12 May 2026, contingency 3.6 million; p4: construction September 2026, grid connection Q4 2027 |
| `employee-handbook.docx` | Leave Policy: 27 annual-leave days, up to 5 carried over; Remote Work: up to 3 days weekly with manager approval |
| `onboarding-guide.md` | Accounts: Tunnelbear-X VPN client; Staging: Tuesday at 14:00 UTC |
| `not-a-document.exe` | Deliberately invalid sample; use to show rejection, never execute it |

The samples are fictional. Check which version is selected before comparing an answer with
this sheet. Model wording may vary; assess facts and source references rather than exact prose.

## Full script

### 1. Introduce the product — about 45 seconds

**Show:** Chat home, then briefly Library.

**Say:**

"This is AI Vault, a document application with an AI question-and-answer interface. The user
uploads documents, asks questions in normal language, and receives an answer with references
to the source text. It also provides summaries, key information, version history and document
comparisons.

"The aim is to reduce the work of manually searching several files. The source links help
the user check an answer. This is a local single-user case study, and it does not currently
have login or production access controls. The demo files are fictional examples."

### 2. Explain the architecture — about 75 seconds

**Show:** The diagram in the learning guide or `docs/ARCHITECTURE.md`. Enlarge it before recording.

**Say:**

"The React frontend is the interface. FastAPI receives requests and coordinates the work.
PostgreSQL stores documents, extracted text, conversations and results. Its pgvector extension
stores the numerical representations used for meaning-based search.

"Uploads can take time to process, so Redis queues work for a Celery background worker. That
worker extracts text, builds the search index and creates automatic insights. Redis also
supports caching and status notifications. Original files are kept in a local storage volume.

"In real mode, OpenAI generates embeddings and text outputs. This means some document text
leaves the local environment for AI processing. Docker Compose runs these cooperating services."

### 3. Upload and processing — about 60–90 seconds

**Show:** New chat; attach the original brief and handbook. If authorised and not already
present, demonstrate upload. Otherwise show existing records and explain them as saved data.
Optionally add the invalid sample to show rejection. Do not open/execute the invalid sample.

**Say:**

"The upload handler checks size and file contents, rather than trusting the extension alone.
Each file gets its own outcome, so one invalid file does not silently hide the valid uploads.
A content fingerprint detects identical files and reuses the existing record.

"For a new file, the backend saves an ID and queued state before background processing.
The worker extracts text with its original page or section. Indexing and automatic analysis
then run independently. These status chips reflect saved processing stages and update live.

"Chat becomes available when indexing succeeds. Insight generation can still be running, or
can fail independently. There is no OCR, so image-only scans need another extraction approach."

**If duplicate appears:** "This file already exists, so the application reused it. No new
document processing was needed for this upload."

### 4. Read automatic insights — about 45 seconds

**Show:** Library -> original brief -> document details; then handbook if useful.

**Say:**

"The automatic analysis provides a summary, key points, entities, categories, tags and
suggested questions. The coverage information shows what input was included.
PDF references use physical pages. The handbook uses sections because this extractor cannot
reliably assign fixed DOCX page numbers. These are model-generated insights and still need
review; structured output does not make every claim correct."

### 5. Ask a question and check its source — about 75 seconds

**Show/type:** Chat attached to the **original** brief:

```text
What is the total capital budget?
```

Open the citation chip when the answer completes. If using saved output, say it is a retained
answer from an earlier real run.

**Expected fact:** 41.5 million euros; PDF page 3. With revision 2, the fact is 44.0 million.

**Say:**

"For this question, the backend searches the selected document's chunks using both meaning
and words. It combines those rankings and sends selected passages to the model. The model is
instructed to answer from those passages and attach source markers.

"The answer streams into the browser. This citation opens the original source passage from
page 3. Source one means the first retrieved passage for this answer; it does not mean page one.
The server checks that the marker points to a supplied source. I still need to read that
source to check whether the claim is actually supported."

### 6. Demonstrate a follow-up — about 40 seconds

**Type:**

```text
When was it approved?
```

**Expected fact for original:** 4 March 2026, page 3. Revision 2: 12 May 2026.

**Say:**

"This question depends on the previous answer. The follow-up step can rewrite it as a
standalone search question about when the capital budget was approved. The interface can
show that search wording.

"The active version is condenser v3. It was changed after a real test showed v2 attaching
an ambiguous pronoun to the wrong subject. V3 preserves the original question when the
conversation does not establish a clear subject. It has passed the known test case, but
that does not prove perfect handling of every conversation."

### 7. Show not-found behaviour — about 30 seconds

**Type:**

```text
Who is the CFO?
```

**Expected:** not found in the selected documents; no valid factual citation.

**Say:**

"The supplied sample does not establish who the CFO is. A useful result here is to say the
answer was not found, instead of inventing a name. This result also depends on retrieval;
it is not proof that a fact could never be found anywhere in a larger collection."

### 8. Show multi-document scope — about 45 seconds

**Show:** Ensure the original brief and handbook are both attached. Ask:

```text
How many days of annual leave do employees get, and when does construction of the solar farm start?
```

**Expected:** 27 days from Leave Policy; June 2026 from original brief page 4.

**Say:**

"This question needs two documents. The leave policy supplies one fact and the project brief
supplies the other. The answer should identify the relevant document for each fact and show
both sources. Scope is enforced by the server. Search entire vault broadens the search to
the latest chat-ready version rows; it is different from this explicitly attached scope."

### 9. Explain a custom summary — about 60 seconds

**Show:** Library -> original brief -> Custom summary. Choose medium, executive, focus:

```text
budget and risks
```

Use a saved result or, with fresh spend approval, Generate. Prefer these settings because
they match the retained v5 real test. If repeating an identical request returns cached=true,
point out the stored-result label.

**Expected:** supported budget facts and a missing-risks notice. Wording can vary.

**Say:**

"Automatic insights are created during processing. This is a separate summary requested
with a length, tone and focus. The source covers budget but does not address risks.

"Earlier real checks exposed invented risks and then merged focus topics. Summary v5 now
requires an independent verdict for each topic defined by the server, plus cited points
and literal evidence quotes. The server builds the summary and missing-topic notices.

"The known budget-and-risks case and a no-focus control passed the latest two real checks.
That is a narrow result, not proof that every future topic judgement will be correct.
An identical stored request can be reused without another model call."

### 10. Show versions and comparisons — about 60–90 seconds

**Show:** Versions panel. If revision 2 exists, open it; otherwise only ingest it with a
separately authorised live demo run. Once settled, open "What changed since v1?" or a stored
comparison. Do not promise exactly five retained rows: focus, validation and model output
can affect which differences appear.

**Say:**

"A revision gets its own processing records while the earlier version stays available.
Here the source budget changed from 41.5 to 44 million euros. Other source changes include
approval date, contingency, construction start and grid connection. The table should link
each retained change to the relevant source locations.

"Comparison v2 keeps literal matching shared sentences as shared passages. This reduces
generic unsupported similarities, but can miss a true similarity written in different words.

"Whole-vault chat uses latest versions. A chat attached to version one keeps version one,
so always check the selected scope when interpreting an answer."

### 11. Show metrics and explain the safeguards — about 60 seconds

**Show:** Metrics; briefly API docs if time permits. Read the actual values currently visible.

**Say:**

"The application records processing attempts, timings and model calls. Token usage is used
to estimate cost by purpose and model. These numbers are estimates, not invoices.
It checks accumulated estimated spend before each model call; the default app setting is
50 cents. Calls already in progress can overshoot that threshold.

"There are also per-minute request limits, cached query embeddings and reusable summaries
and comparisons. A question can still trigger multiple model calls. API documentation makes
the backend operations visible independently of the frontend."

**Optional Stop:** Only during an authorised new live answer, click Stop. Explain that the
partial result is saved as interrupted. Do not claim stopping guarantees zero provider cost.

### 12. Tests, AI assistance and limitations — about 60 seconds

**Show:** The recorded evidence in EVALUATION.md, then AI_USAGE.md. Label recorded test output
as previous evidence, rather than implying you just reran it.

**Say:**

"The latest recorded backend suite has 152 passing fake-mode tests and three live tests
deselected. Fake mode checks the application mechanics with deterministic model doubles.
Real evaluations are separate, and the evidence includes both successful cases and failures
that led to prompt and validation changes.

"The implementation was AI-assisted using Claude Code and OpenAI Codex. The usage document
and development log record that assistance. Personal review fields should describe only
review that was actually completed.

"Current limitations include no authentication, no OCR, local file storage, English-oriented
full-text search, limited real-model evaluation and no demonstrated large-scale performance.
Citations improve traceability but do not prove every claim. Further work would include
access control, broader evaluation and stronger evidence checking."

## If the result differs while recording

| Situation | What to do or say |
|---|---|
| 44 million instead of 41.5 million | Check if revision 2/latest scope was used; do not immediately call it a hallucination |
| Already in vault | Explain content deduplication and reuse |
| Processing takes longer | Wait; inspect the stage status. Do not invent a timing |
| Not found for an expected fact | Check scope/version/readiness and question wording; preserve the failed example honestly |
| An answer cites a real passage but misstates it | Show the discrepancy; a valid marker is not a truth guarantee |
| Fake-mode banner | Describe a functional rehearsal, not real-model quality |
| Rate limited | Wait for the indicated retry time; do not edit limits just for the video |
| AI budget/provider error | Stop new AI actions, inspect the error/metrics; do not raise the budget without deciding to do so |
| Summary says selected parts | Explain incomplete input; do not claim whole-document absence |
| Comparison omits a similarity | Explain the literal shared-passage rule and its recall limitation |

## A short rehearsal without paid calls

Open existing Library records, read the facts, open saved messages/citations, inspect versions,
show metrics and API docs, and speak the upload/question flows aloud. Present saved output as
saved output. Do not send a new question, click Generate, start an uncached comparison,
upload a new real-mode document or reprocess for this rehearsal.

## Final checks before sharing the recording

- A viewer can read the result and source passage.
- Real and fake output are labelled accurately; no keys or private files are visible.
- You explain both a successful answer and an appropriate not-found result.
- The selected versions match your expected numbers/dates.
- You distinguish passing application tests from general AI accuracy.
- You describe AI assistance and personal contribution truthfully.
- You state the important limits and proposed future work.

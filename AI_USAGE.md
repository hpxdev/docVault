# How I used AI

I used AI coding assistants throughout this case study, from planning the backend to
building the application, checking results and preparing the demo. Most of the code,
tests and documentation were written with AI assistance. My role was to set the direction,
choose the scope, approve paid checks and give feedback on the product and demo.

This account is based on the development log, Git history and recorded decisions. It does
not claim that I wrote every component or personally reviewed every line of generated code.
The detailed technical record is in [docs/ai-log.md](docs/ai-log.md).

## Tools used

- **Claude Code** helped implement the initial backend, database, workers, tests and React
  interface. It also ran checks and kept the early development log.
- **OpenAI Codex** continued the work, reviewed the case-study requirements, expanded
  verification, improved prompts and output validation, updated the interface and prepared
  the demo and submission documentation.
- **OpenAI models inside the application** serve a different purpose from the coding
  assistants. The app uses `gpt-4o-mini` for answers and analysis, and
  `text-embedding-3-small` for retrieval embeddings. Model settings are configurable,
  subject to the application's pricing table and embedding schema.
- **Deterministic fake providers** were used for routine development and automated tests.
  These do not call an external model or prove the quality of real AI answers.

## My decisions and feedback

I asked to work through the case study one step at a time and build the backend before
polishing the frontend. The plan covered upload, saved processing states, extraction,
retrieval and cited answers before optional features.

I approved the blueprint and the implementation scope. The assistants proposed and
implemented technical details, including FastAPI, PostgreSQL with pgvector, Celery and
Redis. I controlled when real-model evaluations could use the API budget. The API key was
kept in the local environment rather than committed to the repository.

After the core application, I chose to include custom summaries, document comparisons,
version history and rate limiting. For the interface, I asked for five upload designs and
selected the split workspace. I then requested dark mode as the default and subtle,
professional animations.

I also gave feedback on the video. I rejected repetitive zooms and pointed out that Swagger
was missing. The revised edit uses stationary reading views, short transitions and an
actual loaded Swagger response. The final video review and upload remain my responsibility.

## How the work was checked

The assistants ran builds, lint, tests and browser checks, then recorded the results.
The automated backend tests use real PostgreSQL and Redis services with fake AI providers.
They check upload rules, extraction, task status, retries, retrieval scope, citation
validation, chat history, streaming, caching and the additional features.

Separate, explicitly approved real-model runs checked answer quality on known sample
documents. The results include failures as well as successes. The evaluation notes explain
which prompt version was used, what was checked and what the result does not establish.
See [docs/EVALUATION.md](docs/EVALUATION.md).

The final submission checks are recorded in
[docs/SUBMISSION_CHECK.md](docs/SUBMISSION_CHECK.md). These distinguish new checks from
earlier evaluation evidence. No fresh real-model run is implied by a successful fake test.

The log contains unfilled human-review fields from earlier tasks. I have not filled them
after the fact or treated assistant-run tests as evidence of my own line-by-line review.
My documented contribution is the direction, approvals, feature choices and feedback
described above.

## Examples where the first AI output was wrong

| Problem | How it was found | What changed |
|---|---|---|
| Indexing and insights could finish at the same time and leave a document stuck in processing. | A running-stack walkthrough found it after sequential tests had passed. | The worker refreshes the locked database row, and a concurrent regression test covers the case. |
| A follow-up prompt guessed what an ambiguous reference meant. | Real-model checks compared the rewritten question with the conversation. | The prompt was revised to preserve questions when the referent is unclear. |
| A custom summary invented a risks point that the document did not contain. | The generated summary was compared with the sample document. | Later prompts require evidence quotes and separate verdicts for each requested topic. The server adds missing-topic notices. |
| A comparison described identical statements as differences. | A real comparison of two known versions exposed it. | The server removes identical differences. Later similarity checks also require matching source sentences. |
| The first video review missed a Swagger loading screen. | My feedback prompted another visual check. | The shot was replaced with loaded endpoint documentation and a real read-only HTTP 200 response. |

These corrections are examples of why generated output needed checking. Passing tests did
not mean the first implementation or every generated answer was correct.

## Prompt design

Application prompts are stored as versioned files in `backend/app/prompts/`. The main choices were:

- Retrieve only from documents allowed by the current chat scope.
- Give each retrieved passage a source identifier and an exact page, section or line range.
- Ask for citations and an explicit not-found answer when evidence is missing.
- Treat document contents as untrusted input, rather than instructions to the assistant.
- Use structured output for insights, summaries and comparisons so the server can check it.
- Store prompt versions with results so failures can be traced and compared.

The server checks source identifiers, locations and supported evidence quotes. These checks
do not prove that every paraphrase is correct or that a cited passage fully supports a claim.
Worked examples and changes are in [docs/PROMPTS.md](docs/PROMPTS.md).

## Demo and remaining limits

The latest video is a fresh real-time recording, made after the developer requested a plain,
silent functionality demo. It contains three live recorded segments joined with two plain
cuts, with no voiceover, zoom effects or time compression. Its approved isolated run used
30 calls including one failed server response and a diagnostic check; the ledger estimate
was $0.00430415. Failed takes were excluded from the delivered video and remain recorded
in the run evidence. The main vault's AI ledger did not change. See [docs/REALTIME_VIDEO.md](docs/REALTIME_VIDEO.md).

The earlier narrated video uses results from an approved real-model run, displayed again in the
updated interface. Upload and processing chronology are replayed from archived responses.
The recording discloses this; its edited timings are not a performance benchmark. Narration
uses the local Microsoft Zira synthetic voice. See [docs/VIDEO_DELIVERY.md](docs/VIDEO_DELIVERY.md).

Real-model evaluation is still small and based on synthetic sample documents. It does not
establish reliability for arbitrary documents, general resistance to prompt injection or
large-scale performance. The application is a local, single-user case study with no
authentication or OCR. Those limits remain visible in the README and evaluation notes.

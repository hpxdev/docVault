# AI Vault demo video delivery

This describes the earlier narrated edit. The latest requested plain, silent live recording
is documented in [REALTIME_VIDEO.md](REALTIME_VIDEO.md).

The full edit uses the updated dark workspace UI, English narration, matching subtitles,
stationary detail views, quick cuts and explanatory motion graphics. Required workflow and backend evidence precede
optional and bonus features. Local output folder: `B:\f-work\case study\demo-video`.

## Files

- `ai-vault-demo-polished.webm`: revised narrated 1080p / 24 fps edit, without slow zooms.
- `ai-vault-full-demo.webm`: earlier 15 fps edit, retained for comparison.
- `ai-vault-full-demo.srt`: matching narration subtitles.
- `ai-vault-full-demo-script.md`: complete spoken script.
- `FEATURE_CHECKLIST.md`: timestamped chapter and feature coverage.

## What the footage represents

The underlying real run was explicitly approved and completed before the UI redesign. It
used 25 successful model calls, zero failed calls, at $0.00391133 estimated cost. The main
vault remained unchanged. Results and API/storage evidence are preserved in
[EVALUATION.md](EVALUATION.md#fresh-full-video-capture-2026-10-15-approved).

This remake recaptures those saved real answers in the new frontend. Browser-local replay
uses the actual archived upload/version/summary/comparison responses and saved message
history. It does not send new questions, upload files to the real backend or invoke a model.
Ingestion chronology is replayed; its edited timing is not a performance measurement.
Narration and on-screen labels identify the saved real-run recapture. No artificial streamed
typing is used to imply a fresh generation. No new AI or paid speech cost for this remake.

The short operations insert distinguishes earlier fake functional checks from real results.
Stop uses a separately labelled retained real interrupted result. Architecture and engineering
panels explain internals and earlier recorded tests; not every endpoint is demonstrated live.
The 152-pass backend test result is historical evidence, not a new test of the redesigned UI.

## Sound and format

Narration uses the installed Microsoft Zira synthetic English voice. The exported format is
WebM with VP8 video and Opus audio. MP4 export is not verified. Use the in-app player or a
browser that supports WebM; universal player compatibility is not claimed.

## Data and source preservation

The user's frontend edits and preview images remain unchanged and are not bundled into the
video-documentation commit. The original main ledger remained 43 calls / $0.00674021; the
isolated recorded demo remained 25 calls / $0.00391133 after UI recapture. Temporary demo
services are stopped, while their volumes and recording evidence are retained. No publishing
or submission was performed. No new dependencies were installed.

## Earlier export verification (superseded edit)

Exported duration: 372.533 seconds (about 6:13), 1920 × 1080, 15 fps, 5,588 video frames.
The file includes 18,628 Opus audio packets. Narration decoding matched the source speech
with correlation 0.972; all 22 chapter speech windows passed non-silence checks. Chapter
frames decoded successfully; introduction, source, summary, comparison, operations and
closing frames were visually inspected. Final complete browser playback reached
ended=true at 372.54 seconds with no error. At accelerated 4× playback, the browser reported
679 dropped frames across playback and chapter seeks; this is not a smoothness benchmark.
The local verification report is retained with the recording evidence.

These are technical media checks, not a human listening judgement of the synthetic voice.
The browser playback check is muted at accelerated speed. General player compatibility
and MP4 export remain NOT VERIFIED.


## Revised motion edit

The developer rejected the repeated slow zooms and identified missing Swagger content.
The earlier Swagger screenshot was a loading screen; it was not adequate evidence of the
rendered documentation. The revised capture waits for 28 loaded operations, opens a document
endpoint and executes a read-only GET against an existing main-vault document. Its actual
HTTP 200 response appears alongside the endpoint list. This does not invoke an AI model.

The revision removes all continuous camera zooms/pans. Reading views hold stationary; short
cuts reveal details. New motion graphics explain upload validation, the independent indexing
and insight stages, retrieval and cached-result reuse. They are labelled as explanations,
not live work progress. A closing graphic states limitations and next steps.

UI scenes were recaptured at 2x device scale using archived responses. The suggestions shot
now shows actual saved suggested questions. The not-found and retained Stop crops include
their complete relevant status. Source and version details have fixed, readable framing.
The full replay audit recorded 87 handled requests, zero blocked and zero unhandled requests.
No new paid calls or speech generation, dependencies, app edits or publishing.

A layout audit found no titles or captions exceeding their allotted lines. Six key reading
views were checked to remain pixel-identical between holds; motion diagrams change as
expected. Final export: 372.542 s, 1920 x 1080, 24 fps, 8,941 frames, 71,996,934 bytes.
All 66 sampled chapter/subscene frames decoded and matched the frame-aligned composition
(maximum image RMS difference 7.71 / 255; tolerance 20). An initial comparison landed across
a cut by 0.0005 seconds; comparing the actual 24 fps frame resolved that false mismatch.
All 22 chapter speech windows passed; audio correlation to source narration was 0.972034.
Full muted playback at 4x reached the end without error; it reported 3,669 dropped frames
across accelerated playback and seeks, so that check is not a smoothness benchmark.

Two checks on a page that first loaded the application reported 23/420 and 24/385 dropped
frames. A dedicated clean player at full 1080p size, after settling following a seek, reported
0 dropped / 384 frames without error. This scoped check does not establish
all-player smoothness or replace a full human review of pacing and voice quality.

Machine-readable evidence: [video-motion-2026-10-15.json](evaluations/video-motion-2026-10-15.json).
The video folder contains matching subtitles, script, checklist, poster and verification.
No application tests rerun for the media/docs-only change. SHA256: `90efe4a5e1183019fb0eda8518bb00fb256ab82d847c9e3dc6481686c6730866`.

# AI Vault demo video delivery

The full edit uses the updated dark workspace UI, English narration, matching subtitles,
focused zooms/pans and short cross-fades. Required workflow and backend evidence precede
optional and bonus features. Local output folder: `B:\f-work\case study\demo-video`.

## Files

- `ai-vault-full-demo.webm`: full narrated 1080p edit.
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

## Export verification

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

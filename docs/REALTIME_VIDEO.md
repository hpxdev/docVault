# Plain real-time demo

## Short demo

Latest requested edit: `B:\f-work\case study\demo-video\ai-vault-short-demo.webm`.
80.936 seconds (1:21), 1920 x 1080, silent VP8 WebM, 6,046,690 bytes.
It selects 19 working views from the actual recording, skips long waits and accelerates
selected interactions. Answer reading views remain at normal speed. There are no zooms,
graphics, narration or music. Edited timings do not measure application response speed.
No backend or model changes, new AI calls or new paid costs were involved.

All 19 scenes decoded and complete browser playback at 4x reached the end without error;
zero audio bytes decoded. The accelerated check/seeks reported 47 dropped frames.
Visually checked the scene contact sheet and full-size whole-vault and version views.
Metadata, source ranges, speed factors and checks are in
[short-video-2026-10-15.json](evaluations/short-video-2026-10-15.json).

## Retained full recording

Latest file: `B:\f-work\case study\demo-video\ai-vault-realtime-silent.webm`.
Duration 366.747 seconds (6:07), 1920 x 1080, VP8 WebM, no audio track.
Three live screen recordings are joined with two plain cuts. The first segment
is 25 fps and the remaining segments 15 fps; original frame timestamps are retained. There are no
overlays, voiceover, music, zoom effects, graphics, transitions or time compression.

## Recorded functionality

- Upload PDF, DOCX, Markdown and TXT together; show processing, ready states and file rejection.
- Re-upload an identical document and show deduplication.
- Inspect generated insights, source locations and suggested questions.
- Ask a fresh question, open its original cited passage, ask a follow-up and get a not-found answer.
- Reopen saved chat history, ask across two documents and search the whole vault.
- Generate an executive summary focused on budget and risks, including the missing-risks notice.
- Request the same summary again and show the stored result without another model call.
- Upload version 2, inspect version history, compare five changes and six matching passages.
- Filter the library and ask a whole-vault question that uses the latest budget.
- Stop a streaming answer and retain its partial text.
- Inspect document, processing, chat and cost metrics; delete a disposable sample.
- Open loaded Swagger documentation (28 operations) and execute a real document GET, HTTP 200.

These are visible examples, not an exhaustive test of every API, failure path or scale claim.
The backend is demonstrated through its actual processing, metrics and Swagger response;
the video does not contain a source-code tour or database terminal insert.

## Provenance and cost

The developer approved at most 35 calls and $0.05 for a fresh real-mode recording.
The isolated `ai-vault-realtime-1015` run used 30 ledger calls: 29 succeeded and one
failed with an OpenAI server error. Estimated cost, including failed and diagnostic calls:
$0.00430415. This is the app's token-based estimate, not a provider invoice.
The main vault ledger was unchanged: 43 successful calls, estimated $0.00674021.

All displayed results were generated in this fresh isolated run, with no mocked responses
or replayed upload chronology. Failed attempts and an off-camera diagnostic call are retained
in the local evidence, but their footage is excluded. An early navigation race interrupted
the first take after uploads; the successful upload segment was retained and the chat
sequence recorded separately. A third segment reopens source evidence and suggestions,
shows deduplication and a stored summary, then records loaded Swagger and final metrics.
A visual check caught stale recorder frames on static screens, so those views were
recaptured with periodic fresh browser frames. The final metrics view waits for data.
Database recovery events and a transient provider failure
also interrupted earlier attempts. Their exact infrastructure cause was not established.
Actual waits in the delivered segments are retained; timing is not a performance benchmark.

Permission was given to pause a separate submission-test container. It had already finished
before any pause occurred, so no container was paused or requires resuming. Only this
recording's temporary stack was stopped after capture. Volumes and local evidence remain.

## Verification

Export metadata, SHA256, sampled frames, approval limits, AI ledger and playback results
are retained in [evaluations/realtime-video-2026-10-15.json](evaluations/realtime-video-2026-10-15.json).
All 38 functional scene samples decoded. Complete browser playback at 4x reached the end
without a media error and decoded zero audio bytes. The delivered file plays at normal
speed. Accelerated verification reported 22 dropped frames; this is not a smoothness
benchmark. Exported source, duplicate, summary, Swagger overview/HTTP 200 and final metrics
frames were visually inspected. The final segment shows a running worker with no offline banner.
Local raw evidence is under `.checks/realtime-video/run/`; the video is outside Git.
MP4 export, general player compatibility and human acceptance remain NOT VERIFIED.
No application source or dependencies were changed for this recording. No video was published.

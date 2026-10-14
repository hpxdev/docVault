# Live evaluation (real OpenAI models)

**Status: NOT RUN.** No live OpenAI call has been made. Everything in the test suite so far uses
deterministic fake providers, which prove the plumbing but not answer quality.

When approved, the live run (`tests/live/test_live_openai.py`) will:
- process one self-written 6-page document (`samples/northwind-brief.pdf`) end to end with
  `gpt-4o-mini` and `text-embedding-3-small`;
- ask 10 questions: 7 answerable (expected page + key phrase), 3 unanswerable (expected
  `not_found`);
- record the actual answers, statuses, cited pages, latencies and the ledger's estimated cost.

This file will then contain only the actual results of that run (date, models, per-question
outcome, cost from the `ai_calls` ledger).

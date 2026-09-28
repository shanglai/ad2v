# ADR-0032: Planning, running and the budget guard

- Status: accepted (P4)
- Decisions:
  1. `ad2v llm plan` is read-only. It counts input tokens with the provider's `countTokens` only
     with `--count-tokens` and a live provider; otherwise it uses chars/4, labeled as an
     estimate. Output tokens are estimated per task (judge 300, suggest 350, summarize 450,
     narrate 60 per step + 80, extract-prose 1500).
  2. `ad2v llm run` needs `--max-cost-usd` **and** `--yes`, refuses a cap above `llm.budget_usd`,
     and refuses a live provider without `llm.pricing`.
  3. **The pre-call check** refuses a call when spent + estimate > cap. From the task's second
     call on, the output estimate is the larger of the static estimate and the average output
     tokens observed so far in the run. On the live run, reasoning tokens made the actual output
     about 3× the static estimate. The worst overshoot is one call's difference between estimated
     and actual cost.
  4. Each task commits on its own, so results already paid for are never lost if a later task
     fails or aborts. The `llm_runs` row records calls, hits, tokens, estimated cost and the
     aborted flag.
  5. `--no-llm-cache` makes a fresh call for every job and keeps the old results. That is how
     run-to-run stability is measured.

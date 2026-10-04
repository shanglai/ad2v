# ADR-0052: The quickstart is executed, and `--from` is relative to the repository

- Status: accepted (P7)
- Context: `docs/quickstart-draft.md` was written without running it. P7 M1 ran every local
  command against a copy of `payments-recon`, the P3 history scenario and the three preset
  fixtures.
- Decisions:
  1. **The guide is tested.** `docs/quickstart.md` replaces the draft. `tests/test_quickstart.py`
     (marker `slow`) runs the guide's local commands through the real CLI: extract with and without
     `--spec`, status, inspect, validate, history, log, diff, materialize, `extract --into`,
     `view --no-browser` (the URL answers 200), `llm plan` (fake), `suggestions list`,
     `specs bootstrap --plan` / `review`, the preset fixtures, and an MCP `tools/list` over stdio.
     Cloud steps are skipped with a reason.
  2. **CLI change.** `ad2v specs bootstrap --from` resolved relative paths against the current
     directory, while `--spec-root` in the same command resolves against `--repo`. Run from
     another directory, `--from docs` picked up the wrong folder. `--from` is now relative to
     `--repo`, and a source outside the repository is refused, because proposals record a
     repository path for staleness.
  3. **Fixed in the guide only** (the CLI is consistent):
     - `history --commits HEAD~20..HEAD` fails on a repository with fewer than 21 commits (a git
       range). The guide says so and offers `--commits HEAD` (the whole history);
     - `suggestions accept/reject` need `--manifest` (they edit it);
     - `<repo>/ad2v.yaml` is read automatically, so `--manifest` is only for a manifest elsewhere;
     - viewer step names now match the UI ("Normative status", "Replay a workflow…",
       "Compare with parent");
     - `specs bootstrap --plan` keeps its cache in `<repo>/.ad2v/`, so the guide asks for
       `.ad2v/` in `.gitignore`.

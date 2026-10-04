# ADR-0049: Bootstrapping specs from prose: propose, review, approve

- Status: accepted (P6.1)
- Context: many repositories have prose (`docs/NOTES.md`, design docs) but no requirements in
  any convention. The P4 `extract-prose` task can turn prose into ad2v Markdown, but its output
  must not become normative without a human.
- Decisions:
  1. **Three CLI commands; no viewer or MCP write path.**
     - `ad2v specs bootstrap --from <paths> [--plan] [--yes --max-cost-usd N]` lists the
       qualifying files (Markdown/text with no recognized spec structure), plans through
       `llm.api.plan` (no calls), and runs only with `--yes` (exit 2 without it). Proposals
       go to `<spec root>/.ad2v-extracted/`, which extraction excludes, with an
       `index.json` (source path, source hash, model, run id).
     - `ad2v specs review` lists each proposal: source, model, component and requirement counts,
       token-overlap (Jaccard) against existing requirements, staleness (source hash changed), and
       id clashes with the spec tree.
     - `ad2v specs approve <proposal> [--to DIR] [--force-stale]` moves the file into the spec
       tree. It refuses stale proposals, overwrites and id clashes.
  2. **Ids cannot clash.** Proposed ids use the `-X` range (`REQ-X001`, `CMP-X001`), offset past
     any existing `-X` id (`first_req`/`first_cmp` passed to `llm/prose.py`).
  3. The LLM cache lives in a workspace `.ad2v` (default `<repo>/.ad2v/bootstrap.ad2v`), so a
     re-run is free and the fake provider can replay it.
  4. P6.1 builds and tests this with the `fake` provider only. No real model was called.

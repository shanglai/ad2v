# ADR-0071: `ad2v init`: deterministic onboarding of an existing repository

- Status: accepted (P9)
- Context: zero-config `extract` is conservative by design (ADR-0047): it only looks in well-known
  spec folders, finds one fallback container when there is no top-level project manifest, and
  cannot know a route prefix held in a settings object. On a typical brownfield repository the
  first map was therefore thin: route prefixes were lost (endpoints `missing`, routes `orphan`), test
  names with team prefixes did not link, and services shared one container. Each fix needed a
  manifest key the user had to discover in the docs.

## Decisions

1. **`ad2v init --repo <path>`** scans without executing anything and prints a report followed by
   a proposed `ad2v.yaml`. The report covers:
   - spec folders, found by name and by content, each with a score and the evidence (files per
     format);
   - the format of each spec file, and the prose files no preset reads (candidates for
     `ad2v specs bootstrap`);
   - spec id and non-functional prefixes;
   - containers from project manifests at depth ≤ 3, with their language and whether an active
     extractor reads it;
   - vendored or generated folders, with how many code files each drops;
   - SQL files, with a warning when an exclude would drop them;
   - IaC (reported only, until P10);
   - JUnit files or a pytest configuration;
   - route prefixes the Python extractor cannot resolve. The extractor keeps them in
     `unresolved_prefix_exprs` (run state only, never in the graph).
2. **100% deterministic**, with no LLM. The same output across runs and for LF vs CRLF+BOM: keys
   are sorted, comments are fixed, there is no timestamp and all paths are relative. Strings are
   quoted as JSON, so the YAML round-trips exactly.
3. **Nothing is guessed.** An unknown route prefix is proposed as `pairing.path_constants:
   {"settings.API_PREFIX": ""}`. An empty value is ignored by the manifest loader, so the
   proposal is valid as written. The human fills in the value, and `ad2v init --check` lists it
   until then.
4. **Writes only with `--write <file>`.** It refuses to overwrite without `--force`. The report
   suggests a file outside the repository, so trying ad2v leaves the repository untouched.
   `--format json` prints findings and proposal for tools. `--check <manifest>` compares an
   existing manifest with what `init` would propose (spec folders, containers, stale excludes,
   prefixes, empty path constants) and exits 1 on differences.
5. **Zero-config `extract` also gains `sdd/` and `docs/sdd/`** as auto-detected spec folders, under
   the same rule: only when a reader recognizes a file there. A folder of prose alone is not a spec
   root.

## Measured on `fixtures/brownfield-es`

- Zero-config: 1 command, about 0.75 s. The three endpoints show as `missing`, five code nodes as
  `orphan`, and 1 spec item as `implemented`.
- With `init`: `init --write`, one edit (`/api/v1`) and `extract --manifest`, so 2 commands plus
  1 edit, about 1.3 s of tool time. The endpoints and routes show as `implemented`, there are 0
  orphans, RF-002/003 link through their tests, and the backend and frontend are separate
  containers.

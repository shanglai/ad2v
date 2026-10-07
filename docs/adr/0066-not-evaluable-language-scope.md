# ADR-0066: `not_evaluable`: specified and built in a language ad2v cannot read (format v0.6)

- Status: accepted (P8.1)
- Context: ad2v only evaluates code that an active extractor reads (today: Python). In a mixed
  repository (a Python API and a TypeScript client, say), the TypeScript files were simply not
  walked. A requirement implemented there therefore showed as `specified` (or `missing`), and a
  container holding only TypeScript showed as `orphan`. Both are false: the work exists, ad2v just
  cannot judge it. The owner asked for a legend or category for "specified and developed, but not
  evaluable because the language is outside the comprehended scope". The first mixed repository
  reviewed for dogfooding (Java services, P8) made the gap concrete.

## Decisions

1. **A new status, `not_evaluable`**, for links and nodes. Meaning: there is code for this, in a
   language no active extractor reads; ad2v neither confirms nor contradicts the spec there. It is
   not a problem status (not in the viewer's "problems" set, not a `diff` regression).
2. **Precedence** (format spec §6.4): `drift > needs_review > missing > orphan > stale > verified >
   implemented > not_evaluable > specified > none`. Any evaluated evidence wins: a component with a
   Python module and a TypeScript module is judged on the Python. `not_evaluable` beats
   `specified`: "built where we cannot look" says more than "nothing found".
3. **Language-scope inventory (core, `ad2v.scope`).** Files whose extension is in the scope table
   (TypeScript, JavaScript, Vue, Svelte, Java, Kotlin, Scala, Go, Rust, C#, F#, Ruby, PHP, Swift,
   Objective-C, Dart, Elixir, C, C++; `.d.ts` excluded), that no active plug-in claims, outside the
   excludes and spec roots, become `module` nodes with `attrs = {extracted: false, language}`. Their
   content is an epoch input (`repo_tree_hash`). The table is stored in the epoch rules under
   `scope` (with a version), so changing it changes `rules_hash`.
4. **Annotations in any comment syntax.** `ad2v: REQ-001` after `//`, `#`, `/*`, `*`, `--` or `<!--`
   becomes a spec reference of that module, like a Python annotation (`spec_ref_sources:
   {REQ-001: [comment]}`). Fingerprints (`@1a2b3c4d`) are accepted and ignored for these files.
   Strings are not comments and are ignored.
5. **Pairing.** A link that would be `implemented` and whose code side is an unextracted module, or
   a container/component whose modules are all unextracted, becomes `not_evaluable` with evidence
   `{kind: language_out_of_scope, languages: [...]}`. `verified` (passing tests) stays `verified`,
   and `needs_review` / `drift` stay as they are. Unextracted code with no spec link gets its own
   `not_evaluable` link instead of `orphan`, whatever the orphan policy.
6. **Containers.** `package.json`, `go.mod`, `Cargo.toml`, `pom.xml` and `build.gradle(.kts)` now
   mark containers next to `pyproject.toml`, `setup.py` and `Dockerfile`, so a TypeScript or Java
   service lands in its own container. This can change container inference for repositories with
   such directories; all fixtures are unchanged.
7. **When an extractor for the language is enabled**, its plug-in claims those files and the
   status disappears by itself (tested with a toy TypeScript plug-in).
8. **Format v0.6.** SQLite cannot alter a CHECK constraint, so `links.status` and
   `node_status.status` are rebuilt (create, copy, drop, rename, indexes, the view that reads them)
   when a v0.5 file is opened for writing; v0.4 files go 0.4 → 0.5 → 0.6. Readers accept 0.4–0.6.
   Normative rows are copied unchanged.
9. **Presentation.** Style signature: dotted, hollow, thin, with a `∅` badge (`scope_badge`),
   colors `status.not_evaluable` and `badge.scope` (olive-sage, distinct from the teal AI badge).
   The viewer gets a **Legend** (toolbar) that explains every status and its signature, and a node
   card for a `not_evaluable` node says which language and what to do. The CLI summary prints the
   unextracted languages and file counts; `ad2v status --status not_evaluable` lists them; MCP
   retrieval maps "unevaluated", "evaluable", "unsupported" to the status.

## Not done (later)

- Spec items mapped (`pairing.components`) to a container that is all unextracted inherit nothing
  beyond the component link: their requirements stay `specified` unless annotated.
- Test names in unextracted test files (`it("REQ-001 …")`) are not read; only `ad2v:` comments.
- History of a file whose only change is the scope table: a `rules` epoch, like any rules change.

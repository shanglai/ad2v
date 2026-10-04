# ADR-0047: Where specs are found

- Status: accepted (P6.1)
- Context: P1–P6 needed `--spec <dir>`. Real repositories keep specs in `specs/`, `docs/specs/`,
  `.kiro/specs/`, or a root `openapi.yaml`, and a repository can have several.
- Decisions:
  1. **Order, first match wins:**
     1. `--spec` on the CLI, repeatable. Given but absent paths are an error. There is no
        fallback, so an explicit choice is never silently replaced.
     2. `spec_root` in `ad2v.yaml`, a string or a list. A missing path is a `SpecRootError`.
     3. Auto-detection, unless `--no-spec-autodetect`: the first of `specs/`, `spec/`,
        `docs/specs/`, `.kiro/specs/` that contains a recognized file (ad2v Markdown, a preset
        match, OpenAPI, Gherkin), plus a root `openapi.{yaml,yml,json}`.
  2. **Printed.** `ad2v extract` and every `ad2v history` line print the resolved roots and their
     source, for example `spec roots (auto-detected): specs/`.
  3. **Hashed.** The effective roots (and the preset choices, ADR-0048) are part of
     `config.config_json`, so `config_hash` changes when discovery changes the input.
  4. **Code under a spec root is not code.** Spec roots are excluded from code extraction. This
     matters for `project/` with `project/specs/`: the specs are found with no flags and are not
     scanned as Python.
  5. **Several roots.** Spec-node paths are prefixed by their root label, so two roots that both
     contain `requirements.md` do not collide.
  6. History resolves roots per commit, so a repository that adds `specs/` later is handled.

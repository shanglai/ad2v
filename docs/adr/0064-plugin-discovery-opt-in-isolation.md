# ADR-0064: Plug-in discovery, opt-in, trust and isolation

- Status: accepted (P8)
- Context: third-party plug-ins are Python code that runs in-process with the user's privileges.
  A package that merely happens to be installed (a transitive dependency, a typo-squat) must not
  inject an extractor into a run. A buggy plug-in must not abort or silently corrupt a run.

## Decisions

1. **Discovery** uses stdlib `importlib.metadata.entry_points` for the groups `ad2v.extractors`
   and `ad2v.frameworks`. The entry point loads to a zero-argument callable (class or factory)
   returning the plug-in. The built-ins are registered as entry points in `pyproject.toml` *and*
   in an internal registry, so source checkouts and stale editable installs still work; the
   built-in's own entry point is skipped (same distribution), a third-party entry point that
   reuses a built-in name is reported ("shadows a built-in") and never loaded, and a name
   registered by two distributions is reported and refused.
2. **Opt-in.** Only the built-ins are active by default. Others are enabled per repository in
   `ad2v.yaml` (`extractors: {enabled: [name, …]}`) or per run with `--extractor <name>`
   (repeatable, on `extract` and `history`). Enabling a name that is not installed is an error.
   `extractors.*` is excluded from `config_hash`: the plug-in identity already enters the epoch
   through the rules (ADR-0065), so enabling a plug-in is a `rules` change, not `mixed`.
3. **Disabled plug-ins are never imported** by `extract` / `history`. `ad2v extractors list` shows
   every discovered plug-in (kind, name, version, api_version, distribution, state) but imports
   only built-ins and enabled ones; `--inspect` imports the rest to show their version and api.
4. **Isolation.** Each extractor writes into its own graph; the core merges them in name order
   (first node wins, spec refs unioned, edges merged like `add_edge`). A third-party extractor
   or pack hook runs in a daemon thread with a timeout (`--plugin-timeout`, default 600 s). If it
   raises or times out, its output is discarded (a pack hook runs on a copy of the extractor's
   graph), the failure is printed and recorded in `epochs.attrs.plugin_failures`, and the run
   continues. `--strict` makes any plug-in failure fatal. The built-ins are part of the core and
   always fail the run (as before P8). A timed-out thread cannot be killed in-process; it keeps
   running until the process exits, and its results are ignored.
5. **The file accessor is a contract, not a sandbox.** Files are pre-read by the core; a plug-in
   that opens files itself, uses the network or spawns processes is not stopped at run time. The
   conformance kit detects file opens (audit hook) and accessor misuse; documentation states that
   plug-ins are trusted code (docs/plugins.md, docs/security.md).
6. **Output.** `extract` prints one line per active plug-in with its version, api_version, source
   (built-in / enabled) and own rules hash, then any skipped plug-in; `history` prints them once.

- Tested (tests/test_plugins.py): inactive until enabled (manifest and CLI); unknown name; a
  failing extractor and a failing pack hook are skipped and recorded, and fatal with `strict`; a
  hanging plug-in times out; shadowing, an unsupported api_version and undeclared IR kinds are
  rejected; `extractors list` and `extractor check` from the CLI.

# ADR-0063: The extractor plug-in API (api_version 1.0) and its compatibility policy

- Status: accepted (P8)
- Context: the project will be split by access. Core, the Python extractor, the TypeScript extractor
  (P9), the viewer and the MCP server stay public (Apache-2.0); a Java extractor and an "enterprise
  pack" (framework detection, audit evidence) will live in private repositories. That only works if
  language extractors and framework detectors are plug-ins behind a stable public API, so private
  code never forks this repo. Until P8 the pipeline called `PythonExtractor` directly and the
  framework recognizers were sections of `python.yaml`.

## Decisions

1. **One public module, `ad2v.api`.** It is the only import surface for plug-ins. It re-exports
   the existing internal model instead of inventing a parallel one: `Graph`, `Node`, `Edge`,
   `UnresolvedRef`, `CodeFacts`, `Event`, `Layout`, `SourceFile`, `Config`, `NODE_KINDS`,
   `EDGE_KINDS`, `node_id()`, `content_hash()`. Everything else in `ad2v.*` is internal.

2. **`Extractor`** (entry-point group `ad2v.extractors`):

   ```python
   class Extractor(Protocol):
       api_version: str  # "1.0"
       name: str  # [a-z][a-z0-9-]*, unique
       version: str  # enters the epoch identity and the parse-cache key
       languages: tuple[str, ...]
       file_patterns: tuple[str, ...]  # globs on the file name or repo-relative path
       rules_files: tuple[Path, ...]  # YAML; canonical hash enters the epoch identity
       node_kinds: frozenset[str]  # besides system/container/component (Layout)
       edge_kinds: frozenset[str]  # besides contains

       def extract(self, ctx: ExtractContext) -> ExtractOutput: ...
   ```

   `ExtractContext` gives `graph` (an empty graph holding the system node), `layout` (files to
   containers and components), `files` (a read-only `FileAccessor` over exactly the claimed files,
   pre-read and normalized), `config`, `rules` (effective) and `cache` (earlier parse-cache
   payloads). Nodes, edges, routes and other ports, jobs, datastores, risky behaviors and schema
   digests are nodes and attrs in `graph`; unresolved references go to `graph.unresolved`.
   `ExtractOutput` returns `facts` (`CodeFacts`: events, wrappers, entry ports, files read),
   `cache_entries`, `timings`, `stats`.

3. **`FrameworkPack`** (group `ad2v.frameworks`): `api_version`, `name`, `version`,
   `attaches_to` (extractor names), `frameworks`, `file_patterns` (extra inputs, e.g. `*.sql`),
   `rules_files` (fragments), `node_kinds`, `edge_kinds`, and `post_extract(ctx:
   FrameworkContext)`. A pack contributes recognizers in two ways: **rules fragments**, merged into
   the attached extractor's rules with *pack merge* (mappings merge, lists are unioned base-first
   then packs in name order, scalars replace), and an optional **hook** that runs on the
   extractor's graph after it ran (with the extractor's files plus the pack's own).

4. **Built-ins are plug-ins.** `python` (the tree-sitter extractor, version 1.0.0, rules
   `python.yaml`) and `python-frameworks` (version 1.0.0; FastAPI, Flask, Starlette, Celery,
   APScheduler, `schedule`, Click, Typer, MCP tool registration as the fragment
   `python-frameworks.yaml`; SQLAlchemy / SQL DDL / Pydantic schema digests as its hook). The
   `ports:` section moved verbatim from `python.yaml` to `python-frameworks.yaml`; pack-merging the
   two gives exactly the P7 `python.yaml` (same canonical hash, `40e0c803…`), which a test pins.
   Built-in versions are bumped by hand whenever their output can change for the same inputs (as
   `rules_version` and `LOCAL_EXTRACTOR_VERSION` were before); they are not tied to the ad2v
   package version, so a release that does not touch extraction does not create new epochs.

5. **Versioning and compatibility.**
   - The API follows semver on `MAJOR.MINOR` (`ad2v.api.API_VERSION`, now `1.0`).
   - **Minor** (1.x): additive only: new optional context fields, new optional plug-in attributes
     with defaults, new node/edge kinds, new helpers.
   - **Breaking** (major): removing or renaming anything in `ad2v.api`; changing a signature, the
     meaning of a field, the pack-merge semantics, the file-accessor contract, the identity
     inputs, or making an optional attribute required.
   - **Accepted versions:** the core accepts plug-ins of its own major and of the previous major.
     Within its own major, a plug-in may not declare a newer minor than the core provides. A
     plug-in of the previous major runs with a deprecation note; older majors are rejected.
   - **Deprecation window:** a deprecated element keeps working for at least one minor release and
     until the next major; deprecations are listed in the changelog and `docs/plugins.md`.
   - The handshake runs at load time (`plugins.check_plugin`) and in the conformance kit.

6. **Conformance kit** `ad2v.testing.conformance.check(name, fixture)` (plain functions; CLI
   `ad2v extractor check <name> --fixture <dir> [--json]`): api handshake, runs clean,
   determinism (two runs and a CRLF+BOM copy), id stability under an unrelated insertion (blank
   lines prepended to each claimed file plus a new empty file), schema (`validate` on a real
   extract), file access (an audit hook on `open` while the plug-in's code runs, plus accessor
   violations), side effects (network, subprocess or file write while the plug-in runs, audit
   hook), declared vs emitted kinds. Machine-readable result; no absolute paths in it.

## What did not fit cleanly (reported, not changed in P8)

- `python.yaml` still holds language-agnostic sections (`severity:`, `retrieval:`), because the
  epoch rules keep the P7 top-level layout. They belong to the core; split them before a second
  real extractor (P9) needs its own severity input.
- Framework recognition inside the Python extractor is parameterized by rules; a pack can add
  constructors, decorators, methods and settings bases, but cannot add a new recognition
  *algorithm* that needs the syntax tree (the hook sees the finished graph and file text, not
  tree-sitter nodes). Click group resolution, Celery beat dictionaries and Starlette route lists
  remain code in `python.py`.
- The schema-digest hook re-parses Python with `ast` (it did so in P7 too).
- `CodeFacts.events` and `wrappers` are Python-shaped (workflow steps derived from calls); other
  extractors may return empty events, in which case no code workflows are traced for them.
- Cross-extractor references (a routes file naming a Python handler) can only be expressed as
  computed node ids; the core does not resolve them.

# Writing ad2v plug-ins: extractors and framework packs

ad2v reads code through **language extractors** and recognizes frameworks through **framework
packs**. Both are plug-ins behind a stable public API (`ad2v.api`, api_version **1.0**), so they
can live in their own packages and repositories. The built-in Python extractor (`python`) and the
built-in Python framework pack (`python-frameworks`) use the same API.

Decisions: ADR-0063 (API and compatibility), ADR-0064 (discovery, opt-in, isolation), ADR-0065
(identity in the epoch). Security model: `docs/security.md` §6.

## 1. Trust model: plug-ins are trusted code

A plug-in runs **in-process with your privileges**. ad2v does not sandbox it. Therefore:

- Only the built-ins are active by default. Installing a package never activates it.
- You enable a plug-in per repository in `ad2v.yaml`, or per run:

  ```yaml
  extractors:
    enabled: [routes-dsl, bottle]
  ```

  ```bash
  ad2v extract --repo . --out x.ad2v --extractor routes-dsl
  ```

- `extract` and `history` never import disabled plug-ins. `ad2v extractors list` shows what is
  installed without importing third-party code (`--inspect` imports it to show versions).
- A third-party plug-in that raises or exceeds `--plugin-timeout` (default 600 s) is reported,
  recorded in the epoch (`plugin_failures`) and skipped; `--strict` makes that fatal.
- Install plug-ins only from sources you trust, as you would any Python package.

## 2. Registering a plug-in

```toml
# your pyproject.toml
[project.entry-points."ad2v.extractors"]
routes-dsl = "ad2v_routes_dsl:RoutesDslExtractor"

[project.entry-points."ad2v.frameworks"]
bottle = "ad2v_bottle_pack:BottlePack"
```

The entry point name must equal the plug-in's `name` (`[a-z][a-z0-9-]*`). A name already used by a
built-in, or by another installed distribution, is refused.

## 3. The interfaces

Import only from `ad2v.api`.

```python
class Extractor(Protocol):
    api_version: str  # "1.0"
    name: str
    version: str  # bump whenever output can change: it enters the epoch id
    languages: tuple[str, ...]
    file_patterns: tuple[str, ...]  # e.g. ("*.routes",), matched on file name or repo path
    rules_files: tuple[Path, ...]  # YAML; their canonical hash enters the epoch id
    node_kinds: frozenset[str]  # what you emit, besides system/container/component
    edge_kinds: frozenset[str]  # besides contains

    def extract(self, ctx: ExtractContext) -> ExtractOutput: ...


class FrameworkPack(Protocol):
    api_version: str
    name: str
    version: str
    attaches_to: tuple[str, ...]  # extractor names, e.g. ("python",)
    frameworks: tuple[str, ...]
    file_patterns: tuple[str, ...]  # extra inputs your hook reads (e.g. "*.sql"), or ()
    rules_files: tuple[Path, ...]  # fragments merged into the extractor's rules
    node_kinds: frozenset[str]
    edge_kinds: frozenset[str]

    def post_extract(self, ctx: FrameworkContext) -> None: ...
```

`ExtractContext`: `graph` (add `Node`s and edges; it already holds the system node), `layout`
(`container_for(path)`, `parent_for_module(path)`), `files` (a `FileAccessor`: iterate
`SourceFile`s with normalized `text` and `content_hash`; `read_text(path)` for one file; anything
outside the set raises `FileAccessError`), `config`, `rules`, `cache`, `warn(message)`.

`ExtractOutput`: `facts` (`CodeFacts`; fill `files_read`, and `entry_ports` if you emit ports with
handlers), `cache_entries`, `timings`, `stats`.

Rules for a good plug-in (checked by the conformance kit):

- deterministic: no wall clock, randomness, environment or file-system order in the output;
  line endings and BOMs must not matter (the accessor already normalizes them);
- node ids come from `(side, kind, qualified_name)`: never put line numbers in a qualified name;
- read files only through `ctx.files`; no network, no subprocesses, no writes;
- emit only the kinds you declare; use the IR kinds (`ad2v.api.NODE_KINDS`, `EDGE_KINDS`).

To make routes pair with OpenAPI / Markdown endpoint specs, emit `http_route` nodes named
`"<METHOD> <path>"` with qualified name `"http:<container>:<METHOD> <path>"`, parent = the
container, and `attrs` `{method, path, framework, handler}`, plus an `exposes` edge from the
container (see the example).

## 4. Framework packs for the built-in Python extractor

The Python extractor reads its recognizers from its rules, so a pack contributes recognizers as a
rules **fragment**: mappings merge, lists are unioned (built-in items first, then packs in name
order), scalars replace. The recognizer vocabulary (from `python-frameworks.yaml`):

| key | meaning |
|---|---|
| `ports.http.app_constructors` | callables whose result is an app/router (FastAPI, Flask, Starlette, …) |
| `ports.http.method_decorators` / `route_decorators` | `@app.get(...)` / `@app.route(...)` |
| `ports.http.include_methods`, `prefix_kwargs` | router inclusion and prefixes |
| `ports.http.add_route_methods`, `route_list_constructors`, `route_constructors`, `mount_constructors`, `mount_methods` | imperative and list-style registration |
| `ports.http.settings_bases` | classes whose literal defaults the opt-in settings resolver reads |
| `ports.mcp.server_constructors`, `tool_decorators` | MCP tool registration |
| `ports.cli.typer_constructors`, `typer_decorators`, `click_decorators`, `click_group_decorators` | CLIs |
| `ports.events` | subscriber callbacks (`constructor`, `method`, `callback_kwarg`, …) |
| `ports.entry_points.celery` / `apscheduler` / `schedule` | jobs and schedulers |
| `resources.<library>` | datastore / queue / external service / LLM client libraries (in `python.yaml`) |

Example (`examples/plugins/bottle-framework-pack/src/ad2v_bottle_pack/bottle.yaml`):

```yaml
ports:
  http:
    app_constructors: [bottle.Bottle]
```

A pack may also define a `post_extract` hook; it runs after the extractor, on its graph, and may
add nodes, edges and attrs (the built-in pack attaches schema digests this way). A pack cannot add
new syntax-tree algorithms to the Python extractor in api 1.0 (ADR-0063, "what did not fit").

## 5. Checking a plug-in

```bash
ad2v extractors list
ad2v extractor check routes-dsl --fixture path/to/small-repo --json
```

From Python (no pytest needed):

```python
from pathlib import Path
from ad2v.testing.conformance import check

result = check("routes-dsl", Path("tests/fixture"))
assert result["passed"], result
```

Checks: `api_handshake`, `runs_clean`, `determinism` (two runs, CRLF+BOM copy), `id_stability`
(blank lines prepended to your files plus a new empty file), `schema` (`ad2v validate` of a real
extract), `file_access` (no file opened outside your set while your code runs), `side_effects`
(no network, subprocess or file write while your code runs), `declared_kinds`.

## 6. Compatibility policy (api 1.0)

- `MAJOR.MINOR`. Minor versions only add (optional fields and attributes, kinds, helpers).
- Breaking (new major): removing or renaming anything in `ad2v.api`, changing a signature or the
  meaning of a field, the pack-merge rules, the accessor contract or the identity inputs, or making
  an optional attribute required.
- The core accepts plug-ins of its own major (with a minor not newer than its own) and of the
  previous major (with a deprecation note). Deprecated elements keep working for at least one
  minor release and until the next major.

## 7. Examples

`examples/plugins/` holds two out-of-tree packages: a toy routes-DSL extractor and a Bottle
framework pack. See `examples/plugins/README.md` for install steps.

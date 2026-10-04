"""The public extractor plug-in API (api_version 1.0, ADR-0063).

This module is the only import surface a language extractor or a framework pack needs. Everything
here is covered by the compatibility policy in ADR-0063 (semver on `API_VERSION`; the core accepts
the current and the previous major; deprecations last at least one minor release and are announced
in the changelog). Anything imported from other `ad2v.*` modules is internal and may change.

A plug-in is a plain object (usually a class instance) registered under a Python entry point:

    [project.entry-points."ad2v.extractors"]   # language extractors
    routes-dsl = "my_pkg:RoutesDslExtractor"

    [project.entry-points."ad2v.frameworks"]   # framework packs
    bottle = "my_pkg:BottlePack"

The entry point loads to a zero-argument callable (a class or a factory) that returns the plug-in.
Third-party plug-ins run in-process with full privileges, so they are never active by default: a
repository enables them in `ad2v.yaml` (`extractors: {enabled: [name, ...]}`) or per run with
`--extractor <name>`. Only the built-ins (`python`, `python-frameworks`) are active by default.

Contract (checked by `ad2v.testing.conformance` / `ad2v extractor check`):

- deterministic: the same files, config and rules give the same graph, independent of line
  endings, BOMs, file-system order, wall clock, environment and randomness;
- read-only, and reads repository content only through `ExtractContext.files`;
- node ids come from `node_id(side, kind, qualified_name)` (via `Node`), never from line numbers,
  so an unrelated insertion leaves every existing id unchanged;
- emits only the node and edge kinds it declares (`node_kinds`, `edge_kinds`);
- no network access, no subprocesses, no writes.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ad2v import ids
from ad2v.extract.code.base import CodeFacts, Event, Layout
from ad2v.extract.files import SourceFile
from ad2v.ir import EDGE_KINDS, NODE_KINDS, Edge, Graph, Node, UnresolvedRef
from ad2v.manifest import Config

API_VERSION = "1.0"
EXTRACTOR_GROUP = "ad2v.extractors"
FRAMEWORK_GROUP = "ad2v.frameworks"
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")

# Node kinds the core creates for every extractor through `Layout`; they need not be declared.
LAYOUT_NODE_KINDS = frozenset({"system", "container", "component"})
LAYOUT_EDGE_KINDS = frozenset({"contains"})

__all__ = [
    "API_VERSION",
    "EDGE_KINDS",
    "EXTRACTOR_GROUP",
    "FRAMEWORK_GROUP",
    "LAYOUT_EDGE_KINDS",
    "LAYOUT_NODE_KINDS",
    "NODE_KINDS",
    "CodeFacts",
    "Config",
    "Edge",
    "Event",
    "ExtractContext",
    "ExtractOutput",
    "Extractor",
    "FileAccessError",
    "FileAccessor",
    "FrameworkContext",
    "FrameworkPack",
    "Graph",
    "Layout",
    "Node",
    "PluginError",
    "SourceFile",
    "UnresolvedRef",
    "api_compatible",
    "content_hash",
    "node_id",
]


class PluginError(RuntimeError):
    """A plug-in is invalid, incompatible, failed or timed out."""


class FileAccessError(PermissionError):
    """A plug-in asked for a file outside the file set it was given."""


def node_id(side: str, kind: str, qualified_name: str) -> str:
    """The stable node id (format spec §3.6). `Node` computes it; exposed for cross-references."""
    return ids.node_id(side, kind, qualified_name)


def content_hash(text: str) -> str:
    """content_hash of normalized text (LF, no BOM), as the core computes it for files."""
    return ids.content_hash(text)


def parse_api_version(v: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d+)\.(\d+)", str(v))
    if not m:
        raise PluginError(f"api_version must be 'MAJOR.MINOR', got {v!r}")
    return int(m.group(1)), int(m.group(2))


def api_compatible(plugin_api: str, core_api: str = API_VERSION) -> tuple[bool, str]:
    """ADR-0063: the core accepts its own major and the previous one; within the core's major, a
    plug-in may not require a newer minor than the core has."""
    try:
        pmaj, pmin = parse_api_version(plugin_api)
        cmaj, cmin = parse_api_version(core_api)
    except PluginError as e:
        return False, str(e)
    if pmaj == cmaj:
        if pmin > cmin:
            return False, f"plug-in needs api {plugin_api}; this ad2v provides {core_api}"
        return True, "ok"
    if pmaj == cmaj - 1:
        return True, f"previous major {pmaj}.x (supported, deprecated)"
    accepted = f"{cmaj}.x, {cmaj - 1}.x"
    return False, f"api {plugin_api} is not supported by this ad2v (api {core_api}; accepts {accepted})"


class FileAccessor:
    """Read-only access to exactly the files a plug-in was given (normalized text: LF, no BOM).

    The core reads the files before the plug-in runs, so a well-behaved plug-in never opens a file
    itself. Asking for a path outside the set raises `FileAccessError` and is recorded in
    `violations` (the conformance kit fails on it). This is a contract, not a sandbox: plug-ins are
    trusted code (docs/security.md).
    """

    def __init__(self, files: list[SourceFile]) -> None:
        self._files = {f.path: f for f in sorted(files, key=lambda f: f.path)}
        self.violations: list[str] = []

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(self._files)

    def __iter__(self) -> Iterator[SourceFile]:
        return iter(self._files.values())

    def __len__(self) -> int:
        return len(self._files)

    def __contains__(self, path: object) -> bool:
        return path in self._files

    def source(self, path: str) -> SourceFile:
        f = self._files.get(path)
        if f is None:
            self.violations.append(path)
            raise FileAccessError(f"{path!r} is not in this plug-in's file set")
        return f

    def read_text(self, path: str) -> str:
        return self.source(path).text

    def content_hash(self, path: str) -> str:
        return self.source(path).content_hash

    def with_patterns(self, patterns: tuple[str, ...]) -> FileAccessor:
        """A narrower accessor: the files whose name or path matches one of `patterns`."""
        from ad2v.plugins import matches

        return FileAccessor([f for f in self if matches(f.path, patterns)])


@dataclass
class ExtractContext:
    """What a language extractor receives.

    graph   an empty `Graph` for this extractor's output (it already holds the system node);
            add nodes with `graph.add_node(Node(...))` and edges with `graph.add_edge(...)`;
            dangling spec ids and other unresolved references go to `graph.unresolved`.
    layout  maps a repository-relative file path to its container and component nodes:
            `layout.container_for(path)`, `layout.parent_for_module(path)` (format spec §4).
    files   the files matching the extractor's `file_patterns` (minus excludes and spec roots).
    config  the parsed `ad2v.yaml` (read-only by convention).
    rules   the extractor's effective rules: its own rules files, then the enabled framework
            packs attached to it, then (for the built-in `python` extractor) the manifest overlay.
    cache   the extractor's parse-cache payloads from earlier runs: (path, content_hash) ->
            payload. Return new payloads in `ExtractOutput.cache_entries`.
    """

    graph: Graph
    layout: Layout
    files: FileAccessor
    config: Config
    rules: Mapping[str, Any]
    cache: Mapping[tuple[str, str], Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        self.warnings.append(str(message))


@dataclass
class ExtractOutput:
    """What a language extractor returns besides the nodes and edges it added to `ctx.graph`.

    facts          events (workflow steps), retry/transaction wrappers, entry ports and the files
                   read (`CodeFacts`); an extractor without workflows returns `CodeFacts()` with
                   `files_read` and `entry_ports` filled.
    cache_entries  path -> (content_hash, JSON-serializable payload) for the parse cache.
    timings        named durations in seconds (informative).
    stats          counters such as cache_hits / cache_misses (informative).
    """

    facts: CodeFacts = field(default_factory=CodeFacts)
    cache_entries: dict[str, tuple[str, Any]] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)


@runtime_checkable
class Extractor(Protocol):
    """A language extractor (entry-point group `ad2v.extractors`).

    api_version    the API it was written against ("1.0").
    name           unique, lowercase `[a-z][a-z0-9-]*` (the name used in `extractors.enabled`).
    version        the plug-in's own version; bump it whenever its output can change, because it
                   enters the epoch identity and the parse-cache key.
    languages      language names it handles (informative, shown by `ad2v extractors list`).
    file_patterns  glob patterns matched against the file name or the repository-relative path,
                   e.g. ("*.py",) or ("*.routes",).
    rules_files    YAML files with the extractor's rules (may be empty); their merged canonical
                   hash enters the epoch identity.
    node_kinds     the node kinds it may emit, besides LAYOUT_NODE_KINDS.
    edge_kinds     the edge kinds it may emit, besides LAYOUT_EDGE_KINDS.
    """

    api_version: str
    name: str
    version: str
    languages: tuple[str, ...]
    file_patterns: tuple[str, ...]
    rules_files: tuple[Path, ...]
    node_kinds: frozenset[str]
    edge_kinds: frozenset[str]

    def extract(self, ctx: ExtractContext) -> ExtractOutput: ...


@dataclass
class FrameworkContext:
    """What a framework pack's `post_extract` hook receives, after its extractor ran.

    graph    the attached extractor's output graph (the pack may add nodes, edges and attrs).
    files    the extractor's files plus the files matching the pack's own `file_patterns`.
    rules    the extractor's effective rules (including every enabled pack's fragments).
    facts    the extractor's `CodeFacts` (read-only by convention).
    """

    extractor: str
    graph: Graph
    files: FileAccessor
    config: Config
    rules: Mapping[str, Any]
    facts: CodeFacts
    warnings: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        self.warnings.append(str(message))


@runtime_checkable
class FrameworkPack(Protocol):
    """A framework pack (entry-point group `ad2v.frameworks`).

    attaches_to    the extractor names it extends, e.g. ("python",).
    frameworks     the frameworks it recognizes (informative).
    file_patterns  extra input files its hook reads (e.g. ("*.sql",)); they become epoch inputs.
    rules_files    rules fragments merged into the attached extractor's rules: mappings merge key
                   by key, lists are unioned (base first, then packs in name order), scalars are
                   replaced. This is how recognizers are contributed to an extractor that reads
                   them from its rules (the built-in Python extractor's recognizer vocabulary is
                   documented in docs/plugins.md).
    node_kinds / edge_kinds   what `post_extract` may add.
    post_extract   optional hook; packs that only contribute rules define it as a no-op.
    """

    api_version: str
    name: str
    version: str
    attaches_to: tuple[str, ...]
    frameworks: tuple[str, ...]
    file_patterns: tuple[str, ...]
    rules_files: tuple[Path, ...]
    node_kinds: frozenset[str]
    edge_kinds: frozenset[str]

    def post_extract(self, ctx: FrameworkContext) -> None: ...

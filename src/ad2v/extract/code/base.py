"""Language-agnostic code extraction: plugin protocol, containers and components."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ad2v import ids, ir
from ad2v.extract.files import SourceFile
from ad2v.manifest import Config, ContainerDecl

CONTAINER_MARKERS = ("pyproject.toml", "setup.py", "Dockerfile")


@dataclass(frozen=True)
class Event:
    """One step-worthy thing a function does, in source order (input to static workflows).

    kind: "call" (targets are callee node ids; several targets = parallel) or "touch"
    (targets is one resource node id). behaviors: emitted behavior node ids that lexically
    enclose the event, outermost first.
    """

    kind: str
    targets: tuple[str, ...]
    behaviors: tuple[str, ...]
    line: int


@dataclass
class CodeFacts:
    """What a code extractor returns besides the nodes/edges it adds to the graph."""

    events: dict[str, list[Event]] = field(default_factory=dict)
    wrappers: dict[str, list[str]] = field(default_factory=dict)  # fn id -> emitted retry/transaction ids
    entry_ports: list[tuple[str, str]] = field(default_factory=list)  # (port id, handler node id)
    files_read: dict[str, str] = field(default_factory=dict)  # path -> content_hash


class Layout:
    """Maps repository files to containers and components (format spec §4)."""

    def __init__(self, graph: ir.Graph, config: Config, repo: Path, system_name: str) -> None:
        self.graph = graph
        self.config = config
        self.repo = Path(repo)
        self.system = graph.add_node(
            ir.Node("code", "system", system_name, system_name, content_hash="", attrs={})
        )
        self.system.content_hash = ids.attrs_hash("system", system_name, {})
        self.decls = list(config.containers) or self._infer()
        self._containers: dict[str, ir.Node] = {}

    def _infer(self) -> list[ContainerDecl]:
        out = []
        for child in sorted(self.repo.iterdir(), key=lambda p: p.name):
            if not child.is_dir() or child.is_symlink() or child.name.startswith("."):
                continue
            if child.name in self.config.exclude:
                continue
            if any((child / m).is_file() for m in CONTAINER_MARKERS):
                out.append(ContainerDecl(child.name, (child.name,), kind="service", declared=False))
        return out

    def container_decl(self, rel_path: str) -> tuple[ContainerDecl, str]:
        """(container, matched root path) for a file; longest prefix wins."""
        best: tuple[int, ContainerDecl, str] | None = None
        for d in self.decls:
            for p in d.paths:
                if p == "." or rel_path == p or rel_path.startswith(p + "/"):
                    score = 0 if p == "." else len(p)
                    if best is None or score > best[0] or (score == best[0] and d.name < best[1].name):
                        best = (score, d, p)
        if best is None:
            fallback = ContainerDecl(self.system.name, (".",), kind="service", declared=False)
            return fallback, "."
        return best[1], best[2]

    def container_node(self, decl: ContainerDecl) -> ir.Node:
        if decl.name in self._containers:
            return self._containers[decl.name]
        attrs = {
            "container_kind": decl.kind,
            "declared": decl.declared,
            "paths": list(decl.paths),
            "replicas": decl.replicas,
        }
        node = self.graph.add_node(
            ir.Node(
                "code",
                "container",
                decl.name,
                f"container:{decl.name}",
                parent_id=self.system.id,
                attrs=attrs,
                content_hash=ids.attrs_hash("container", decl.name, attrs),
            )
        )
        self._containers[decl.name] = node
        return node

    def container_for(self, rel_path: str) -> ir.Node:
        return self.container_node(self.container_decl(rel_path)[0])

    def parent_for_module(self, rel_path: str) -> str:
        """Create component nodes for the directories between the container root and the file."""
        decl, root = self.container_decl(rel_path)
        parent = self.container_node(decl)
        parts = rel_path.split("/")[:-1]
        root_parts = [] if root == "." else root.split("/")
        for i in range(len(root_parts), len(parts)):
            d = "/".join(parts[: i + 1])
            name = parts[i]
            attrs: dict[str, object] = {}
            parent = self.graph.add_node(
                ir.Node(
                    "code",
                    "component",
                    name,
                    d,
                    parent_id=parent.id,
                    path=d,
                    attrs=attrs,
                    content_hash=ids.attrs_hash("component", name, attrs),
                )
            )
        return parent.id


class CodeExtractor(Protocol):
    """Plugin interface for a language. Implementations must be read-only and deterministic."""

    language: str
    suffixes: tuple[str, ...]

    def extract(self, graph: ir.Graph, layout: Layout, files: list[SourceFile]) -> CodeFacts:
        """Add nodes/edges for `files` (sorted) to `graph`; return events and entry ports."""
        ...

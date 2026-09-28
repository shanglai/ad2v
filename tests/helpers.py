from __future__ import annotations

import textwrap
from pathlib import Path

from ad2v import ids, ir
from ad2v.extract import files as filewalk
from ad2v.extract.code.base import CodeFacts, Layout
from ad2v.extract.code.python import PythonExtractor
from ad2v.manifest import Config
from ad2v.manifest import load as load_manifest

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "payments-recon"


def write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8", newline="\n")


def run_code(
    tmp_path: Path, files: dict[str, str], config: Config | None = None
) -> tuple[ir.Graph, CodeFacts]:
    write_tree(tmp_path, files)
    cfg = config or load_manifest(tmp_path)
    g = ir.Graph()
    layout = Layout(g, cfg, tmp_path, cfg.system_name or "sys")
    ex = PythonExtractor(cfg)
    rel = filewalk.walk(tmp_path, cfg.exclude, (".py",))
    facts = ex.extract(g, layout, filewalk.load(tmp_path, rel))
    return g, facts


def node(g: ir.Graph, kind: str, qname: str) -> ir.Node:
    nid = ids.node_id(ir.side_of(kind), kind, qname)
    have = sorted(n.qualified_name for n in g.nodes.values() if n.kind == kind)
    assert nid in g.nodes, f"missing {kind} {qname}; have: {have}"
    return g.nodes[nid]


def qnames(g: ir.Graph, kind: str) -> list[str]:
    return sorted(n.qualified_name for n in g.nodes.values() if n.kind == kind)


def edges(g: ir.Graph, kind: str) -> set[tuple[str, str]]:
    return {(g.nodes[s].qualified_name, g.nodes[d].qualified_name) for (s, k, d) in g.edges if k == kind}

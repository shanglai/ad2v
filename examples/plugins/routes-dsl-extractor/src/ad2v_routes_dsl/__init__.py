"""An example out-of-tree ad2v extractor for a toy "routes DSL".

A `*.routes` file lists HTTP routes, one per line:

    # orders service
    GET    /v1/orders        list_orders     # ad2v: REQ-001
    POST   /v1/orders        create_order

Each route becomes an `http_route` node in the file's container (so it pairs with OpenAPI or
Markdown endpoint specs like a Python route would), the file becomes a `module` node, and
`# ad2v: <spec id>` comments become spec references. It imports nothing from ad2v but `ad2v.api`.
"""

from __future__ import annotations

import re
from pathlib import Path

from ad2v.api import (
    API_VERSION,
    CodeFacts,
    ExtractContext,
    ExtractOutput,
    Node,
    content_hash,
)

__version__ = "0.1.0"

LINE_RE = re.compile(r"^\s*([A-Za-z]+)\s+(/\S*)\s+([A-Za-z_][\w.]*)\s*(?:#\s*ad2v:\s*(.+))?$")
SPEC_ID_RE = re.compile(r"[A-Z][A-Z0-9]*-[0-9]+")


class RoutesDslExtractor:
    api_version = API_VERSION
    name = "routes-dsl"
    version = __version__
    languages = ("routes-dsl",)
    file_patterns = ("*.routes",)
    rules_files = (Path(__file__).resolve().parent / "routes-dsl.yaml",)
    node_kinds = frozenset({"module", "http_route"})
    edge_kinds = frozenset({"exposes"})

    def extract(self, ctx: ExtractContext) -> ExtractOutput:
        methods = {m.upper() for m in ctx.rules.get("methods", [])}
        facts = CodeFacts()
        graph, layout = ctx.graph, ctx.layout
        for f in ctx.files:  # sorted by path
            facts.files_read[f.path] = f.content_hash
            container = layout.container_for(f.path)
            lines = f.text.split("\n")
            graph.add_node(
                Node(
                    "code",
                    "module",
                    f.path.rsplit("/", 1)[-1],
                    f.path,
                    parent_id=layout.parent_for_module(f.path),
                    path=f.path,
                    span_start_line=1,
                    span_end_line=len(lines),
                    content_hash=f.content_hash,
                    attrs={"language": "routes-dsl"},
                )
            )
            for i, raw in enumerate(lines, start=1):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                m = LINE_RE.match(line)
                if not m or m.group(1).upper() not in methods:
                    ctx.warn(f"{f.path}:{i}: not a route line")
                    continue
                method, path, handler = m.group(1).upper(), m.group(2), m.group(3)
                attrs = {"framework": "routes-dsl", "handler": handler, "method": method, "path": path}
                node = graph.add_node(
                    Node(
                        "code",
                        "http_route",
                        f"{method} {path}",
                        f"http:{container.name}:{method} {path}",
                        parent_id=container.id,
                        path=f.path,
                        span_start_line=i,
                        span_end_line=i,
                        attrs=attrs,
                        content_hash=content_hash(f"{method} {path} {handler}"),
                        spec_ref=sorted(set(SPEC_ID_RE.findall(m.group(4) or ""))),
                    )
                )
                graph.add_edge(container.id, node.id, "exposes")
        return ExtractOutput(facts=facts, stats={"files": len(ctx.files)})

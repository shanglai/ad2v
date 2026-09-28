"""Task `summarize`: bottom-up node summaries over containment (format spec §11.6).

- `label` is deterministic (display name + kind); no LLM.
- One call per node returns `card` (≤ 240 chars), `deep` (≤ 1200 chars) and `mentions`.
  Leaves see their code span (capped like the judge slice) and IR digest; parents see their IR
  digest (counts, ports, resources, risky behaviors, status roll-up) and their children's cards.
- The input includes the children's `result_id`s, so a changed leaf re-summarizes only its
  ancestor chain; everything else is a cache hit.
- `mentions` must be node ids that appear in the input; others are dropped and recorded.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ad2v import __version__, ids, ir
from ad2v.llm import fence
from ad2v.llm.context import PORT_KINDS, RESOURCE_KINDS, EpochView
from ad2v.llm.prompts import load as load_prompt
from ad2v.llm.runner import Executor, Job, Result, now

NODE_ID_RE = re.compile(r"\bn_[0-9a-f]{20}\b")
STRUCTURAL = frozenset({"system", "container", "component", "module"})
NO_SOURCE = frozenset({"system", "container", "component"})
LEAF_MAX_LINES = 150

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "card": {"type": "string", "maxLength": 240},
        "deep": {"type": "string", "maxLength": 1200},
        "mentions": {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 40}},
    },
    "required": ["card", "deep", "mentions"],
}


def label(n: ir.Node) -> str:
    return f"{n.name} ({n.kind.replace('_', ' ')})"


def in_scope(view: EpochView, scope: str) -> list[str]:
    g = view.graph
    linked = {lk.code_node_id for lk in view.derived.pairing.links if lk.code_node_id and lk.spec_node_id}
    handlers = {view.handler_of(n).id for n in g.nodes.values() if n.kind in PORT_KINDS}
    out = []
    for nid, n in g.nodes.items():
        if n.side != "code" or n.kind in RESOURCE_KINDS:
            continue
        if (
            scope == "all"
            or n.kind in STRUCTURAL
            or n.kind in PORT_KINDS
            or (n.kind in ir.BEHAVIOR_KINDS and n.attrs.get("risk"))
            or (n.kind == "function" and (nid in linked or nid in handlers))
        ):
            out.append(nid)
    return sorted(out)


def depth(view: EpochView, nid: str) -> int:
    d, cur = 0, view.graph.nodes[nid].parent_id
    while cur is not None:
        d, cur = d + 1, view.graph.nodes[cur].parent_id
    return d


def parent_digest(view: EpochView, n: ir.Node) -> dict[str, Any]:
    g = view.graph
    desc: list[str] = []
    stack = list(view.kids.get(n.id, []))
    while stack:
        c = stack.pop()
        desc.append(c)
        stack.extend(view.kids.get(c, []))
    kinds = Counter(g.nodes[c].kind for c in desc)
    risky = sorted(
        f"{c} {g.nodes[c].qualified_name}: {g.nodes[c].attrs.get('risk')}"
        for c in desc
        if g.nodes[c].attrs.get("risk")
    )[:10]
    ports = sorted(f"{c} {g.nodes[c].qualified_name}" for c in desc if g.nodes[c].kind in PORT_KINDS)[:20]
    res_q = sorted({r for c in [n.id, *desc] for r in view.resources_reached(c)})[:20]
    resources = [f"{view.by_qname.get((q.split(':', 1)[0], q), '?')} {q}" for q in res_q]
    keep = ("method", "path", "handler", "trigger", "command", "risk")
    return {
        "id": n.id,
        "kind": n.kind,
        "qualified_name": n.qualified_name,
        "counts": dict(sorted(kinds.items())),
        "ports": ports,
        "resources": resources,
        "risky_behaviors": risky,
        "status": view.status_of(n.id),
        "status_rollup": dict(sorted(view.derived.pairing.rollup.get(n.id, {}).items())),
        "attrs": {k: n.attrs[k] for k in sorted(n.attrs) if k in keep},
    }


def job(view: EpochView, nid: str, children: list[tuple[str, Result | None]]) -> tuple[Job, set[str]]:
    n = view.graph.nodes[nid]
    target = view.handler_of(n)
    lines = [] if n.kind in NO_SOURCE else view.span_lines(target)
    if len(lines) > LEAF_MAX_LINES:
        lines = lines[:100] + lines[-50:]
    digest = parent_digest(view, n)
    kid_cards = [
        {
            "id": c,
            "qualified_name": view.graph.nodes[c].qualified_name,
            "result_id": r.result_id if r else None,
            "card": (r.output or {}).get("card") if r and r.valid else None,
        }
        for c, r in children
    ]
    label_ = f"ad2v IR digest of {n.kind} {n.qualified_name}"
    parts = [fence.fence("ir", label_, ids.canonical_json(digest))]
    if lines:
        parts.append(fence.fence("code", f"{target.qualified_name} ({target.path})", fence.numbered(lines)))
    callees = sorted(
        f"{e.dst} {view.graph.nodes[e.dst].qualified_name}"
        for e in view.out_edges.get(target.id, [])
        if e.kind == "calls" and e.dst in view.graph.nodes
    )
    if callees:
        parts.append(fence.fence("ir", "direct callees (id, qualified name)", "\n".join(callees[:30])))
    haystack = "\n".join(parts)  # repository-derived only: not the children's LLM cards
    if kid_cards:
        kids_label = "summaries of its children (LLM output, informative)"
        parts.append(fence.fence("children", kids_label, ids.canonical_json(kid_cards)))
    allowed = set(NODE_ID_RE.findall("\n".join(parts)))  # mentions must be ids shown in the input

    def check(out: dict[str, Any]) -> list[dict[str, str]]:
        bad = [m for m in out.get("mentions", []) if m not in allowed]
        if not bad:
            return []
        return [{"code": "invalid_mentions", "message": ", ".join(bad)[:200], "severity": "warning"}]

    prompt = load_prompt("summarize")
    subject = f"{n.qualified_name} [{n.kind}]"
    return Job("summarize", subject, parts, prompt.user, SCHEMA, check, haystack=haystack), allowed


def run(view: EpochView, ex: Executor, scope: str | None = None) -> list[tuple[Any, ...]]:
    scope = scope or view.cfg.summaries_scope
    nodes = in_scope(view, scope)
    wanted = set(nodes)
    results: dict[str, Result | None] = {}
    rows: list[tuple[Any, ...]] = []
    created = now()
    prompt_hash = load_prompt("summarize").prompt_hash
    for nid in sorted(nodes, key=lambda x: (-depth(view, x), x)):  # leaves first
        kids = [(c, results.get(c)) for c in view.kids.get(nid, []) if c in wanted]
        j, allowed = job(view, nid, kids)
        res = ex.call(j)
        results[nid] = res
        n = view.graph.nodes[nid]
        rows.append(
            (view.epoch_id, nid, "label", label(n), "ad2v", __version__, "-", "-", 1.0, created, None)
        )
        if res is None or not res.valid:
            continue
        out = res.output
        mentions = [m for m in out.get("mentions", []) if m in allowed]
        deep = out["deep"] + (f"\n\nmentions: {', '.join(mentions)}" if mentions else "")
        version = model_version(ex, res)
        for length, text in (("card", out["card"]), ("deep", deep)):
            rows.append(
                (
                    view.epoch_id,
                    nid,
                    length,
                    text,
                    ex.provider.model,
                    version,
                    prompt_hash,
                    j.input_hash,
                    1.0,
                    created,
                    res.result_id,
                )
            )
    if ex.mode != "plan":
        view.conn.execute("DELETE FROM summaries WHERE epoch_id = ?", (view.epoch_id,))
        view.conn.executemany("INSERT OR REPLACE INTO summaries VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    return rows


def model_version(ex: Executor, res: Result) -> str:
    row = ex.conn.execute(
        "SELECT model_version FROM llm_results WHERE result_id = ?", (res.result_id,)
    ).fetchone()
    return row[0] if row and row[0] else ex.provider.model

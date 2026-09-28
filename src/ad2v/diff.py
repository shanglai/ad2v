"""Epoch diff (format spec §8.2): what changed between two epochs, deterministic and sorted.

Volatile columns (class V: span lines, edge line lists) are ignored. Node identity across the
two epochs follows lineage (renames) composed along the parent chain. Derived data (statuses,
links, workflows) is materialized in memory for both epochs, so nothing is written.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any

from ad2v import history, ir, materialize, store

SEVERITY_DELTA = 1.0
MD_MAX_LINES = 60
SPEC_ITEMS = frozenset({"requirement", "scenario", "spec_component", "spec_endpoint"})
STATUS_BADNESS = {s: i for i, s in enumerate(ir.STATUS_PRECEDENCE)}  # lower index = worse


def _chain(conn: sqlite3.Connection, frm: str, to: str) -> list[str] | None:
    """Epochs after `frm` up to `to` along parent links, oldest first; None if not an ancestor."""
    out, cur = [], to
    while cur is not None and cur != frm:
        out.append(cur)
        cur = store.get_epoch(conn, cur).parent_epoch_id
    return list(reversed(out)) if cur == frm else None


def lineage_map(conn: sqlite3.Connection, frm: str, to: str) -> tuple[dict[str, str], dict[str, str]]:
    """old id (in `frm`) -> id in `to`, and the method of the last rename hop."""
    chain = _chain(conn, frm, to) or []
    fwd: dict[str, str] = {}
    how: dict[str, str] = {}
    for e in chain:
        step = {o: (n, m) for o, n, m, _ in store.load_lineage(conn, e) if m != "ambiguous"}
        for src in list(fwd):
            if fwd[src] in step:
                fwd[src], how[src] = step[fwd[src]]
        for o, (n, m) in step.items():
            if o not in fwd.values() and o not in fwd:
                fwd[o], how[o] = n, m
    return fwd, how


def _q(g: ir.Graph, nid: str | None) -> str:
    return g.nodes[nid].qualified_name if nid and nid in g.nodes else str(nid)


def diff(conn: sqlite3.Connection, frm: str, to: str) -> dict[str, Any]:
    ga, gb = store.load_graph(conn, frm), store.load_graph(conn, to)
    da, db = materialize.derive(conn, frm), materialize.derive(conn, to)
    fwd, how = lineage_map(conn, frm, to)
    f = lambda a: fwd.get(a, a)  # noqa: E731
    image = {f(a): a for a in ga.nodes}

    # 1. nodes -----------------------------------------------------------------------------
    added = sorted(b for b in gb.nodes if b not in image)
    removed = sorted(a for a in ga.nodes if f(a) not in gb.nodes)
    renamed = sorted(
        ((a, f(a)) for a in ga.nodes if f(a) != a and f(a) in gb.nodes), key=lambda p: (_q(ga, p[0]), p[1])
    )
    modified, moved = [], []
    for b, a in sorted(image.items()):
        if b not in gb.nodes:
            continue
        na, nb = ga.nodes[a], gb.nodes[b]
        attrs_a = {k: v for k, v in na.attrs.items() if not k.startswith("severity")}
        attrs_b = {k: v for k, v in nb.attrs.items() if not k.startswith("severity")}
        if history._fingerprint(na) != history._fingerprint(nb) or attrs_a != attrs_b:
            modified.append(b)
        if f(na.parent_id) != nb.parent_id if na.parent_id else nb.parent_id is not None:
            moved.append(b)

    def per_kind(ids_: list[str], g: ir.Graph) -> dict[str, int]:
        return dict(sorted(Counter(g.nodes[i].kind for i in ids_).items()))

    nodes = {
        "added": [{"kind": gb.nodes[b].kind, "qualified_name": _q(gb, b)} for b in added],
        "removed": [{"kind": ga.nodes[a].kind, "qualified_name": _q(ga, a)} for a in removed],
        "renamed": [
            {"kind": gb.nodes[b].kind, "from": _q(ga, a), "to": _q(gb, b), "method": how.get(a, "")}
            for a, b in renamed
        ],
        "modified": [{"kind": gb.nodes[b].kind, "qualified_name": _q(gb, b)} for b in modified],
        "moved": [{"kind": gb.nodes[b].kind, "qualified_name": _q(gb, b)} for b in moved],
        "counts": {
            "added": per_kind(added, gb),
            "removed": per_kind(removed, ga),
            "renamed": per_kind([b for _, b in renamed], gb),
            "modified": per_kind(modified, gb),
            "moved": per_kind(moved, gb),
        },
    }

    # 2. status transitions -------------------------------------------------------------------
    sa, sb = da.pairing.statuses, db.pairing.statuses
    node_tr = []
    for b, a in sorted(image.items()):
        if b in sb and a in sa and sa[a].status != sb[b].status:
            node_tr.append(
                {
                    "qualified_name": _q(gb, b),
                    "kind": gb.nodes[b].kind,
                    "side": gb.nodes[b].side,
                    "from": sa[a].status,
                    "to": sb[b].status,
                }
            )
    node_tr.sort(key=lambda t: (STATUS_BADNESS.get(t["to"], 99), t["side"], t["qualified_name"]))
    la = {
        (
            f(lk.spec_node_id) if lk.spec_node_id else None,
            f(lk.code_node_id) if lk.code_node_id else None,
            lk.method,
        ): lk
        for lk in da.pairing.links
    }
    link_tr = []
    for lk in sorted(db.pairing.links, key=lambda x: x.link_id):
        old = la.get((lk.spec_node_id, lk.code_node_id, lk.method))
        if old is not None and old.status != lk.status:
            link_tr.append(
                {
                    "spec": _q(gb, lk.spec_node_id),
                    "code": _q(gb, lk.code_node_id),
                    "method": lk.method,
                    "from": old.status,
                    "to": lk.status,
                    "evidence": [e["kind"] for e in lk.evidence if e.get("kind") in HISTORY_KINDS],
                }
            )
    transitions = {
        "nodes": node_tr,
        "links": link_tr,
        "counts": dict(sorted(Counter(f"{t['from']} -> {t['to']}" for t in node_tr).items())),
    }

    # 3. risk ----------------------------------------------------------------------------------
    def risky(g: ir.Graph) -> dict[str, ir.Node]:
        return {n.id: n for n in g.nodes.values() if n.kind in ir.BEHAVIOR_KINDS and n.attrs.get("risk")}

    ra, rb = risky(ga), risky(gb)
    ra_mapped = {f(a): n for a, n in ra.items()}
    new_risks = sorted((b for b in rb if b not in ra_mapped), key=lambda b: (-rb[b].attrs["severity"], b))
    gone = sorted(a for a in ra if f(a) not in rb)
    changes = []
    for b in sorted(rb):
        if b in ra_mapped:
            d = round(rb[b].attrs["severity"] - ra_mapped[b].attrs["severity"], 4)
            if abs(d) >= SEVERITY_DELTA:
                changes.append(
                    {
                        "qualified_name": _q(gb, b),
                        "from": ra_mapped[b].attrs["severity"],
                        "to": rb[b].attrs["severity"],
                        "delta": d,
                    }
                )
    top = sorted(rb.values(), key=lambda n: n.attrs["severity_rank"])[:10]
    risk = {
        "new": [_risk(n) for n in (rb[b] for b in new_risks)],
        "removed": [_risk(ra[a]) for a in gone],
        "severity_changes": sorted(changes, key=lambda c: (-abs(c["delta"]), c["qualified_name"])),
        "top10": [_risk(n) for n in top],
    }

    # 4. spec ----------------------------------------------------------------------------------
    def items(g: ir.Graph) -> dict[str, ir.Node]:
        return {n.id: n for n in g.nodes.values() if n.kind in SPEC_ITEMS}

    spa, spb = items(ga), items(gb)
    spec = {
        "added": sorted(_q(gb, b) for b in spb if b not in image or image[b] not in spa),
        "removed": sorted(_q(ga, a) for a in spa if f(a) not in spb),
        "changed": sorted(
            _q(gb, b)
            for b in spb
            if b in image and image[b] in spa and spa[image[b]].content_hash != spb[b].content_hash
        ),
    }

    # 5. workflows -----------------------------------------------------------------------------
    def wf_key(w: ir.Workflow, mapping: Any) -> tuple[str, str]:
        return (w.side, mapping(w.entry_node_id))

    wa = {wf_key(w, f): w for w in da.workflows}
    wb = {wf_key(w, lambda x: x): w for w in db.workflows}

    def trace(w: ir.Workflow, mapping: Any) -> list[frozenset[str]]:
        return [frozenset(mapping(n) for n in s.node_ids) for s in w.steps]

    workflows = {
        "added": sorted(w.name for k, w in wb.items() if k not in wa),
        "removed": sorted(w.name for k, w in wa.items() if k not in wb),
        "changed": sorted(
            w.name for k, w in wb.items() if k in wa and trace(wa[k], f) != trace(w, lambda x: x)
        ),
    }

    ea, eb = store.get_epoch(conn, frm), store.get_epoch(conn, to)
    worse = [t for t in node_tr if STATUS_BADNESS.get(t["to"], 99) < STATUS_BADNESS.get(t["from"], 99)]
    summary = (
        f"{len(added)} added, {len(removed)} removed, {len(renamed)} renamed,"
        f" {len(modified)} modified nodes; "
        f"{len(node_tr)} status transitions ({len(worse)} worse); {len(new_risks)} new risky behaviors; "
        f"{len(spec['added']) + len(spec['removed']) + len(spec['changed'])} spec items changed; "
        f"{len(workflows['changed'])} workflows changed."
    )
    return {
        "from": {"epoch": frm, "commit": ea.repo_commit, "seq": ea.seq},
        "to": {"epoch": to, "commit": eb.repo_commit, "seq": eb.seq, "change_kind": eb.change_kind},
        "summary": summary,
        "nodes": nodes,
        "status_transitions": transitions,
        "risk": risk,
        "spec": spec,
        "workflows": workflows,
    }


HISTORY_KINDS = frozenset(
    {
        "spec_changed_since",
        "code_changed_unverified",
        "code_changed_since",
        "both_changed",
        "reannotated",
        "fingerprint_mismatch",
        "retested",
        "descendants_changed",
        "callee_renamed",
    }
)


def _risk(n: ir.Node) -> dict[str, Any]:
    return {
        "qualified_name": n.qualified_name,
        "kind": n.kind,
        "risk": n.attrs.get("risk", []),
        "severity": n.attrs.get("severity"),
        "rank": n.attrs.get("severity_rank"),
    }


def _short(e: dict[str, Any]) -> str:
    c = e.get("commit")
    return f"#{e['seq']}" + (f" ({c[:8]})" if c else "")


def _cap(items: list[str], n: int) -> list[str]:
    if len(items) <= n:
        return items
    return [*items[:n], f"- … and {len(items) - n} more"]


def to_markdown(d: dict[str, Any]) -> str:
    """Compact PR-comment markdown, at most MD_MAX_LINES lines."""
    lines = [
        f"### ad2v: epoch {_short(d['from'])} → {_short(d['to'])} ({d['to']['change_kind']})",
        "",
        d["summary"],
    ]
    counts = d["status_transitions"]["counts"]
    if counts:
        lines += ["", "| transition | nodes |", "|---|---|"]
        rows = [f"| `{k}` | {v} |" for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
        lines += rows[:8] + ([f"| … | {len(rows) - 8} more |"] if len(rows) > 8 else [])
    worst = [
        t
        for t in d["status_transitions"]["nodes"]
        if t["to"] in ("drift", "stale", "missing", "orphan", "needs_review")
    ]
    if worst:
        lines += ["", "**Needs attention**"]
        lines += _cap([f"- `{t['qualified_name']}`: {t['from']} → **{t['to']}**" for t in worst], 8)
    risks = d["risk"]["new"] + [
        {**c, "risk": ["severity +" + str(c["delta"])], "severity": c["to"]}
        for c in d["risk"]["severity_changes"]
        if c["delta"] > 0
    ]
    if risks:
        lines += ["", "**New or worsened risks**"]
        risks = sorted(risks, key=lambda r: (-(r["severity"] or 0), r["qualified_name"]))
        lines += _cap(
            [
                f"- `{r['qualified_name']}`: {', '.join(r['risk'])} (severity {r['severity']:g})"
                for r in risks
            ],
            5,
        )
    n = d["nodes"]
    changed_lines = [f"- renamed `{r['from']}` → `{r['to']}` ({r['method']})" for r in n["renamed"]]
    changed_lines += [
        f"- added `{x['qualified_name']}`" for x in n["added"] if x["kind"] not in ("scenario_step",)
    ]
    changed_lines += [f"- removed `{x['qualified_name']}`" for x in n["removed"]]
    if changed_lines:
        lines += ["", "**Code and spec changes**"]
        lines += _cap(changed_lines, 10)
    spec = d["spec"]
    if spec["changed"] or spec["added"] or spec["removed"]:
        lines += [
            "",
            f"Spec items: {len(spec['added'])} added, {len(spec['removed'])} removed, "
            f"{len(spec['changed'])} changed"
            + (f" ({', '.join(spec['changed'][:5])})" if spec["changed"] else ""),
        ]
    lines = lines[: MD_MAX_LINES - 1]
    lines += ["", "<sub>ad2v diff: deterministic, no LLM. Qualified names point into the .ad2v map.</sub>"]
    return "\n".join(lines[:MD_MAX_LINES]) + "\n"


def to_table(d: dict[str, Any]) -> str:
    out = [f"diff {_short(d['from'])} -> {_short(d['to'])} ({d['to']['change_kind']})", d["summary"], ""]
    for section, data in (("nodes", d["nodes"]["counts"]),):
        out.append(f"[{section}]")
        for k, v in data.items():
            if v:
                out.append(f"  {k:9s} " + ", ".join(f"{kind}={c}" for kind, c in v.items()))
    for r in d["nodes"]["renamed"]:
        out.append(f"  renamed   {r['from']} -> {r['to']} ({r['method']})")
    out.append("[status transitions]")
    for t in d["status_transitions"]["nodes"]:
        out.append(f"  {t['from']:>12s} -> {t['to']:<12s} {t['kind']:14s} {t['qualified_name']}")
    for t in d["status_transitions"]["links"]:
        out.append(f"  link {t['from']} -> {t['to']}: {t['spec']} <-> {t['code']} {t['evidence']}")
    out.append("[risk]")
    for r in d["risk"]["new"]:
        out.append(f"  new      {r['severity']:>6g} {r['qualified_name']} {r['risk']}")
    for r in d["risk"]["removed"]:
        out.append(f"  removed  {r['qualified_name']}")
    for c in d["risk"]["severity_changes"]:
        out.append(f"  severity {c['from']:g} -> {c['to']:g} {c['qualified_name']}")
    out.append("[spec]")
    for k in ("added", "removed", "changed"):
        for q in d["spec"][k]:
            out.append(f"  {k:8s} {q}")
    out.append("[workflows]")
    for k in ("added", "removed", "changed"):
        for q in d["workflows"][k]:
            out.append(f"  {k:8s} {q}")
    return "\n".join(out) + "\n"

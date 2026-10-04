"""Task `judge`: does the linked code do what the spec item says? (format spec §11.4)

The slice (§2.1 of the P4 decisions) is built deterministically from the file:
- spec side: the spec item's lines; for a `spec_endpoint`, its OpenAPI operation (≤ openapi_max_lines);
- code side: the paired node's span (a port's handler), capped at code_max_lines as head + tail
  with an elision marker, plus an IR digest of the elided lines; the signatures of its direct
  callees on the port's workflows (≤ callee_sig_max_lines); the resources it reaches;
- for a `stale` link: a unified diff of the changed side since the last agreement (≤ stale_diff_max_lines).

Outputs are checked deterministically: evidence ranges must lie in lines present in the slice,
`drift`/`partial` need code and spec evidence, and the rationale is non-empty. An invalid result
is kept for audit with verdict `cannot_tell`.
"""

from __future__ import annotations

import difflib
import sqlite3
from typing import Any

from ad2v import ids, ir, store
from ad2v.extract.code.schema_digest import MAX_LINES, digest_lines
from ad2v.llm import fence
from ad2v.llm.context import EpochView
from ad2v.llm.prompts import load as load_prompt
from ad2v.llm.runner import Executor, Job, Result

JUDGEABLE_STATUSES = frozenset({"implemented", "verified", "stale"})
# P7 (ADR-0060): containers and components get a deterministic roll-up, never a judge call
ROLLUP_KINDS = frozenset({"container", "component", "spec_component"})
SEVERITY = {"drift": 3, "partial": 2, "conforms": 1, "cannot_tell": 0}
VERDICTS = ("conforms", "partial", "drift", "cannot_tell")

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string", "maxLength": 400},
        "evidence": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "side": {"type": "string", "enum": ["spec", "code"]},
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                    "claim": {"type": "string", "maxLength": 160},
                },
                "required": ["side", "start_line", "end_line", "claim"],
            },
        },
    },
    "required": ["verdict", "confidence", "rationale", "evidence"],
}


def judgeable(view: EpochView) -> list[ir.Link]:
    out = []
    for lk in view.derived.pairing.links:
        if lk.spec_node_id is None or lk.code_node_id is None or lk.method == "none":
            continue
        code = view.graph.nodes[lk.code_node_id]
        spec = view.graph.nodes[lk.spec_node_id]
        if code.kind in ROLLUP_KINDS or spec.kind in ROLLUP_KINDS:
            continue
        if lk.status in JUDGEABLE_STATUSES and not code.attrs.get("is_test"):
            out.append(lk)
    return sorted(out, key=lambda lk: lk.link_id)


def subject(view: EpochView, lk: ir.Link) -> str:
    g = view.graph
    return f"{g.nodes[lk.spec_node_id].qualified_name} -> {g.nodes[lk.code_node_id].qualified_name}"


def _cap(lines: list[tuple[int, str]], limit: int) -> list[tuple[int, str]]:
    return lines[:limit]


def build_slice(view: EpochView, lk: ir.Link) -> dict[str, Any]:
    """The judge's input for one link. Pure: same epoch, same slice."""
    sl = view.cfg.slice
    spec = view.graph.nodes[lk.spec_node_id]
    linked = view.graph.nodes[lk.code_node_id]
    code = view.handler_of(linked)
    spec_lines = view.span_lines(spec)
    if spec.kind == "spec_endpoint":
        spec_lines = _cap(spec_lines, sl["openapi_max_lines"])
    out: dict[str, Any] = {
        "link": {"method": lk.method, "status": lk.status},
        "spec": {
            "id": spec.qualified_name,
            "kind": spec.kind,
            "path": spec.path,
            "text": spec.attrs.get("text"),
            "lines": [[i, t] for i, t in spec_lines],
        },
    }
    code_lines = view.span_lines(code)
    elided = None
    if len(code_lines) > sl["code_max_lines"]:
        head, tail = code_lines[: sl["code_head"]], code_lines[-sl["code_tail"] :]
        elided = [head[-1][0] + 1, tail[0][0] - 1]
        code_lines = head + tail
    callees = []
    in_workflows = {w.workflow_id for w in view.workflows_of.get(code.id, [])}
    sig_budget = sl["callee_sig_max_lines"]
    for e in view.out_edges.get(code.id, []):
        callee = view.graph.nodes.get(e.dst)
        if e.kind != "calls" or callee is None or callee.kind not in ("function", "class"):
            continue
        if in_workflows and not in_workflows & {w.workflow_id for w in view.workflows_of.get(callee.id, [])}:
            continue
        sig = view.signature(callee)
        if not sig or len(sig) > sig_budget:
            continue
        sig_budget -= len(sig)
        callees.append({"id": callee.qualified_name, "lines": [[i, t] for i, t in sig]})
    out["code"] = {
        "id": linked.qualified_name,
        "kind": linked.kind,
        "handler": code.qualified_name if code is not linked else None,
        "path": code.path,
        "lines": [[i, t] for i, t in code_lines],
        "elided": elided,
        "elided_digest": view.digest(code, elided[0], elided[1]) if elided else None,
        "digest": view.digest(code) if not code_lines else None,
        "callee_signatures": callees,
        "resources": view.resources_reached(code.id),
    }
    # P7 (ADR-0059): the schema of the datastores the code reaches, ≤ 40 lines (the REQ-009 gap)
    schema: list[str] = []
    by_q = {n.qualified_name: n for n in view.graph.nodes.values() if n.kind == "datastore"}
    for q in out["code"]["resources"]:
        d = by_q.get(q)
        if d is not None and d.attrs.get("schema_digest"):
            schema += [f"datastore {q}"] + digest_lines(d.attrs["schema_digest"], MAX_LINES)
    if schema:
        out["code"]["schema"] = schema[:MAX_LINES]
    if lk.status == "stale":
        out["since_agreement"] = stale_diff(view, lk, spec, code, sl["stale_diff_max_lines"])
    return out


def stale_diff(view: EpochView, lk: ir.Link, spec: ir.Node, code: ir.Node, limit: int) -> dict[str, Any]:
    state = store.load_link_state(view.conn, view.epoch_id).get(lk.link_id) or {}
    agreed = state.get("agreed_epoch_id")
    info: dict[str, Any] = {"agreed_epoch_id": agreed, "diffs": []}
    if not agreed or store.get_epoch_or_none(view.conn, agreed) is None:
        info["note"] = "agreement epoch not in this file"
        return info
    old = EpochView(view.conn, agreed, view.cfg)
    for side, node, agreed_hash in (
        ("spec", spec, state.get("agreed_spec_hash")),
        ("code", code, state.get("agreed_code_hash")),
    ):
        if agreed_hash is None or agreed_hash == node.content_hash:
            continue
        old_node = old.graph.nodes.get(node.id)
        before = [t for _, t in old.span_lines(old_node)] if old_node is not None else []
        after = [t for _, t in view.span_lines(node)]
        diff = list(
            difflib.unified_diff(before, after, f"{side} @ agreement", f"{side} now", n=2, lineterm="")
        )
        info["diffs"].append({"side": side, "lines": diff[:limit], "truncated": len(diff) > limit})
    return info


def serialize(sl: dict[str, Any]) -> list[str]:
    """The fenced data parts of the prompt: everything cut from the repository is untrusted."""
    spec, code = sl["spec"], sl["code"]
    parts = [
        fence.fence(
            "spec",
            f"{spec['kind']} {spec['id']} ({spec['path']})",
            fence.numbered([tuple(x) for x in spec["lines"]]),
        ),
    ]
    code_text = fence.numbered([tuple(x) for x in code["lines"]])
    if code["elided"]:
        a, b = code["elided"]
        head = [tuple(x) for x in code["lines"] if x[0] < a]
        tail = [tuple(x) for x in code["lines"] if x[0] > b]
        code_text = (
            fence.numbered(head)
            + f"\n    ... lines {a}-{b} elided; IR digest below ...\n"
            + fence.numbered(tail)
        )
    label = (
        f"{code['kind']} {code['id']}"
        + (f" handled by {code['handler']}" if code["handler"] else "")
        + f" ({code['path']})"
    )
    parts.append(fence.fence("code", label, code_text or "(no source span: see the IR digest)"))
    ir_part = {
        "link": sl["link"],
        "elided_digest": code["elided_digest"],
        "digest": code["digest"],
        "resources_reached": code["resources"],
        "callee_signatures": [
            {"id": c["id"], "signature": " ".join(t.strip() for _, t in c["lines"])}
            for c in code["callee_signatures"]
        ],
    }
    parts.append(
        fence.fence("ir", "ad2v IR digest (derived from the repository)", ids.canonical_json(ir_part))
    )
    if code.get("schema"):
        body = "\n".join(code["schema"])
        parts.append(fence.fence("schema", "datastore schema digest (derived from the repository)", body))
    if "since_agreement" in sl:
        diffs = sl["since_agreement"]
        body = "\n\n".join("\n".join(d["lines"]) for d in diffs["diffs"]) or diffs.get("note", "(no diff)")
        parts.append(fence.fence("diff", f"changes since agreement {diffs['agreed_epoch_id']}", body))
    return parts


def validator(sl: dict[str, Any]):  # noqa: ANN201 - returns the Job validator
    spec_lines = {x[0] for x in sl["spec"]["lines"]}
    code_lines = {x[0] for x in sl["code"]["lines"]}

    def check(out: dict[str, Any]) -> list[dict[str, str]]:
        errors = []
        if not out.get("rationale", "").strip():
            errors.append({"code": "empty_rationale", "message": "rationale is empty", "severity": "error"})
        sides = set()
        for i, ev in enumerate(out.get("evidence", [])):
            present = spec_lines if ev["side"] == "spec" else code_lines
            rng = range(ev["start_line"], ev["end_line"] + 1)
            if ev["end_line"] < ev["start_line"] or not rng or any(n not in present for n in rng):
                errors.append(
                    {
                        "code": "evidence_out_of_slice",
                        "message": f"evidence[{i}] {ev['side']} {ev['start_line']}-{ev['end_line']}"
                        " is not in the slice",
                        "severity": "error",
                    }
                )
            else:
                sides.add(ev["side"])
        if out.get("verdict") in ("drift", "partial") and sides != {"spec", "code"}:
            errors.append(
                {
                    "code": "evidence_missing",
                    "message": f"{out['verdict']} needs valid spec and code evidence",
                    "severity": "error",
                }
            )
        return errors

    return check


def job(view: EpochView, lk: ir.Link) -> tuple[Job, dict[str, Any]]:
    sl = build_slice(view, lk)
    prompt = load_prompt("judge")
    return Job("judge", subject(view, lk), serialize(sl), prompt.user, SCHEMA, validator(sl)), sl


def row(epoch_id: str, lk: ir.Link, res: Result, min_confidence: float) -> tuple[Any, ...]:
    out = res.output if isinstance(res.output, dict) else {}
    valid = res.valid
    verdict = out.get("verdict", "cannot_tell") if valid else "cannot_tell"
    confidence = float(out.get("confidence", 0.0)) if valid else 0.0
    warned = any(e["code"] == "injection_suspected" for e in res.errors)  # no drift overlay then
    overlay = "drift" if verdict == "drift" and confidence >= min_confidence and not warned else "evidence"
    rationale = (
        out.get("rationale", "") if valid else "invalid output: " + "; ".join(e["code"] for e in res.errors)
    )
    return (
        epoch_id,
        lk.link_id,
        res.result_id,
        verdict,
        confidence,
        rationale[:400],
        ids.canonical_json(out.get("evidence", []) if valid else []),
        int(valid),
        overlay,
    )


def run(view: EpochView, ex: Executor, link_ids: set[str] | None = None) -> list[tuple[Any, ...]]:
    """Judge every judgeable link (or `link_ids`); write link_judgments rows for answered links."""
    rows = []
    for lk in judgeable(view):
        if link_ids is not None and lk.link_id not in link_ids:
            continue
        j, _sl = job(view, lk)
        res = ex.call(j)
        if res is not None:
            rows.append(row(view.epoch_id, lk, res, view.cfg.min_confidence))
    if ex.mode != "plan":
        write(view.conn, view.epoch_id, rows, replace=link_ids is None)
        write_rollups(view.conn, view.epoch_id, rollup(view.conn, view.epoch_id, view.cfg.min_confidence))
    return rows


def rollup(conn: sqlite3.Connection, epoch_id: str, min_confidence: float) -> list[tuple[Any, ...]]:
    """A container's, component's or spec component's verdict: the worst confident verdict among
    its descendants' link judgments (drift > partial > conforms > cannot_tell), with its
    confidence and the counts. Deterministic: the same judgments give the same rows."""
    nodes = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT id, kind, parent_id FROM nodes WHERE epoch_id = ?", (epoch_id,))}  # fmt: skip
    rows = conn.execute(
        "SELECT j.link_id, j.verdict, j.confidence, l.spec_node_id, l.code_node_id FROM link_judgments j"
        " JOIN links l ON l.epoch_id = j.epoch_id AND l.link_id = j.link_id"
        " WHERE j.epoch_id = ? AND j.valid = 1 AND j.confidence >= ? ORDER BY j.link_id",
        (epoch_id, min_confidence),
    ).fetchall()
    acc: dict[str, list[tuple[str, str, float]]] = {}
    for link_id, verdict, conf, spec_id, code_id in rows:
        seen: set[str] = set()
        for start in (spec_id, code_id):
            cur = nodes.get(start, (None, None))[1]
            while cur is not None and cur in nodes:
                if nodes[cur][0] in ROLLUP_KINDS and cur not in seen:
                    seen.add(cur)
                    acc.setdefault(cur, []).append((link_id, verdict, conf))
                cur = nodes[cur][1]
    out = []
    for nid in sorted(acc):
        js = acc[nid]
        worst = max(js, key=lambda j: (SEVERITY[j[1]], j[2], j[0]))
        counts: dict[str, int] = {}
        for _, v, _ in js:
            counts[v] = counts.get(v, 0) + 1
        out.append(
            (epoch_id, nid, worst[1], worst[2], ids.canonical_json(counts),
             ids.canonical_json(sorted(j[0] for j in js)), min_confidence)
        )  # fmt: skip
    return out


def write_rollups(conn: sqlite3.Connection, epoch_id: str, rows: list[tuple[Any, ...]]) -> None:
    conn.execute("DELETE FROM judge_rollups WHERE epoch_id = ?", (epoch_id,))
    conn.executemany("INSERT INTO judge_rollups VALUES (?,?,?,?,?,?,?)", rows)


def write(conn: sqlite3.Connection, epoch_id: str, rows: list[tuple[Any, ...]], replace: bool = True) -> None:
    if replace:
        conn.execute("DELETE FROM link_judgments WHERE epoch_id = ?", (epoch_id,))
    conn.executemany("INSERT OR REPLACE INTO link_judgments VALUES (?,?,?,?,?,?,?,?,?)", rows)

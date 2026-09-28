"""Task `narrate`: step narrations for workflow replay (format spec §11.7).

For each code workflow and each containment depth that yields a distinct projection, one call
(or one per chunk of `CHUNK` coarse steps) narrates the coarse steps. Coarse spans come from
`workflows.project()`, so they are deterministic. Each coarse step at a finer level gets the
narration of the enclosing coarse step one level up as context, so finer narrations read as a
refinement of coarser ones (replay consistency). `mode=containment` is written eagerly;
`call_depth` narrations are generated on demand for one workflow.
"""

from __future__ import annotations

import re
from typing import Any

from ad2v import ids, ir, workflows
from ad2v.llm import fence
from ad2v.llm.context import EpochView
from ad2v.llm.prompts import load as load_prompt
from ad2v.llm.runner import Executor, Job, Result, now

CHUNK = 40
NODE_ID_RE = re.compile(r"\bn_[0-9a-f]{20}\b")
MAX_TOUCHED = 12


def schema(n: int) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "narrations": {
                "type": "array",
                "minItems": n,
                "maxItems": n,
                "items": {
                    "type": "object",
                    "properties": {
                        "step": {"type": "integer", "minimum": 0},
                        "text": {"type": "string", "maxLength": 280},
                        "mentions": {
                            "type": "array",
                            "maxItems": 8,
                            "items": {"type": "string", "maxLength": 40},
                        },
                    },
                    "required": ["step", "text", "mentions"],
                },
            }
        },
        "required": ["narrations"],
    }


def levels(
    view: EpochView, w: ir.Workflow, mode: str = "containment"
) -> list[tuple[int, list[Any], list[tuple[int, int]]]]:
    """[(detail_level, coarse steps, spans)] for each level with a distinct projection, coarse first."""
    anc = workflows.ancestry(view.graph)
    max_depth = max((len(anc.get(n, [])) for s in w.steps for n in s.node_ids), default=1)
    if mode == "call_depth":
        max_depth = max((s.depth for s in w.steps), default=0) + 1
    out, prev = [], None
    for k in range(1, max_depth + 1):
        coarse, spans = workflows.project(w.steps, k, mode, anc)
        if spans != prev:
            out.append((k, coarse, spans))
            prev = spans
        if len(spans) == len(w.steps):
            break
    return out


def _parent_text(parent: list[tuple[tuple[int, int], str]] | None, span: tuple[int, int]) -> str | None:
    for (a, b), text in parent or []:
        if a <= span[0] and span[1] <= b:
            return text
    return None


def jobs_for_level(
    view: EpochView,
    w: ir.Workflow,
    k: int,
    coarse: list[Any],
    spans: list[tuple[int, int]],
    parent: list[tuple[tuple[int, int], str]] | None,
    mode: str,
) -> list[tuple[Job, int, set[str]]]:
    g = view.graph
    port = g.nodes.get(w.entry_node_id)
    out = []
    for c0 in range(0, len(coarse), CHUNK):
        chunk = []
        for i in range(c0, min(c0 + CHUNK, len(coarse))):
            cs = coarse[i]
            chunk.append(
                {
                    "step": i - c0,
                    "fine_span": list(spans[i]),
                    "highlight": [
                        f"{n} {g.nodes[n].kind} {g.nodes[n].qualified_name}"
                        for n in cs.node_ids
                        if n in g.nodes
                    ],
                    "touched": [
                        f"{n} {g.nodes[n].qualified_name}" for n in cs.touched[:MAX_TOUCHED] if n in g.nodes
                    ],
                    "coarser_narration": _parent_text(parent, spans[i]),
                }
            )
        head = {
            "workflow": w.name,
            "entry": f"{w.entry_node_id} {port.qualified_name}" if port else w.entry_node_id,
            "mode": mode,
            "detail_level": k,
            "chunk": [c0, min(c0 + CHUNK, len(coarse)) - 1],
            "coarse_steps_total": len(coarse),
        }
        parts = [
            fence.fence(
                "workflow", f"workflow {w.name} level {k}", ids.canonical_json({**head, "steps": chunk})
            )
        ]
        allowed = set(NODE_ID_RE.findall(parts[0]))
        n = len(chunk)

        def check(o: dict[str, Any], n: int = n, allowed: set[str] = allowed) -> list[dict[str, str]]:
            errs = []
            if sorted(x["step"] for x in o["narrations"]) != list(range(n)):
                errs.append(
                    {"code": "steps_mismatch", "message": f"expected steps 0..{n - 1}", "severity": "error"}
                )
            bad = sorted({m for x in o["narrations"] for m in x["mentions"] if m not in allowed})
            if bad:
                errs.append(
                    {"code": "invalid_mentions", "message": ", ".join(bad)[:200], "severity": "warning"}
                )
            return errs

        subject = f"{w.workflow_id} {mode} L{k} C{c0}"
        out.append(
            (
                Job(
                    "narrate",
                    subject,
                    parts,
                    load_prompt("narrate").user,
                    schema(n),
                    check,
                    output_estimate=60 * n + 80,
                    # repository-derived only: the coarser narrations are earlier LLM output
                    haystack=ids.canonical_json(
                        {
                            **head,
                            "steps": [
                                {k: v for k, v in s.items() if k != "coarser_narration"} for s in chunk
                            ],
                        }
                    ),
                ),
                c0,
                allowed,
            )
        )
    return out


def narrate_workflow(
    view: EpochView, ex: Executor, w: ir.Workflow, mode: str = "containment"
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    parent: list[tuple[tuple[int, int], str]] | None = None
    prompt_hash = load_prompt("narrate").prompt_hash
    created = now()
    for k, coarse, spans in levels(view, w, mode):
        texts: list[tuple[tuple[int, int], str]] = []
        for j, c0, allowed in jobs_for_level(view, w, k, coarse, spans, parent, mode):
            res: Result | None = ex.call(j)
            if res is None or not res.valid:
                continue
            for x in sorted(res.output["narrations"], key=lambda x: x["step"]):
                i = c0 + x["step"]
                a, b = spans[i]
                mentions = [m for m in x["mentions"] if m in allowed]
                text = x["text"] + (f" [mentions: {', '.join(mentions)}]" if mentions else "")
                texts.append(((a, b), x["text"]))
                rows.append(
                    (
                        view.epoch_id,
                        w.workflow_id,
                        mode,
                        k,
                        a,
                        b,
                        text,
                        ex.provider.model,
                        ex.model_version or ex.provider.model,
                        prompt_hash,
                        j.input_hash,
                        1.0,
                        created,
                        res.result_id,
                    )
                )
        parent = texts
    return rows


def run(
    view: EpochView, ex: Executor, mode: str = "containment", workflow: str | None = None
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for w in sorted(view.derived.workflows, key=lambda w: w.workflow_id):
        if w.side != "code" or (workflow is not None and workflow not in (w.workflow_id, w.name)):
            continue
        rows.extend(narrate_workflow(view, ex, w, mode))
    if ex.mode != "plan":
        if workflow is None:
            view.conn.execute("DELETE FROM narrations WHERE epoch_id = ? AND mode = ?", (view.epoch_id, mode))
        view.conn.executemany("INSERT OR REPLACE INTO narrations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return rows

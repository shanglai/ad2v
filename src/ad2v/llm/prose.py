"""Task `extract-prose`: propose requirements from free prose, frozen for human review (§11.8).

The model returns structured JSON; ad2v renders it deterministically as Markdown in the existing
convention (`## Component: ... {#CMP-X001}`, `- [REQ-X001] When ..., the ... shall ....`) with IDs
from the reserved `-X` range, so they never collide with human IDs. The file is written to
`<spec root>/.ad2v-extracted/<doc-slug>.md`, a directory every extraction skips. Moving or
renaming the file into the spec tree is the approval; it is then parsed like any spec.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ad2v import ir
from ad2v.llm import fence
from ad2v.llm.context import EpochView
from ad2v.llm.prompts import load as load_prompt
from ad2v.llm.runner import Executor, Job, Result

EXTRACTED_DIR = ".ad2v-extracted"
EARS = ("event", "state", "unwanted", "optional", "ubiquitous")
# P9 (ADR-0069): Spanish EARS is accepted too ("Cuando …, el sistema deberá …")
EARS_START = {
    "event": ("when ", "cuando ", "mientras "),
    "state": ("while ", "mientras "),
    "unwanted": ("if ", "si "),
    "optional": ("where ", "donde "),
}
MODAL_RE = re.compile(r"\b(?:shall|deber[aá]n?|debe(?:n)?|tendr[aá]n?\s+que)\b", re.I)
MIN_PROSE_CHARS = 40

# Flat on purpose: Vertex rejected the nested form (an array of objects inside an array of
# objects) with HTTP 400 in the P4 live run. Requirements carry their component name.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "requirements": {
            "type": "array",
            "maxItems": 30,
            "items": {
                "type": "object",
                "properties": {
                    "component": {"type": "string", "maxLength": 80},
                    "ears": {"type": "string", "enum": list(EARS)},
                    "text": {"type": "string", "maxLength": 300},
                    "source_start_line": {"type": "integer", "minimum": 1},
                    "source_end_line": {"type": "integer", "minimum": 1},
                },
                "required": ["component", "ears", "text", "source_start_line", "source_end_line"],
            },
        }
    },
    "required": ["requirements"],
}


def grouped(out: dict[str, Any]) -> list[dict[str, Any]]:
    """[{name, requirements}] in first-seen component order (at most 5 components)."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in out["requirements"]:
        groups.setdefault(" ".join(r["component"].split()) or "Requirements", []).append(r)
    return [{"name": k, "requirements": v} for k, v in list(groups.items())[:5]]


def docs(view: EpochView) -> list[ir.Node]:
    out = [
        n
        for n in view.graph.nodes.values()
        if n.kind == "spec_doc"
        and n.attrs.get("format") == "markdown"
        and len((n.attrs.get("prose") or "").strip()) >= MIN_PROSE_CHARS
    ]
    return sorted(out, key=lambda n: n.qualified_name)


def slug(path: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", path.lower().rsplit(".", 1)[0]).strip("-") or "doc"


def job(view: EpochView, doc: ir.Node) -> Job:
    lines = view.span_lines(doc)
    existing = sorted(
        view.graph.nodes[c].qualified_name
        for c in view.graph.nodes
        if view.graph.nodes[c].path == doc.path
        and view.graph.nodes[c].kind in ("requirement", "spec_component")
    )
    parts = [
        fence.fence("spec", f"spec document {doc.path}", fence.numbered(lines)),
        fence.fence(
            "ir", "requirement ids already defined in this document", ", ".join(existing) or "(none)"
        ),
    ]
    present = {i for i, _ in lines}

    def check(out: dict[str, Any]) -> list[dict[str, str]]:
        errs = []
        for c in grouped(out):
            for r in c["requirements"]:
                text = r["text"].strip()
                rng = range(r["source_start_line"], r["source_end_line"] + 1)
                if not rng or any(x not in present for x in rng):
                    errs.append({"code": "source_out_of_doc", "message": text[:80], "severity": "error"})
                if not MODAL_RE.search(text):
                    errs.append(
                        {
                            "code": "not_ears",
                            "message": f"no 'shall' / 'deberá': {text[:80]}",
                            "severity": "error",
                        }
                    )
                starts = EARS_START.get(r["ears"])
                if starts and not text.lower().startswith(starts):
                    errs.append(
                        {"code": "ears_mismatch", "message": f"{r['ears']}: {text[:80]}", "severity": "error"}
                    )
        return errs

    return Job(
        "extract-prose",
        doc.qualified_name,
        parts,
        load_prompt("extract-prose").user,
        SCHEMA,
        check,
        verbatim_check=False,
    )


def render(
    doc: ir.Node, res: Result, model: str, model_version: str | None, first_req: int, first_cmp: int
) -> tuple[str, int, int]:
    """Deterministic Markdown in the ad2v convention. Returns (text, next req no, next cmp no)."""
    out = [
        "<!--",
        "  ad2v extract-prose: REVIEW BEFORE COMMITTING.",
        f"  source: {doc.path} (content_hash {doc.content_hash[:12]})",
        f"  model: {model} ({model_version or 'unknown version'});"
        f" prompt_hash {load_prompt('extract-prose').prompt_hash[:12]}; result {res.result_id}",
        "  These requirements were proposed by an LLM from free prose. ad2v ignores this directory.",
        "  To approve, edit as needed and move or rename the file into the spec tree.",
        "-->",
        "",
        f"# Proposed requirements from {doc.path}",
        "",
    ]
    rq, cp = first_req, first_cmp
    for c in grouped(res.output):
        out += [f"## Component: {c['name'].strip()} {{#CMP-X{cp:03d}}}", ""]
        cp += 1
        for r in c["requirements"]:
            text = " ".join(r["text"].split())
            out.append(f"- [REQ-X{rq:03d}] {text}")
            out.append(
                f"  <!-- {r['ears']}; source lines {r['source_start_line']}-{r['source_end_line']} -->"
            )
            rq += 1
        out.append("")
    return "\n".join(out).rstrip() + "\n", rq, cp


def run(
    view: EpochView, ex: Executor, spec_root: Path | None = None, first_req: int = 1, first_cmp: int = 1
) -> list[tuple[Any, ...]]:
    """`first_req` / `first_cmp`: where the reserved -X numbering starts (P6.1 bootstrap continues
    after the -X ids already approved into the spec tree, so proposals never collide)."""
    rows = []
    rq, cp = first_req, first_cmp
    known = {n.qualified_name for n in view.graph.nodes.values() if n.side == "spec"}
    for doc in docs(view):
        j = job(view, doc)
        res = ex.call(j)
        if res is None or not res.valid:
            continue
        version = ex.conn.execute(
            "SELECT model_version FROM llm_results WHERE result_id = ?", (res.result_id,)
        ).fetchone()[0]
        start_rq = rq
        text, rq, cp = render(doc, res, ex.provider.model, version, rq, cp)
        rel = f"{EXTRACTED_DIR}/{slug(doc.path)}.md"
        proposed = {f"REQ-X{i:03d}" for i in range(start_rq, rq)}
        state = "ingested" if proposed and proposed <= known else "proposed"
        if spec_root is not None and state == "proposed" and ex.mode == "run":
            target = Path(spec_root) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode("utf-8"))
            state = "written"
        rows.append((view.epoch_id, doc.id, res.result_id, rel, state))
    if ex.mode != "plan":
        view.conn.execute("DELETE FROM spec_extractions WHERE epoch_id = ?", (view.epoch_id,))
        view.conn.executemany("INSERT INTO spec_extractions VALUES (?,?,?,?,?)", rows)
    return rows


def rendered(conn: Any, view: EpochView, doc_id: str, result_id: str) -> str:
    """Re-render a stored extraction (for `ad2v llm show-prose`)."""
    doc = view.graph.nodes[doc_id]
    row = conn.execute(
        "SELECT output_json, model, model_version FROM llm_results WHERE result_id = ?", (result_id,)
    ).fetchone()
    res = Result(result_id, json.loads(row[0]), True, [], True, "extract-prose", doc.qualified_name)
    order = [d.id for d in docs(view)]
    rq = cp = 1
    for d in docs(view)[: order.index(doc_id)] if doc_id in order else []:
        prev = conn.execute(
            "SELECT result_id FROM spec_extractions WHERE epoch_id = ? AND spec_doc_node_id = ?",
            (view.epoch_id, d.id),
        ).fetchone()
        if prev:
            pr = conn.execute(
                "SELECT output_json FROM llm_results WHERE result_id = ?", (prev[0],)
            ).fetchone()
            out = json.loads(pr[0])
            rq += sum(len(c["requirements"]) for c in grouped(out))
            cp += len(grouped(out))
    text, _, _ = render(doc, res, row[1], row[2], rq, cp)
    return text

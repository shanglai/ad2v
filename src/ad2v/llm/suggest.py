"""Task `suggest`: link suggestions for unpaired items (format spec §11.5).

1. Deterministic candidates: BM25 (standard library) over tokens from names, qualified names,
   docstrings, route paths, spec titles and text. Top-k code candidates per unpaired spec item,
   and top-k spec candidates per unpaired code item.
2. One LLM call per item judges its candidates; `match` verdicts with confidence at or above
   `llm.judge.min_confidence` become suggestions.
3. A human confirms: `ad2v suggestions accept|reject` appends the pair to `pairing.links` /
   `pairing.rejected` in ad2v.yaml. That changes `config_hash`, so the next extraction makes the
   link normative (method `manifest_link`); rejected pairs are never proposed again.
"""

from __future__ import annotations

import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ad2v import ids, ir
from ad2v.llm import fence
from ad2v.llm.context import PORT_KINDS, EpochView
from ad2v.llm.prompts import load as load_prompt
from ad2v.llm.runner import Executor, Job, Result

SPEC_ITEM_KINDS = ("requirement", "spec_component", "spec_endpoint")
CODE_CANDIDATE_KINDS = frozenset({"container", "component", "function", "class", *PORT_KINDS})
UNPAIRED_SPEC = frozenset({"specified", "missing"})
SNIPPET_LINES = 25
MAX_MATCHES = 2
STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "per",
        "shall",
        "should",
        "that",
        "the",
        "then",
        "this",
        "to",
        "when",
        "where",
        "which",
        "while",
        "will",
        "with",
        "py",
        "def",
        "self",
        "return",
        "none",
        "true",
        "false",
    }
)
BM25_K1, BM25_B = 1.2, 0.75

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "maxItems": MAX_MATCHES,
            "items": {
                "type": "object",
                "properties": {
                    "candidate": {"type": "string", "maxLength": 8},
                    "verdict": {"type": "string", "enum": ["match", "no_match"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "rationale": {"type": "string", "maxLength": 400},
                    "evidence": {
                        "type": "array",
                        "maxItems": 6,
                        "items": {
                            "type": "object",
                            "properties": {
                                "start_line": {"type": "integer", "minimum": 1},
                                "end_line": {"type": "integer", "minimum": 1},
                                "claim": {"type": "string", "maxLength": 160},
                            },
                            "required": ["start_line", "end_line", "claim"],
                        },
                    },
                },
                "required": ["candidate", "verdict", "confidence", "rationale", "evidence"],
            },
        }
    },
    "required": ["matches"],
}


# -- tokens and BM25 ---------------------------------------------------------------------------
def stem(t: str) -> str:
    for suf, rep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if len(t) > len(suf) + 3 and t.endswith(suf):
            return t[: -len(suf)] + rep
    return t


def tokens(text: str) -> list[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return [stem(t) for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS and len(t) > 1]


@dataclass
class BM25:
    docs: dict[str, list[str]]

    def __post_init__(self) -> None:
        self.n = len(self.docs)
        self.avg = sum(len(d) for d in self.docs.values()) / max(self.n, 1)
        df: Counter[str] = Counter()
        for d in self.docs.values():
            df.update(set(d))
        self.idf = {t: math.log(1 + (self.n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = {k: Counter(d) for k, d in self.docs.items()}

    def score(self, query: list[str], key: str) -> float:
        tf, dl = self.tf[key], len(self.docs[key])
        s = 0.0
        for t in set(query):
            f = tf.get(t, 0)
            if f:
                s += (
                    self.idf[t]
                    * f
                    * (BM25_K1 + 1)
                    / (f + BM25_K1 * (1 - BM25_B + BM25_B * dl / (self.avg or 1)))
                )
        return round(s, 6)

    def top(self, query: list[str], k: int, exclude: set[str] = frozenset()) -> list[tuple[str, float]]:
        scored = [(key, self.score(query, key)) for key in sorted(self.docs) if key not in exclude]
        return sorted([x for x in scored if x[1] > 0], key=lambda x: (-x[1], x[0]))[:k]


def code_doc(view: EpochView, n: ir.Node) -> str:
    parts = [n.name, n.qualified_name]
    a = n.attrs
    parts += [
        str(a.get(k, "")) for k in ("path", "method", "command", "tool_name", "handler", "container_kind")
    ]
    target = view.handler_of(n)
    parts += [t for _, t in view.span_lines(target)[:12]]  # def line + docstring
    if n.kind in ("container", "component"):
        for c in view.kids.get(n.id, []):
            parts.append(view.graph.nodes[c].name)
        parts += [p.split(":", 2)[-1] for p in view.digest(n).get("ports", [])]
        parts += [
            t for m in view.kids.get(n.id, []) for _, t in view.span_lines(view.graph.nodes[m], 1, 3)
        ]  # module docstrings
    return " ".join(parts)


def spec_doc(n: ir.Node) -> str:
    a = n.attrs
    return " ".join(
        str(x)
        for x in (
            n.name,
            n.qualified_name,
            a.get("text", ""),
            a.get("method", ""),
            a.get("path", ""),
            a.get("summary", ""),
        )
    )


# -- items and candidates -----------------------------------------------------------------------
def unpaired(view: EpochView) -> tuple[list[str], list[str]]:
    """(spec items, code items) that need a partner, sorted."""
    g = view.graph
    specs = sorted(
        n for n, x in g.nodes.items() if x.kind in SPEC_ITEM_KINDS and view.status_of(n) in UNPAIRED_SPEC
    )
    coverage = "none" if not any(x.kind in SPEC_ITEM_KINDS for x in g.nodes.values()) else "present"
    codes = sorted(
        n
        for n, x in g.nodes.items()
        if x.side == "code"
        and (
            view.status_of(n) == "orphan"
            or (coverage != "none" and x.kind in PORT_KINDS and view.status_of(n) == "none")
        )
    )
    return specs, codes


def candidates(view: EpochView) -> list[dict[str, Any]]:
    """Deterministic groups: one per unpaired item, with its top-k candidates and BM25 scores."""
    g, k = view.graph, view.cfg.suggest_top_k
    rejected = set(view.config.pairing_rejected)
    code_pool = {
        n: tokens(code_doc(view, x))
        for n, x in g.nodes.items()
        if x.kind in CODE_CANDIDATE_KINDS and not x.attrs.get("is_test")
    }
    spec_pool = {n: tokens(spec_doc(x)) for n, x in g.nodes.items() if x.kind in SPEC_ITEM_KINDS}
    code_bm, spec_bm = BM25(code_pool), BM25(spec_pool)
    specs, codes = unpaired(view)
    groups = []
    for s in specs:
        skip = {c for c in code_pool if (g.nodes[s].qualified_name, g.nodes[c].qualified_name) in rejected}
        top = code_bm.top(spec_pool.get(s) or tokens(spec_doc(g.nodes[s])), k, skip)
        if top:
            groups.append({"item": s, "side": "spec", "candidates": top})
    for c in codes:
        if c not in code_pool:
            continue
        skip = {s for s in spec_pool if (g.nodes[s].qualified_name, g.nodes[c].qualified_name) in rejected}
        top = spec_bm.top(code_pool[c], k, skip)
        if top:
            groups.append({"item": c, "side": "code", "candidates": top})
    return groups


def _show(view: EpochView, nid: str) -> tuple[str, list[tuple[int, str]], dict[str, Any] | None]:
    n = view.graph.nodes[nid]
    if n.side == "spec":
        return f"{n.kind} {n.qualified_name} ({n.path})", view.span_lines(n)[:SNIPPET_LINES], None
    target = view.handler_of(n)
    lines = view.span_lines(target)[:SNIPPET_LINES]
    label = f"{n.kind} {n.qualified_name}" + (
        f" handled by {target.qualified_name}" if target is not n else ""
    )
    return f"{label} ({target.path or n.path or '-'})", lines, (view.digest(n) if not lines else None)


def job(view: EpochView, group: dict[str, Any]) -> Job:
    item = group["item"]
    label, lines, digest = _show(view, item)
    parts = [fence.fence("item", label, fence.numbered(lines) if lines else ids.canonical_json(digest or {}))]
    item_lines = {x for x, _ in lines}
    item_is_code = view.graph.nodes[item].side == "code"
    shown: dict[str, tuple[set[int], set[int]]] = {}  # key -> (citable lines, code lines)
    for i, (cid, score) in enumerate(group["candidates"], 1):
        clabel, clines, cdigest = _show(view, cid)
        key = f"C{i}"
        cand = {x for x, _ in clines}
        # evidence may cite any numbered line shown for the item or this candidate (the live run
        # cited a spec candidate's lines for a container item); a match needs code lines if any
        shown[key] = (item_lines | cand, item_lines if item_is_code else cand)
        body = fence.numbered(clines) if clines else "(no source span)"
        if cdigest:
            body += "\nIR digest: " + ids.canonical_json(cdigest)
        parts.append(fence.fence("candidate", f"{key}: {clabel} (lexical score {score})", body))
    subject = f"{view.graph.nodes[item].qualified_name} [{group['side']}]"
    return Job("suggest", subject, parts, load_prompt("suggest").user, SCHEMA, _validator(shown))


def _validator(shown: dict[str, tuple[set[int], set[int]]]):  # noqa: ANN202
    def check(out: dict[str, Any]) -> list[dict[str, str]]:
        errors = []
        seen = set()
        for i, m in enumerate(out.get("matches", [])):
            if m["candidate"] not in shown:
                errors.append(
                    {
                        "code": "unknown_candidate",
                        "message": f"matches[{i}] {m['candidate']}",
                        "severity": "error",
                    }
                )
                continue
            if m["candidate"] in seen:
                errors.append({"code": "duplicate_candidate", "message": m["candidate"], "severity": "error"})
            seen.add(m["candidate"])
            if not m["rationale"].strip():
                errors.append({"code": "empty_rationale", "message": f"matches[{i}]", "severity": "error"})
            lines, code_lines = shown[m["candidate"]]
            for ev in m["evidence"]:
                if ev["end_line"] < ev["start_line"] or any(
                    x not in lines for x in range(ev["start_line"], ev["end_line"] + 1)
                ):
                    errors.append(
                        {
                            "code": "evidence_out_of_slice",
                            "message": f"matches[{i}] {ev['start_line']}-{ev['end_line']}",
                            "severity": "error",
                        }
                    )
            if m["verdict"] == "match" and code_lines and not m["evidence"]:
                errors.append(
                    {
                        "code": "evidence_missing",
                        "message": f"matches[{i}] match needs code evidence",
                        "severity": "error",
                    }
                )
        return errors

    return check


def suggestion_id(spec_id: str, code_id: str) -> str:
    return "s_" + ids.sha256_hex(f"{spec_id}|{code_id}")[: ids.ID_HEX_LEN]


def rows_for(view: EpochView, group: dict[str, Any], res: Result) -> list[tuple[Any, ...]]:
    if not res.valid or not isinstance(res.output, dict):
        return []
    g = view.graph
    accepted, rejected = set(view.config.pairing_links), set(view.config.pairing_rejected)
    out = []
    for m in res.output["matches"]:
        if m["verdict"] != "match" or m["confidence"] < view.cfg.min_confidence:
            continue
        idx = int(m["candidate"][1:]) - 1
        cid, score = group["candidates"][idx]
        spec_id, code_id = (group["item"], cid) if group["side"] == "spec" else (cid, group["item"])
        pair = (g.nodes[spec_id].qualified_name, g.nodes[code_id].qualified_name)
        state = "accepted" if pair in accepted else "rejected" if pair in rejected else "open"
        out.append(
            (
                view.epoch_id,
                suggestion_id(spec_id, code_id),
                spec_id,
                code_id,
                idx + 1,
                score,
                res.result_id,
                "match",
                float(m["confidence"]),
                m["rationale"][:400],
                state,
            )
        )
    return out


def run(view: EpochView, ex: Executor) -> list[tuple[Any, ...]]:
    best: dict[str, tuple[Any, ...]] = {}
    for group in candidates(view):
        res = ex.call(job(view, group))
        if res is None:
            continue
        for r in rows_for(view, group, res):
            if r[1] not in best or r[8] > best[r[1]][8]:  # the same pair found from both sides
                best[r[1]] = r
    rows = [best[k] for k in sorted(best)]
    if ex.mode != "plan":
        view.conn.execute("DELETE FROM link_suggestions WHERE epoch_id = ?", (view.epoch_id,))
        view.conn.executemany("INSERT INTO link_suggestions VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    return rows


# -- human confirmation: minimal, append-only edits of ad2v.yaml ------------------------------
class ManifestEditError(RuntimeError):
    pass


def _entry(spec: str, code: str) -> str:
    import json

    return "{spec: " + json.dumps(spec) + ", code: " + json.dumps(code) + "}"


def append_pair(manifest: Path, key: str, spec: str, code: str) -> bool:
    """Append `{spec, code}` to `pairing.<key>` (links | rejected). Returns False if already there.

    The file is edited line by line: existing lines, comments and order are kept; lines are only
    inserted (or an empty inline `key: []` is opened into a block).
    """
    if key not in ("links", "rejected"):
        raise ValueError(key)
    text = manifest.read_text(encoding="utf-8") if manifest.exists() else ""
    before = yaml.safe_load(text) or {}
    existing = (before.get("pairing") or {}).get(key) or []
    if any(e.get("spec") == spec and e.get("code") == code for e in existing if isinstance(e, dict)):
        return False
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    item = _entry(spec, code)
    top = next((i for i, ln in enumerate(lines) if re.match(r"^pairing:\s*(#.*)?$", ln)), None)
    if top is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += ["pairing:", f"  {key}:", f"    - {item}"]
    else:
        end = next(
            (
                i
                for i in range(top + 1, len(lines))
                if lines[i].strip() and not lines[i].startswith((" ", "\t", "#"))
            ),
            len(lines),
        )
        kline = next((i for i in range(top + 1, end) if re.match(rf"^  {key}:", lines[i])), None)
        if kline is None:
            insert_at = end
            while insert_at > top + 1 and not lines[insert_at - 1].strip():
                insert_at -= 1
            lines[insert_at:insert_at] = [f"  {key}:", f"    - {item}"]
        elif re.match(rf"^  {key}:\s*\[\s*\]\s*(#.*)?$", lines[kline]):
            lines[kline : kline + 1] = [f"  {key}:", f"    - {item}"]
        elif re.match(rf"^  {key}:\s*(#.*)?$", lines[kline]):
            last = kline
            for i in range(kline + 1, end):
                if lines[i].startswith("    ") or not lines[i].strip():
                    if lines[i].strip():
                        last = i
                else:
                    break
            lines.insert(last + 1, f"    - {item}")
        else:
            raise ManifestEditError(f"pairing.{key} is not a block list; add the entry by hand: - {item}")
    new = nl.join(lines) + nl
    after = yaml.safe_load(new) or {}
    got = (after.get("pairing") or {}).get(key) or []
    if {"spec": spec, "code": code} not in got or {k: v for k, v in after.items() if k != "pairing"} != {
        k: v for k, v in before.items() if k != "pairing"
    }:
        raise ManifestEditError("refusing to write: the edit would change more than the appended entry")
    manifest.write_bytes(new.encode("utf-8"))
    return True


def get_suggestion(conn: sqlite3.Connection, epoch_id: str, sid: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT s.*, a.qualified_name AS spec_q, b.qualified_name AS code_q FROM link_suggestions s"
        " JOIN nodes a ON a.epoch_id = s.epoch_id AND a.id = s.spec_node_id"
        " JOIN nodes b ON b.epoch_id = s.epoch_id AND b.id = s.code_node_id"
        " WHERE s.epoch_id = ? AND s.suggestion_id LIKE ?",
        (epoch_id, sid + "%"),
    ).fetchone()

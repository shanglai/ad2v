"""`ad2v_locate`: a question in natural language -> ranked node ids, deterministically (no LLM).

BM25F-lite: one BM25 index per field (P4's stdlib BM25 and tokenizer), a weighted sum over
fields, then multiplied by kind priors that the question's wording selects (ports and containers
for "where", behaviors for "risk", spec items for "requirement", …) and by a status boost when
the question names a status ("drifting", "missing", …).

The weights live in the rules file (`retrieval:`), so they are covered by `rules_hash`; a file
whose stored rules predate them uses the bundled rules (ADR-0043).
"""

from __future__ import annotations

import functools
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

from ad2v import rules as rules_mod
from ad2v import store
from ad2v.llm.suggest import BM25, STOPWORDS, stem
from ad2v.mcp.index import EpochIndex

_stem = functools.lru_cache(maxsize=None)(stem)


def tokens(text: str) -> list[str]:
    """ad2v.llm.suggest.tokens with a memoized stemmer (same output, ~10x faster on big repos)."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS and len(t) > 1]


FIELDS = ("name", "qname", "code", "spec", "summary", "narration")
STATUS_WORDS = {
    "drift": "drift",
    "drifting": "drift",
    "drifted": "drift",
    "missing": "missing",
    "unimplemented": "missing",
    "orphan": "orphan",
    "orphaned": "orphan",
    "unlinked": "orphan",
    "stale": "stale",
    "outdated": "stale",
    "verified": "verified",
    "tested": "verified",
    "review": "needs_review",
}
STATUS_STEMS = {stem(w): s for w, s in STATUS_WORDS.items()}  # "drifts", "drifting" -> drift


def _bundled_retrieval() -> dict[str, Any]:
    return rules_mod.load().get("retrieval") or {}


def retrieval_rules(conn: sqlite3.Connection, epoch_id: str) -> dict[str, Any]:
    """The `retrieval:` section of the rules this epoch was extracted with, else the bundled one."""
    try:
        rh = store.get_epoch(conn, epoch_id).rules_hash
        stored = store.load_rules(conn, rh).get("retrieval")
    except Exception:  # noqa: BLE001 - an old file without stored rules
        stored = None
    return stored or _bundled_retrieval()


@dataclass
class Locator:
    weights: dict[str, float]
    priors: dict[str, dict[str, Any]]
    status_boost: float
    prefix_min: int = 0
    k1_docs: dict[str, BM25] = field(default_factory=dict)
    kinds: dict[str, str] = field(default_factory=dict)
    status: dict[str, set[str]] = field(default_factory=dict)
    build_ms: float = 0.0

    def rank(
        self,
        question: str,
        k: int = 10,
        side: str | None = None,
        kind: str | None = None,
        ix: EpochIndex | None = None,
    ) -> list[dict[str, Any]]:
        q = tokens(question)
        words = set(question.lower().replace("?", " ").replace(",", " ").split())
        qset = set(q)
        if self.prefix_min:  # "night" also matches "nightly", "classifi" (classified) matches "classify"
            vocab = self._vocab()
            q = q + sorted(
                {v for t in qset if len(t) >= self.prefix_min for v in vocab if v != t and v.startswith(t)}
            )
        mult: dict[str, float] = {}
        fired: list[str] = []
        for name, p in self.priors.items():
            trig = set(p.get("triggers", []))
            if words & trig or qset & {tokens(t)[0] for t in trig if tokens(t)}:
                fired.append(name)
                for kd, m in (p.get("kinds") or {}).items():
                    mult[kd] = mult.get(kd, 1.0) * float(m)
        wanted_status = sorted({STATUS_STEMS[stem(w)] for w in words if stem(w) in STATUS_STEMS})
        scored: list[tuple[float, str, dict[str, float]]] = []
        for nid, kd in self.kinds.items():
            if kind and kd != kind:
                continue
            if side and ix is not None and ix.nodes[nid]["side"] != side:
                continue
            per: dict[str, float] = {}
            total = 0.0
            for f in FIELDS:
                w = self.weights.get(f, 0.0)
                bm = self.k1_docs.get(f)
                if not w or bm is None or nid not in bm.tf:
                    continue
                s = bm.score(q, nid)
                if s:
                    per[f] = round(s * w, 4)
                    total += s * w
            if wanted_status and self.status.get(nid, set()) & set(wanted_status):
                total = (total + 1.0) * self.status_boost
                per["status"] = self.status_boost
            if total <= 0:
                continue
            total *= mult.get(kd, 1.0)
            scored.append((round(total, 6), nid, per))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [
            {"id": nid, "score": s, "matched": sorted(per, key=lambda f: -per[f]), "intents": fired}
            for s, nid, per in scored[:k]
        ]

    def _vocab(self) -> list[str]:
        v = getattr(self, "_vocab_cache", None)
        if v is None:
            v = sorted({t for bm in self.k1_docs.values() for t in bm.idf})
            self._vocab_cache = v
        return v


def build(conn: sqlite3.Connection, ix: EpochIndex) -> Locator:
    t0 = time.perf_counter()
    cfg = retrieval_rules(conn, ix.epoch_id)
    docs: dict[str, dict[str, list[str]]] = {f: {} for f in FIELDS}
    code_lines = _code_heads(conn, ix)
    narr = _narrations_by_node(conn, ix)
    for nid, n in ix.nodes.items():
        a = ix.attrs.get(nid, {})
        docs["name"][nid] = tokens(n["name"] + " " + str(a.get("title", "")))
        docs["qname"][nid] = tokens(n["qname"].replace("/", " ").replace("::", " ").replace(".", " "))
        code = [
            str(a.get(k, ""))
            for k in ("path", "method", "command", "tool_name", "handler", "topic", "schedule")
        ]
        code += [str(t) for t in a.get("risk", [])] + [str(t) for t in a.get("touches", [])]
        code.append(code_lines.get(nid, ""))
        docs["code"][nid] = tokens(" ".join(code))
        if n["side"] == "spec":
            spec = [
                str(a.get(k, ""))
                for k in ("text", "response", "trigger", "system", "summary", "method", "path", "title")
            ]
            spec += [str(s) for s in a.get("steps", [])] if isinstance(a.get("steps"), list) else []
            docs["spec"][nid] = tokens(" ".join(spec))
        s = ix.summaries.get(nid)
        if s:
            docs["summary"][nid] = tokens(
                " ".join(x for x in (s.get("label"), s.get("card"), s.get("deep")) if x)
            )
        if nid in narr:
            docs["narration"][nid] = tokens(narr[nid])
    bms = {f: BM25({k: v for k, v in d.items() if v}) for f, d in docs.items() if any(d.values())}
    st: dict[str, set[str]] = {}
    for nid in ix.nodes:
        st[nid] = {ix.norm.get(nid, {}).get("status", "none"), ix.eff.get(nid, {}).get("status", "none")}
    loc = Locator(
        weights={k: float(v) for k, v in (cfg.get("field_weights") or {}).items()},
        priors=cfg.get("intents") or {},
        status_boost=float(cfg.get("status_boost", 2.0)),
        prefix_min=int(cfg.get("prefix_min", 0)),
        k1_docs=bms,
        kinds={nid: n["kind"] for nid, n in ix.nodes.items()},
        status=st,
    )
    loc.build_ms = (time.perf_counter() - t0) * 1000
    return loc


def _code_heads(conn: sqlite3.Connection, ix: EpochIndex, max_lines: int = 12) -> dict[str, str]:
    """The def line and docstring (first lines of the span) of code nodes, and of port handlers."""
    by_q: dict[tuple[str, str], str] = {(n["kind"], n["qname"]): i for i, n in ix.nodes.items()}
    files: dict[str, list[str] | None] = {}
    module_hash = {  # one query, not one per module: `nodes` is a view over the version tables
        r["qualified_name"]: r["content_hash"]
        for r in conn.execute(
            "SELECT qualified_name, content_hash FROM nodes WHERE epoch_id = ? AND kind = 'module'",
            (ix.epoch_id,),
        )
    }

    def lines_of(path: str | None) -> list[str] | None:
        if path is None:
            return None
        if path not in files:
            h = module_hash.get(path)
            text = store.load_source(conn, h) if h else None
            files[path] = text.split("\n") if text is not None else None
        return files[path]

    out: dict[str, str] = {}
    for nid, n in ix.nodes.items():
        if (
            n["side"] != "code"
            or n["kind"] not in ("function", "class", "module")
            and not n["kind"].endswith(("_route", "_command", "_tool", "_consumer"))
        ):
            continue
        target = n
        h = ix.attrs.get(nid, {}).get("handler")
        if h:
            for kd in ("function", "module", "class"):
                t = by_q.get((kd, h))
                if t is not None:
                    target = ix.nodes[t]
                    break
        lines = lines_of(target["path"])
        s = target["spanStart"] or 1
        e = min(target["spanEnd"] or s, s + max_lines - 1)
        if lines is None:
            continue
        out[nid] = " ".join(lines[i - 1] for i in range(s, min(e, len(lines)) + 1))
    return out


def _narrations_by_node(conn: sqlite3.Connection, ix: EpochIndex) -> dict[str, str]:
    """Narration text attached to each workflow's entry node (informative text, BM25 only)."""
    out: dict[str, list[str]] = {}
    rows = conn.execute(
        "SELECT w.entry_node_id, n.text FROM narrations n JOIN workflows w"
        " ON w.epoch_id = n.epoch_id AND w.workflow_id = n.workflow_id WHERE n.epoch_id = ?"
        " ORDER BY w.entry_node_id, n.detail_level, n.span_start",
        (ix.epoch_id,),
    ).fetchall()
    for r in rows:
        out.setdefault(r["entry_node_id"], []).append(r["text"])
    return {k: " ".join(v) for k, v in out.items()}

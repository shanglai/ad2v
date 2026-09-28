"""Retrieval eval for the MCP tools, without an LLM (P6 §7, ADR-0043).

For each question in expected-questions.yaml, run the tool a model would call (`ad2v_locate`, or
`ad2v_status` / `ad2v_diff` when the question names a status or a diff), take the ranked node ids
and score them against the gold components: recall@5, MRR and nDCG@5 (binary relevance).

`tune()` searches the retrieval weights by deterministic coordinate descent on the questions that
are NOT held out; held-out questions are only ever scored.

    python -m ad2v.mcp.evaluate FILE QUESTIONS.yaml [--tune] [--json]
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path
from typing import Any

import yaml

from ad2v import ir
from ad2v.mcp import locate
from ad2v.mcp.files import FileSet
from ad2v.mcp.index import EpochIndex
from ad2v.mcp.protocol import Request
from ad2v.mcp.tools import Ctx, t_diff, t_status

K = 5
FIELD_VALUES = (0.0, 0.5, 1.0, 2.0, 3.0)
BOOST_VALUES = (1.5, 2.0, 3.0, 4.0)
SCALE_VALUES = (0.0, 1.0, 1.5, 2.0)


def load_questions(path: Path) -> list[dict[str, Any]]:
    return list(yaml.safe_load(Path(path).read_text(encoding="utf-8"))["questions"])


def resolve_gold(ix: EpochIndex, names: list[str]) -> list[str]:
    out = []
    for g in names:
        ids = ix.by_qname.get(g)
        if not ids and ":" in g and g.split(":", 1)[0] in ir.NODE_KINDS:
            kind, q = g.split(":", 1)
            ids = [i for i in ix.by_qname.get(q, []) if ix.nodes[i]["kind"] == kind]
        if not ids:
            raise KeyError(f"gold component not found: {g}")
        out.append(sorted(ids)[0])
    return out


def metrics(ranked: list[str], gold: list[str]) -> dict[str, float]:
    g = set(gold)
    top = ranked[:K]
    recall = len(g & set(top)) / len(g)
    rr = next((1.0 / (i + 1) for i, x in enumerate(ranked) if x in g), 0.0)
    dcg = sum(1.0 / math.log2(i + 2) for i, x in enumerate(top) if x in g)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(g), K)))
    return {"recall@5": recall, "mrr": rr, "ndcg@5": dcg / idcg}


def _mean(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {"recall@5": 0.0, "mrr": 0.0, "ndcg@5": 0.0, "n": 0}
    return {
        **{k: round(sum(r[k] for r in rows) / len(rows), 4) for k in ("recall@5", "mrr", "ndcg@5")},
        "n": len(rows),
    }


class Evaluator:
    def __init__(self, file: Path, questions: list[dict[str, Any]]) -> None:
        self.ctx = Ctx(FileSet(single=Path(file)))
        self.ix, self.conn = self.ctx.index({})
        self.loc = locate.build(self.conn, self.ix)
        self.base = locate.retrieval_rules(self.conn, self.ix.epoch_id)
        self.questions = questions
        self.gold = {q["id"]: resolve_gold(self.ix, q["gold"]) for q in questions}
        self._tool_cache: dict[str, list[str]] = {}

    def apply(self, cfg: dict[str, Any]) -> None:
        self.loc.weights = {k: float(v) for k, v in cfg["field_weights"].items()}
        self.loc.priors = cfg["intents"]
        self.loc.status_boost = float(cfg["status_boost"])
        self.loc.prefix_min = int(cfg.get("prefix_min", 0))

    def ranked(self, q: dict[str, Any], use_tool: bool) -> list[str]:
        tool = q.get("tool") or {}
        if use_tool and tool.get("name") in ("status", "diff"):
            if q["id"] not in self._tool_cache:
                self._tool_cache[q["id"]] = self._tool_rank(tool)
            return self._tool_cache[q["id"]]
        return [r["id"] for r in self.loc.rank(q["q"], 20, ix=self.ix)]

    def _tool_rank(self, tool: dict[str, Any]) -> list[str]:
        req = Request(0, "tools/call", {}, "", {}, modern=True)
        if tool["name"] == "status":
            sc = t_status(self.ctx, req, {"status": tool["status"], "limit": 50})["structuredContent"]
            return [n["id"] for n in sc["nodes"]]
        sc = t_diff(self.ctx, req, {"from": tool["from"], "to": tool["to"]})["structuredContent"]["diff"]
        names = [t["qualified_name"] for t in sc["status_transitions"]["nodes"]]
        for sec in ("added", "renamed", "modified"):
            names += [
                x.get("qualified_name") or x.get("to")
                for x in sc["nodes"].get(sec, [])
                if isinstance(x, dict)
            ]
        out: list[str] = []
        for nm in names:
            for i in self.ix.by_qname.get(nm or "", []):
                if i not in out:
                    out.append(i)
        return out

    def run(self, use_tool: bool = True, only: str | None = None) -> dict[str, Any]:
        per = []
        for q in self.questions:
            if only == "tune" and q.get("holdout"):
                continue
            if only == "holdout" and not q.get("holdout"):
                continue
            r = self.ranked(q, use_tool)
            m = metrics(r, self.gold[q["id"]])
            tool = (q.get("tool") or {}).get("name", "locate") if use_tool else "locate"
            per.append(
                {
                    "id": q["id"],
                    "type": q["type"],
                    "holdout": bool(q.get("holdout")),
                    "tool": tool,
                    **m,
                    "top": [self.ix.nodes[i]["qname"] for i in r[:K]],
                    "gold": q["gold"],
                }
            )
        by_type: dict[str, list[dict[str, float]]] = {}
        for p in per:
            by_type.setdefault(p["type"], []).append(p)
        return {
            "overall": _mean(per),
            "tuning_set": _mean([p for p in per if not p["holdout"]]),
            "held_out": _mean([p for p in per if p["holdout"]]),
            "by_type": {t: _mean(v) for t, v in sorted(by_type.items())},
            "questions": per,
        }

    def objective(self) -> float:
        m = self.run(use_tool=False, only="tune")["overall"]
        return round(m["recall@5"] + m["mrr"] + m["ndcg@5"], 6)

    def tune(self, passes: int = 3) -> dict[str, Any]:
        """Coordinate descent over field weights, the intent strength and the status boost.
        Deterministic: fixed value lists, fixed parameter order, ties keep the current value."""
        base_intents = copy.deepcopy(self.base["intents"])
        cfg = {
            "field_weights": dict(self.base["field_weights"]),
            "status_boost": self.base["status_boost"],
            "scale": 1.0,
        }

        def materialize(c: dict[str, Any]) -> dict[str, Any]:
            intents = copy.deepcopy(base_intents)
            for p in intents.values():
                p["kinds"] = {
                    k: round(1 + (float(m) - 1) * c["scale"], 4) for k, m in (p.get("kinds") or {}).items()
                }
            return {
                "field_weights": c["field_weights"],
                "status_boost": c["status_boost"],
                "prefix_min": self.base.get("prefix_min", 0),
                "intents": intents,
            }

        self.apply(materialize(cfg))
        best = self.objective()
        for _ in range(passes):
            changed = False
            for f in locate.FIELDS:
                for v in FIELD_VALUES:
                    trial = copy.deepcopy(cfg)
                    trial["field_weights"][f] = v
                    self.apply(materialize(trial))
                    s = self.objective()
                    if s > best + 1e-9:
                        best, cfg, changed = s, trial, True
            for key, values in (("status_boost", BOOST_VALUES), ("scale", SCALE_VALUES)):
                for v in values:
                    trial = {**copy.deepcopy(cfg), key: v}
                    self.apply(materialize(trial))
                    s = self.objective()
                    if s > best + 1e-9:
                        best, cfg, changed = s, trial, True
            if not changed:
                break
        final = materialize(cfg)
        self.apply(final)
        return {"objective": best, "retrieval": final, "scale": cfg["scale"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ad2v.mcp.evaluate")
    ap.add_argument("file")
    ap.add_argument("questions")
    ap.add_argument("--tune", action="store_true", help="tune weights on the non-held-out questions")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    ev = Evaluator(Path(a.file), load_questions(Path(a.questions)))
    before = {"locate_only": ev.run(use_tool=False), "with_tools": ev.run(use_tool=True)}
    out: dict[str, Any] = {"before": before, "rules": ev.base}
    if a.tune:
        t = ev.tune()
        out["tuned"] = t
        out["after"] = {"locate_only": ev.run(use_tool=False), "with_tools": ev.run(use_tool=True)}
    if a.json:
        json.dump(out, sys.stdout, indent=1)
        return 0
    for label in ("before", "after"):
        if label not in out:
            continue
        for mode, r in out[label].items():
            print(
                f"{label} / {mode}: overall {r['overall']}  tuning {r['tuning_set']}  held-out "
                f"{r['held_out']}"
            )
            for t, m in r["by_type"].items():
                print(f"    {t:12} {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

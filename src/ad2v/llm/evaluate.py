"""`ad2v llm eval`: judge agreement with human labels (format spec §11.4).

Per run: accuracy, a confusion matrix (human label × verdict), Cohen's κ, and the validity rate;
an invalid result counts as `cannot_tell`. Across two or more runs: stability, the share of
labeled links whose verdict is identical in every run.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from ad2v.llm.judge import VERDICTS


def load_expected(path: Path) -> dict[str, str]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out = {}
    for e in data.get("links", []):
        if e["label"] not in VERDICTS:
            raise ValueError(f"label must be one of {VERDICTS}: {e}")
        out[f"{e['spec']} -> {e['code']}"] = e["label"]
    return out


def judge_runs(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT r.run_id, u.started_at FROM llm_run_results r"
        " JOIN llm_results x ON x.result_id = r.result_id JOIN llm_runs u ON u.run_id = r.run_id"
        " WHERE x.task = 'judge' ORDER BY u.started_at, r.run_id"
    ).fetchall()
    return [r[0] for r in rows]


def verdicts(conn: sqlite3.Connection, run_id: str) -> dict[str, tuple[str, bool, float]]:
    out = {}
    for subject, output, valid in conn.execute(
        "SELECT x.subject, x.output_json, x.valid FROM llm_run_results r JOIN llm_results x"
        " ON x.result_id = r.result_id WHERE r.run_id = ? AND x.task = 'judge' ORDER BY x.seq",
        (run_id,),
    ):
        o = json.loads(output) if output else {}
        v = o.get("verdict", "cannot_tell") if valid else "cannot_tell"
        out[subject] = (v, bool(valid), float(o.get("confidence", 0.0)) if valid else 0.0)
    return out


def kappa(pairs: list[tuple[str, str]]) -> float | None:
    n = len(pairs)
    if n == 0:
        return None
    po = sum(a == b for a, b in pairs) / n
    pe = sum((sum(a == c for a, _ in pairs) / n) * (sum(b == c for _, b in pairs) / n) for c in VERDICTS)
    return round((po - pe) / (1 - pe), 4) if pe < 1 else (1.0 if po == 1 else 0.0)


def evaluate(
    conn: sqlite3.Connection, expected: dict[str, str], run_ids: list[str] | None = None
) -> dict[str, Any]:
    runs = run_ids or judge_runs(conn)
    per_run = []
    all_v: dict[str, dict[str, str]] = {}
    for rid in runs:
        got = verdicts(conn, rid)
        pairs = [(expected[s], got[s][0]) for s in sorted(expected) if s in got]
        matrix = {h: {p: 0 for p in VERDICTS} for h in VERDICTS}
        for h, p in pairs:
            matrix[h][p] += 1
        labeled = [s for s in expected if s in got]
        per_run.append(
            {
                "run_id": rid,
                "labeled_links_judged": len(pairs),
                "labeled_links_missing": sorted(s for s in expected if s not in got),
                "accuracy": round(sum(h == p for h, p in pairs) / len(pairs), 4) if pairs else None,
                "kappa": kappa(pairs),
                "validity_rate": round(sum(got[s][1] for s in labeled) / len(labeled), 4)
                if labeled
                else None,
                "confusion": matrix,
                "per_link": {
                    s: {
                        "human": expected[s],
                        "verdict": got[s][0],
                        "valid": got[s][1],
                        "confidence": got[s][2],
                    }
                    for s in sorted(labeled)
                },
            }
        )
        all_v[rid] = {s: got[s][0] for s in labeled}
    stability = None
    if len(runs) >= 2:
        common = set.intersection(*(set(v) for v in all_v.values())) if all_v else set()
        same = [s for s in common if len({all_v[r][s] for r in runs}) == 1]
        stability = {
            "runs": runs,
            "links": len(common),
            "identical": len(same),
            "rate": round(len(same) / len(common), 4) if common else None,
        }
    return {"runs": per_run, "stability": stability}

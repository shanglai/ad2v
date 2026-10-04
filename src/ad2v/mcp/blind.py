"""Blind retrieval eval (P8 M2): aggregates only, never a question, a gold id or a per-question row.

The blind question set lives OUTSIDE the repository, at the path in the environment variable
`AD2V_BLIND_EVAL` (one YAML file, or a directory whose `*.yaml` / `*.yml` files are all read). Its
author keeps it private; this runner is built so that nothing it prints or writes can leak it:

- output = counts, SHA-256 of the blind file(s) and of the maps, and aggregate metrics (MRR,
  recall@5, nDCG@5) with bootstrap 95% confidence intervals (percentile method, 2,000 resamples,
  `random.Random(987654)`);
- per-type aggregates only for types with at least `MIN_GROUP` questions (smaller groups would
  approximate per-question scores);
- errors are sanitized: YAML errors report a line number, invalid questions and unknown gold
  components are counted, never quoted; map names and file names are never printed.

File schema (see fixtures/retrieval-eval/blind-template.yaml and docs/blind-eval.md):

    ad2v_blind_eval: 1
    maps: {<label>: <path to .ad2v, relative to this file or absolute>}
    questions:
      - {id: <str>, map: <label>, type: <str>, q: <question>, gold: [<qualified name>, ...],
         tool: {name: status, status: drift}}   # tool optional, as in expected-questions.yaml

    ad2v eval blind [--json] [--out FILE]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from pathlib import Path
from typing import Any

import yaml

ENV = "AD2V_BLIND_EVAL"
SEED = 987654
RESAMPLES = 2000
MIN_GROUP = 5
METRICS = ("mrr", "recall@5", "ndcg@5")
SCHEMA_VERSION = 1


class BlindEvalError(ValueError):
    """A sanitized error: its message never contains question text, gold ids or names."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def blind_files(location: str | os.PathLike[str] | None = None) -> list[Path]:
    raw = location if location is not None else os.environ.get(ENV)
    if not raw:
        raise BlindEvalError(f"set {ENV} to the blind question file or directory")
    p = Path(raw)
    if p.is_file():
        return [p]
    if p.is_dir():
        files = sorted([*p.glob("*.yaml"), *p.glob("*.yml")])
        if not files:
            raise BlindEvalError(f"{ENV} is a directory without *.yaml files")
        return files
    raise BlindEvalError(f"{ENV} does not point to a file or directory")


def _load(path: Path, index: int) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" near line {mark.line + 1}" if mark is not None else ""
        raise BlindEvalError(f"blind file #{index + 1}: invalid YAML{where}") from None
    except UnicodeDecodeError:
        raise BlindEvalError(f"blind file #{index + 1}: not UTF-8") from None
    if not isinstance(data, dict) or data.get("ad2v_blind_eval") != SCHEMA_VERSION:
        raise BlindEvalError(f"blind file #{index + 1}: missing `ad2v_blind_eval: {SCHEMA_VERSION}`")
    return data


def _valid(q: Any, maps: dict[str, Path]) -> bool:
    return (
        isinstance(q, dict)
        and isinstance(q.get("id"), str)
        and isinstance(q.get("q"), str)
        and isinstance(q.get("type"), str)
        and q.get("map") in maps
        and isinstance(q.get("gold"), list)
        and bool(q["gold"])
        and all(isinstance(g, str) for g in q["gold"])
    )


def bootstrap_ci(values: list[float], rng: random.Random, n: int = RESAMPLES) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    k = len(values)
    means = sorted(sum(values[rng.randrange(k)] for _ in range(k)) / k for _ in range(n))
    lo = means[int(0.025 * (n - 1))]
    hi = means[int(round(0.975 * (n - 1)))]
    return (round(lo, 4), round(hi, 4))


def run(location: str | os.PathLike[str] | None = None, use_tool: bool = True) -> dict[str, Any]:
    """Score the blind set; return aggregates only (safe to print or write)."""
    from ad2v.mcp.evaluate import Evaluator, metrics, resolve_gold

    files = blind_files(location)
    maps: dict[str, Path] = {}
    questions: list[dict[str, Any]] = []
    invalid = 0
    for i, f in enumerate(files):
        data = _load(f, i)
        for label, rel in sorted((data.get("maps") or {}).items()):
            mp = Path(str(rel))
            mp = mp if mp.is_absolute() else (f.parent / mp)
            if str(label) in maps and maps[str(label)] != mp:
                raise BlindEvalError(
                    f"blind file #{i + 1}: a map label is defined twice with different paths"
                )
            maps[str(label)] = mp
        for q in data.get("questions") or []:
            if _valid(q, maps):
                questions.append(q)
            else:
                invalid += 1
    missing_maps = sum(1 for p in maps.values() if not p.is_file())
    if missing_maps:
        raise BlindEvalError(f"{missing_maps} map file(s) not found (paths are relative to the blind file)")
    ids = [q["id"] for q in questions]
    if len(set(ids)) != len(ids):
        raise BlindEvalError("question ids are not unique")
    rows: list[dict[str, Any]] = []  # in memory only
    unresolved = failed = 0
    for n, label in enumerate(sorted({q["map"] for q in questions})):
        try:
            ev = Evaluator(maps[label], [])
        except Exception:  # noqa: BLE001 - the message could name the map; say only which ordinal
            raise BlindEvalError(f"map #{n + 1} could not be opened as an .ad2v file") from None
        for q in (x for x in questions if x["map"] == label):
            try:
                gold = resolve_gold(ev.ix, q["gold"])
            except KeyError:
                unresolved += 1
                continue
            try:
                m = metrics(ev.ranked(q, use_tool), gold)
            except Exception:  # noqa: BLE001 - never echo a question through an exception
                failed += 1
                continue
            rows.append({"type": q["type"], **m})
    rng = random.Random(SEED)
    agg: dict[str, Any] = {}
    for k in METRICS:
        vals = [r[k] for r in rows]
        mean = round(sum(vals) / len(vals), 4) if vals else 0.0
        agg[k] = {"mean": mean, "ci95": list(bootstrap_ci(vals, rng))}
    by_type: dict[str, Any] = {}
    suppressed = 0
    for t in sorted({r["type"] for r in rows}):
        group = [r for r in rows if r["type"] == t]
        if len(group) < MIN_GROUP:
            suppressed += 1
            continue
        by_type[t] = {
            "n": len(group),
            **{k: round(sum(r[k] for r in group) / len(group), 4) for k in METRICS},
        }
    from ad2v import __version__

    return {
        "ad2v_version": __version__,
        "blind_set": {
            "files": len(files),
            "sha256": [_sha256(f) for f in files],
            "maps": len(maps),
            "maps_sha256": sorted(_sha256(p) for p in maps.values()),
        },
        "questions": {
            "scored": len(rows),
            "invalid": invalid,
            "gold_not_found": unresolved,
            "failed": failed,
        },
        "method": {
            "tools": "locate, plus status/diff when a question names that tool"
            if use_tool
            else "locate only",
            "k": 5,
            "bootstrap": {"resamples": RESAMPLES, "seed": SEED, "interval": "percentile 95%"},
            "min_group": MIN_GROUP,
        },
        "metrics": agg,
        "by_type": by_type,
        "types_suppressed": suppressed,
    }


def format_text(r: dict[str, Any]) -> str:
    b, q = r["blind_set"], r["questions"]
    lines = [
        f"ad2v {r['ad2v_version']} blind retrieval eval: {q['scored']} question(s) scored"
        f" on {b['maps']} map(s) ({b['files']} file(s); {q['invalid']} invalid,"
        f" {q['gold_not_found']} with gold not found, {q['failed']} failed)",
        "blind file sha256: " + ", ".join(b["sha256"]),
    ]
    for k in METRICS:
        m = r["metrics"][k]
        lines.append(f"  {k:9s} {m['mean']:.4f}  95% CI [{m['ci95'][0]:.4f}, {m['ci95'][1]:.4f}]")
    for t, m in r["by_type"].items():
        lines.append(f"  type {t}: n={m['n']} " + " ".join(f"{k} {m[k]:.4f}" for k in METRICS))
    if r["types_suppressed"]:
        lines.append(f"  ({r['types_suppressed']} type(s) with fewer than {MIN_GROUP} questions not shown)")
    return "\n".join(lines) + "\n"


def cmd_blind(a: argparse.Namespace) -> int:
    try:
        r = run(use_tool=not a.locate_only)
    except BlindEvalError as e:
        sys.stderr.write(f"ad2v: blind eval: {e}\n")
        return 2
    text = json.dumps(r, indent=2, sort_keys=True) + "\n" if a.json else format_text(r)
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(text)
    return 0


def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    ev = sub.add_parser("eval", help="evaluations that print aggregates only")
    es = ev.add_subparsers(dest="eval_cmd", required=True)
    b = es.add_parser("blind", help=f"blind retrieval eval of the question set at ${ENV} (aggregates only)")
    b.add_argument("--json", action="store_true")
    b.add_argument("--out", help="also write the aggregate JSON to this file")
    b.add_argument(
        "--locate-only", action="store_true", help="score ad2v_locate alone (no status/diff tools)"
    )
    b.set_defaults(func=cmd_blind)

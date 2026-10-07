"""Aggregate counts of a .ad2v map for the dogfood results table (docs/dogfood.md).

Prints numbers only: no node names, paths, spec text or ids, so the output is safe to share.

    python scripts/dogfood_counts.py <map.ad2v> [--json]
"""

from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path


def counts(path: Path) -> dict:
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        head = meta["head_epoch"]
        q = conn.execute
        kinds = collections.Counter(k for (k,) in q("SELECT kind FROM nodes WHERE epoch_id = ?", (head,)))
        status = collections.Counter(
            f"{side}:{st}"
            for side, st in q(
                "SELECT n.side, s.status FROM node_status s JOIN nodes n"
                " ON n.epoch_id = s.epoch_id AND n.id = s.node_id WHERE s.epoch_id = ?",
                (head,),
            )
        )
        routes = kinds.get("http_route", 0)
        unresolved = q(
            "SELECT COUNT(*) FROM nodes WHERE epoch_id = ? AND kind = 'http_route'"
            " AND attrs_json LIKE '%\"path_unresolved\":true%'",
            (head,),
        ).fetchone()[0]
        links = collections.Counter(
            f"{m}:{st}" for m, st in q("SELECT method, status FROM links WHERE epoch_id = ?", (head,))
        )
        risky = q(
            'SELECT COUNT(*) FROM nodes WHERE epoch_id = ? AND attrs_json LIKE \'%"risk":["%\'', (head,)
        ).fetchone()[0]
        epochs = q("SELECT COUNT(*) FROM epochs").fetchone()[0]
        unres_refs = q("SELECT COUNT(*) FROM unresolved_refs WHERE epoch_id = ?", (head,)).fetchone()[0]
        modules = kinds.get("module", 0)
        loc = q(
            "SELECT COALESCE(SUM(span_end_line), 0) FROM nodes"
            " WHERE epoch_id = ? AND kind = 'module' AND side = 'code'",
            (head,),
        ).fetchone()[0]
        # P8.1 (ADR-0066): code no active extractor reads, by language (status not_evaluable)
        unextracted: collections.Counter[str] = collections.Counter()
        for (raw,) in q(
            "SELECT attrs_json FROM nodes WHERE epoch_id = ? AND kind = 'module'"
            " AND attrs_json LIKE '%\"extracted\":false%'",
            (head,),
        ):
            unextracted[str(json.loads(raw).get("language"))] += 1
        return {
            "format_version": meta.get("format_version"),
            "unextracted_files_by_language": dict(sorted(unextracted.items())),
            "epochs": epochs,
            "code_files": modules,
            "code_lines": loc,
            "nodes_by_kind": dict(sorted(kinds.items())),
            "status_by_side": dict(sorted(status.items())),
            "links_by_method_status": dict(sorted(links.items())),
            "http_routes": routes,
            "http_routes_path_unresolved": unresolved,
            "risky_nodes": risky,
            "unresolved_spec_refs": unres_refs,
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    c = counts(Path(a.map))
    if a.json:
        print(json.dumps(c, indent=2))
        return 0
    for k, v in c.items():
        if isinstance(v, dict):
            print(f"{k}:")
            for kk, vv in v.items():
                print(f"  {kk:32s} {vv}")
        else:
            print(f"{k:34s} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

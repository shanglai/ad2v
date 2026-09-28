"""SQLite writer/reader for .ad2v files."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ad2v import __version__, ids, ir
from ad2v import workflows as wf_mod
from ad2v.resources import ddl_path

if TYPE_CHECKING:
    from ad2v.pairing import PairingResult

GENERATOR = "ad2v-reference"

# Columns that never enter the canonical dump (wall-clock, environment-dependent).
EXCLUDED_COLUMNS = frozenset({"created_at"})
INFORMATIVE_META_KEYS = frozenset({"created_at", "generator", "generator_version", "repo_root_name"})


@dataclass
class Epoch:
    epoch_id: str
    repo_tree_hash: str
    spec_tree_hash: str
    rules_hash: str
    config_hash: str = ids.sha256_hex(ids.canonical_json({}))
    test_results_hash: str = ids.tree_hash({})
    parent_epoch_id: str | None = None
    repo_commit: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


class NotAnAd2vFile(ValueError):
    pass


def connect(path: Path) -> sqlite3.Connection:
    """Read-write connection (creates the file). Used by the writer and by tests."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def open_readonly(path: Path) -> sqlite3.Connection:
    """Open an existing .ad2v file read-only; never creates a file."""
    path = Path(path)
    if not path.is_file():
        raise NotAnAd2vFile(f"no such file: {path}")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("SELECT value FROM meta WHERE key = 'format_version'").fetchone()
    except sqlite3.DatabaseError as e:
        conn.close()
        raise NotAnAd2vFile(f"not an ad2v file: {path} ({e})") from e
    return conn


def write(
    out: Path,
    graph: ir.Graph,
    epoch: Epoch,
    glyphs: list[ir.Glyph],
    workflows: list[ir.Workflow],
    meta: dict[str, str],
    pairing_result: PairingResult | None = None,
    test_results: list[ir.TestResult] | None = None,
) -> None:
    """Write a complete .ad2v file (replaces `out` if it exists)."""
    out = Path(out)
    if out.exists():
        out.unlink()
    conn = connect(out)
    try:
        conn.executescript(ddl_path().read_text(encoding="utf-8"))
        with conn:
            conn.execute("PRAGMA defer_foreign_keys = ON")
            all_meta = {
                "format_version": ir.FORMAT_VERSION,
                "generator": GENERATOR,
                "generator_version": __version__,
                "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                **meta,
            }
            conn.executemany(
                "INSERT INTO meta(key, value, class) VALUES (?, ?, ?)",
                [(k, v, "I" if k in INFORMATIVE_META_KEYS else "N") for k, v in sorted(all_meta.items())],
            )
            conn.execute(
                "INSERT INTO epochs(epoch_id, parent_epoch_id, repo_commit, repo_tree_hash, spec_tree_hash,"
                " rules_hash, config_hash, test_results_hash, attrs_json, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    epoch.epoch_id,
                    epoch.parent_epoch_id,
                    epoch.repo_commit,
                    epoch.repo_tree_hash,
                    epoch.spec_tree_hash,
                    epoch.rules_hash,
                    epoch.config_hash,
                    epoch.test_results_hash,
                    ids.canonical_json(epoch.attrs),
                    all_meta["created_at"],
                ),
            )
            e = epoch.epoch_id
            conn.executemany(
                "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        e,
                        n.id,
                        n.side,
                        n.kind,
                        n.name,
                        n.qualified_name,
                        n.parent_id,
                        n.path,
                        n.span_start_line,
                        n.span_end_line,
                        n.content_hash,
                        n.subtree_hash,
                        n.level_hint,
                        ids.canonical_json(n.attrs),
                        ids.canonical_json(sorted(set(n.spec_ref))),
                    )
                    for _, n in sorted(graph.nodes.items())
                ],
            )
            conn.executemany(
                "INSERT INTO edges(epoch_id, src, dst, kind, weight, attrs_json, provenance)"
                " VALUES (?,?,?,?,?,?,?)",
                [
                    (e, ed.src, ed.dst, ed.kind, ed.weight, ids.canonical_json(ed.attrs), ed.provenance)
                    for _, ed in sorted(graph.edges.items())
                ],
            )
            conn.executemany(
                "INSERT INTO unresolved_refs VALUES (?,?,?,?,?)",
                sorted({(e, u.src, u.ref, u.ref_kind, u.reason) for u in graph.unresolved}),
            )
            conn.executemany(
                "INSERT INTO glyphs VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        e,
                        g.node_id,
                        g.base_shape,
                        g.variant,
                        ids.canonical_json(g.modifiers),
                        g.size_weight,
                        int(g.has_interior),
                    )
                    for g in sorted(glyphs, key=lambda g: g.node_id)
                ],
            )
            for wf in sorted(workflows, key=lambda w: w.workflow_id):
                conn.execute(
                    "INSERT INTO workflows(epoch_id, workflow_id, name, side, entry_node_id, scenario_id,"
                    " source, attrs_json) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        e,
                        wf.workflow_id,
                        wf.name,
                        wf.side,
                        wf.entry_node_id,
                        wf.scenario_id,
                        wf.source,
                        ids.canonical_json(wf.attrs),
                    ),
                )
                conn.executemany(
                    "INSERT INTO workflow_steps VALUES (?,?,?,?,?)",
                    [(e, wf.workflow_id, s.seq, ids.canonical_json(s.node_ids), s.depth) for s in wf.steps],
                )
            conn.executemany(
                "INSERT INTO workflow_step_nodes VALUES (?,?,?,?)",
                [(e, w, seq, n) for w, seq, n in wf_mod.step_nodes(workflows)],
            )
            conn.executemany(
                "INSERT INTO test_results VALUES (?,?,?,?,?)",
                sorted(
                    (e, t.test_node_id, t.outcome, t.source_file, t.duration_ms) for t in test_results or []
                ),
            )
            if pairing_result is not None:
                _write_pairing(conn, e, pairing_result)
    finally:
        conn.close()


def _write_pairing(conn: sqlite3.Connection, e: str, res: PairingResult) -> None:
    conn.executemany(
        "INSERT INTO links(epoch_id, link_id, spec_node_id, code_node_id, method, status, provenance,"
        " evidence_json, confidence) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (
                e,
                lk.link_id,
                lk.spec_node_id,
                lk.code_node_id,
                lk.method,
                lk.status,
                lk.provenance,
                ids.canonical_json(lk.evidence),
                lk.confidence,
            )
            for lk in sorted(res.links, key=lambda x: x.link_id)
        ],
    )
    precedence = list(ir.STATUS_PRECEDENCE)
    conn.executemany(
        "INSERT INTO node_status VALUES (?,?,?,?)",
        [
            (e, nid, st.status, ids.canonical_json({"precedence": precedence, "reasons": st.reasons}))
            for nid, st in sorted(res.statuses.items())
        ],
    )
    conn.executemany(
        "INSERT INTO status_rollup VALUES (?,?,?)",
        [(e, nid, ids.canonical_json(c)) for nid, c in sorted(res.rollup.items())],
    )


def read_meta(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [r["name"] for r in rows]


def primary_key(conn: sqlite3.Connection, table: str) -> list[str]:
    info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    pk = sorted((r["pk"], r["name"]) for r in info if r["pk"] > 0)
    return [name for _, name in pk] or [r["name"] for r in info]


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]

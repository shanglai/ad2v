"""SQLite storage for .ad2v files, format v0.4 (multi-epoch, content-addressed base facts).

Base facts (nodes, edges, unresolved refs, test results, code facts) are stored once per
distinct content in `*_versions` tables and referenced per epoch. Readers use the v0.2-shaped
views `nodes`, `edges`, `unresolved_refs`, `test_results`. Derived tables hold rows only for
materialized epochs (see `ad2v.materialize`).
"""

from __future__ import annotations

import json
import sqlite3
import zlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ad2v import __version__, ids, ir
from ad2v import workflows as wf_mod
from ad2v.extract.code.base import CodeFacts, Event
from ad2v.resources import ddl_path

if TYPE_CHECKING:
    from ad2v.pairing import PairingResult

GENERATOR = "ad2v-reference"

# Columns that never enter the canonical dump (wall-clock, environment-dependent).
EXCLUDED_COLUMNS = frozenset({"created_at"})
INFORMATIVE_META_KEYS = frozenset({"created_at", "generator", "generator_version", "repo_root_name"})
# Physical storage tables: hidden from dumps (dedup is invisible), reached through views.
PHYSICAL_TABLES = frozenset(
    {
        "node_versions",
        "epoch_nodes",
        "edge_versions",
        "epoch_edges",
        "unresolved_ref_versions",
        "epoch_unresolved_refs",
        "test_result_versions",
        "epoch_test_results",
        "code_fact_versions",
        "epoch_code_facts",
        "rules_versions",
        "config_versions",
        "parse_cache",
        "epoch_materialized",
        "source_blobs",
        "llm_results",
        "llm_runs",
        "llm_run_results",
        "layout_grids",
    }
)
# Informative per-epoch rows built from the LLM cache (P4). Dropped with the derived rows (and
# before them: they reference links and workflows), rebuilt from `llm_results` without calls.
LLM_DERIVED_TABLES = ("link_judgments", "link_suggestions", "spec_extractions", "narrations", "summaries")
VIEWS = ("nodes", "edges", "unresolved_refs", "test_results")
DERIVED_TABLES = (
    "glyphs",
    "workflows",
    "workflow_steps",
    "workflow_step_nodes",
    "links",
    "node_status",
    "status_rollup",
)
# Delete order respecting foreign keys.
DERIVED_DELETE_ORDER = (
    "workflow_step_nodes",
    "workflow_steps",
    "workflows",
    "glyphs",
    "links",
    "node_status",
    "status_rollup",
)
CHANGE_KINDS = ("initial", "code", "spec", "code+spec", "rules", "config", "tests_only", "mixed")


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
    change_kind: str = "initial"
    seq: int = 1
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def input_hashes(self) -> tuple[str, str, str, str, str]:
        return (
            self.repo_tree_hash,
            self.spec_tree_hash,
            self.rules_hash,
            self.config_hash,
            self.test_results_hash,
        )


def change_kind(parent: Epoch | None, e: Epoch) -> str:
    """Which inputs changed relative to the parent (format spec §5.1)."""
    if parent is None:
        return "initial"
    names = ("code", "spec", "rules", "config", "tests")
    changed = {n for n, a, b in zip(names, parent.input_hashes, e.input_hashes, strict=True) if a != b}
    table = {
        frozenset({"code"}): "code",
        frozenset({"spec"}): "spec",
        frozenset({"code", "spec"}): "code+spec",
        frozenset({"rules"}): "rules",
        frozenset({"config"}): "config",
        frozenset({"tests"}): "tests_only",
    }
    return table.get(frozenset(changed), "mixed")


class NotAnAd2vFile(ValueError):
    pass


# ---------------------------------------------------------------------------------------------
# connections
# ---------------------------------------------------------------------------------------------


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


def open_rw(path: Path) -> sqlite3.Connection:
    """Open an existing .ad2v file for writing (never creates it)."""
    path = Path(path)
    if not path.is_file():
        raise NotAnAd2vFile(f"no such file: {path}")
    conn = connect(path)
    try:
        version = conn.execute("SELECT value FROM meta WHERE key = 'format_version'").fetchone()
    except sqlite3.DatabaseError as e:
        conn.close()
        raise NotAnAd2vFile(f"not an ad2v file: {path} ({e})") from e
    if version is None or version[0] != ir.FORMAT_VERSION:
        conn.close()
        raise NotAnAd2vFile(
            f"{path} has format {version[0] if version else '?'}; appending needs {ir.FORMAT_VERSION}"
            " (re-extract with --out to start a new file)"
        )
    from ad2v import layout  # v0.4 files written before P5 lack the additive layout_grids table

    conn.executescript(layout.DDL)
    return conn


def create(path: Path) -> sqlite3.Connection:
    path = Path(path)
    if path.exists():
        path.unlink()
    conn = connect(path)
    conn.executescript(ddl_path().read_text(encoding="utf-8"))
    set_meta(
        conn,
        {
            "format_version": ir.FORMAT_VERSION,
            "generator": GENERATOR,
            "generator_version": __version__,
        },
    )
    conn.commit()
    return conn


def set_meta(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    conn.executemany(
        "INSERT INTO meta(key, value, class) VALUES (?, ?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value, class = excluded.class",
        [(k, v, "I" if k in INFORMATIVE_META_KEYS else "N") for k, v in sorted(values.items())],
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


# ---------------------------------------------------------------------------------------------
# epochs
# ---------------------------------------------------------------------------------------------


def _epoch_from_row(r: sqlite3.Row) -> Epoch:
    return Epoch(
        epoch_id=r["epoch_id"],
        repo_tree_hash=r["repo_tree_hash"],
        spec_tree_hash=r["spec_tree_hash"],
        rules_hash=r["rules_hash"],
        config_hash=r["config_hash"],
        test_results_hash=r["test_results_hash"],
        parent_epoch_id=r["parent_epoch_id"],
        repo_commit=r["repo_commit"],
        change_kind=r["change_kind"],
        seq=r["seq"],
        attrs=json.loads(r["attrs_json"]),
    )


def head_epoch(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = 'head_epoch'").fetchone()
    return row[0] if row else None


def get_epoch(conn: sqlite3.Connection, epoch_id: str) -> Epoch:
    r = conn.execute("SELECT * FROM epochs WHERE epoch_id = ?", (epoch_id,)).fetchone()
    if r is None:
        raise KeyError(epoch_id)
    return _epoch_from_row(r)


def get_epoch_or_none(conn: sqlite3.Connection, epoch_id: str) -> Epoch | None:
    try:
        return get_epoch(conn, epoch_id)
    except KeyError:
        return None


def epoch_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM epochs ORDER BY seq").fetchall()


def resolve_epoch(conn: sqlite3.Connection, ref: str | None) -> str:
    """Epoch by id, 'head', 'parent' (of head), label, or commit (prefix, >= 7 chars)."""
    head = head_epoch(conn)
    if ref in (None, "", "head"):
        if head is None:
            raise KeyError("file has no epochs")
        return head
    if ref == "parent":
        if head is None:
            raise KeyError("file has no epochs")
        parent = get_epoch(conn, head).parent_epoch_id
        if parent is None:
            raise KeyError("head has no parent epoch")
        return parent
    rows = epoch_rows(conn)
    for r in rows:
        if r["epoch_id"] == ref or r["label"] == ref:
            return r["epoch_id"]
    matches = [
        r["epoch_id"] for r in rows if r["repo_commit"] and len(ref) >= 7 and r["repo_commit"].startswith(ref)
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise KeyError(f"commit prefix {ref!r} matches {len(matches)} epochs")
    raise KeyError(f"no epoch matches {ref!r}")


def insert_epoch(
    conn: sqlite3.Connection, e: Epoch, rules: dict[str, Any], config_json: dict[str, Any]
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO rules_versions VALUES (?, ?)",
        (e.rules_hash, ids.canonical_json({k: v for k, v in rules.items() if not k.startswith("_")})),
    )
    conn.execute(
        "INSERT OR IGNORE INTO config_versions VALUES (?, ?)",
        (e.config_hash, ids.canonical_json(config_json)),
    )
    conn.execute(
        "INSERT INTO epochs(epoch_id, parent_epoch_id, seq, repo_commit, repo_tree_hash, spec_tree_hash,"
        " rules_hash, config_hash, test_results_hash, change_kind, attrs_json, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            e.epoch_id,
            e.parent_epoch_id,
            e.seq,
            e.repo_commit,
            e.repo_tree_hash,
            e.spec_tree_hash,
            e.rules_hash,
            e.config_hash,
            e.test_results_hash,
            e.change_kind,
            ids.canonical_json(e.attrs),
            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
    )


def load_rules(conn: sqlite3.Connection, rules_hash: str) -> dict[str, Any]:
    r = conn.execute("SELECT rules_json FROM rules_versions WHERE rules_hash = ?", (rules_hash,)).fetchone()
    rules = json.loads(r[0])
    rules["_hash"] = rules_hash
    return rules


def load_config_json(conn: sqlite3.Connection, config_hash: str) -> dict[str, Any]:
    r = conn.execute(
        "SELECT config_json FROM config_versions WHERE config_hash = ?", (config_hash,)
    ).fetchone()
    return json.loads(r[0])


# ---------------------------------------------------------------------------------------------
# base facts
# ---------------------------------------------------------------------------------------------


def _vkey(payload: Any) -> str:
    return "v_" + ids.sha256_hex(ids.canonical_json(payload))[: ids.ID_HEX_LEN]


def node_payload(n: ir.Node) -> dict[str, Any]:
    """Normative node payload (no volatile span lines): the version key's input."""
    return {
        "attrs": n.attrs,
        "content_hash": n.content_hash,
        "id": n.id,
        "kind": n.kind,
        "level_hint": n.level_hint,
        "name": n.name,
        "parent_id": n.parent_id,
        "path": n.path,
        "qualified_name": n.qualified_name,
        "side": n.side,
        "spec_ref": sorted(set(n.spec_ref)),
        "subtree_hash": n.subtree_hash,
    }


def edge_payload(e: ir.Edge) -> dict[str, Any]:
    attrs = {k: v for k, v in e.attrs.items() if k != "lines"}
    return {
        "attrs": attrs,
        "dst": e.dst,
        "kind": e.kind,
        "provenance": e.provenance,
        "src": e.src,
        "weight": e.weight,
    }


def _events_payload(evs: list[Event]) -> list[list[Any]]:
    # event lines are volatile and unused by traces: not stored
    return [[e.kind, list(e.targets), list(e.behaviors)] for e in evs]


NODE_VERSION_COLS = (
    "version_key, node_id, side, kind, name, qualified_name, parent_id, path, content_hash, subtree_hash,"
    " level_hint, attrs_json, spec_ref_json"
)


def _vids(conn: sqlite3.Connection, table: str, keys: Iterable[str]) -> dict[str, int]:
    """Surrogate ids of the given version keys (the rows must exist)."""
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _version_keys (k TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM temp._version_keys")
    conn.executemany("INSERT OR IGNORE INTO temp._version_keys VALUES (?)", ((k,) for k in keys))
    sql = f"SELECT v.version_key, v.vid FROM temp._version_keys k JOIN {table} v ON v.version_key = k.k"
    return dict(conn.execute(sql).fetchall())


def _add_versions(
    conn: sqlite3.Connection, table: str, cols: str, rows: list[tuple[Any, ...]]
) -> tuple[dict[str, int], int]:
    """Insert content-addressed rows (first column: version_key) unless present. Returns (vids, new rows)."""
    before = conn.total_changes
    marks = ",".join("?" for _ in cols.split(","))
    conn.executemany(f"INSERT OR IGNORE INTO {table}({cols}) VALUES ({marks})", rows)
    new = conn.total_changes - before
    return _vids(conn, table, (r[0] for r in rows)), new


def epoch_seq(conn: sqlite3.Connection, epoch_id: str) -> int:
    row = conn.execute("SELECT seq FROM epochs WHERE epoch_id = ?", (epoch_id,)).fetchone()
    if row is None:
        raise KeyError(f"no epoch {epoch_id!r}")
    return int(row[0])


def write_base(
    conn: sqlite3.Connection,
    epoch_id: str,
    graph: ir.Graph,
    facts: CodeFacts,
    tests: Iterable[ir.TestResult],
    lineage: Iterable[tuple[str, str, str, float]],
    link_state: Iterable[dict[str, Any]],
) -> dict[str, int]:
    """Write one epoch's base facts. Returns counts of new version rows (dedup statistics)."""
    stats = {}
    seq = epoch_seq(conn, epoch_id)
    node_rows, spans = [], []
    for nid in sorted(graph.nodes):
        n = graph.nodes[nid]
        p = node_payload(n)
        vk = _vkey(p)
        node_rows.append(
            (
                vk,
                n.id,
                n.side,
                n.kind,
                n.name,
                n.qualified_name,
                n.parent_id,
                n.path,
                n.content_hash,
                n.subtree_hash,
                n.level_hint,
                ids.canonical_json(n.attrs),
                ids.canonical_json(p["spec_ref"]),
            )
        )
        spans.append((vk, n.span_start_line, n.span_end_line))
    vids, stats["node_versions_new"] = _add_versions(conn, "node_versions", NODE_VERSION_COLS, node_rows)
    conn.executemany(
        "INSERT INTO epoch_nodes VALUES (?,?,?,?)", sorted((seq, vids[vk], a, b) for vk, a, b in spans)
    )

    edge_rows, elines = [], []
    for key in sorted(graph.edges):
        ed = graph.edges[key]
        p = edge_payload(ed)
        vk = _vkey(p)
        edge_rows.append(
            (vk, ed.src, ed.dst, ed.kind, ed.weight, ids.canonical_json(p["attrs"]), ed.provenance)
        )
        lines = ed.attrs.get("lines")
        elines.append((vk, ids.canonical_json(lines) if lines else None))
    vids, stats["edge_versions_new"] = _add_versions(
        conn, "edge_versions", "version_key, src, dst, kind, weight, attrs_json, provenance", edge_rows
    )
    conn.executemany(
        "INSERT INTO epoch_edges VALUES (?,?,?)", sorted((seq, vids[vk], ln) for vk, ln in elines)
    )

    urows = [
        (_vkey([src, ref, kind, reason]), src, ref, kind, reason)
        for src, ref, kind, reason in sorted({(u.src, u.ref, u.ref_kind, u.reason) for u in graph.unresolved})
    ]
    vids, _ = _add_versions(conn, "unresolved_ref_versions", "version_key, src, ref, ref_kind, reason", urows)
    conn.executemany(
        "INSERT INTO epoch_unresolved_refs VALUES (?,?)", sorted((seq, v) for v in vids.values())
    )

    trows = [
        (
            _vkey([t.test_node_id, t.outcome, t.source_file, t.duration_ms]),
            t.test_node_id,
            t.outcome,
            t.source_file,
            t.duration_ms,
        )
        for t in sorted(tests, key=lambda x: x.test_node_id)
    ]
    vids, _ = _add_versions(
        conn, "test_result_versions", "version_key, test_node_id, outcome, source_file, duration_ms", trows
    )
    conn.executemany("INSERT INTO epoch_test_results VALUES (?,?)", sorted((seq, v) for v in vids.values()))

    fact_rows: list[tuple[str, str, Any]] = []
    for sid, evs in sorted(facts.events.items()):
        fact_rows.append(("events", sid, _events_payload(evs)))
    for sid, ws in sorted(facts.wrappers.items()):
        fact_rows.append(("wrappers", sid, list(ws)))
    handlers: dict[str, list[str]] = {}
    for port, handler in sorted(facts.entry_ports):
        handlers.setdefault(port, []).append(handler)  # a port may be bound to several handlers
    for port, hs in sorted(handlers.items()):
        fact_rows.append(("entry", port, hs))
    frows = [(_vkey([k, sid, p]), k, sid, ids.canonical_json(p)) for k, sid, p in fact_rows]
    vids, _ = _add_versions(
        conn, "code_fact_versions", "version_key, fact_kind, subject_id, payload_json", frows
    )
    conn.executemany("INSERT INTO epoch_code_facts VALUES (?,?)", sorted((seq, v) for v in vids.values()))

    conn.executemany(
        "INSERT INTO id_lineage VALUES (?,?,?,?,?)",
        sorted((epoch_id, o, n, m, s) for o, n, m, s in lineage),
    )
    conn.executemany(
        "INSERT INTO link_state VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (
                epoch_id,
                s["link_id"],
                s["spec_node_id"],
                s["code_node_id"],
                s["method"],
                s["status"],
                ids.canonical_json(s["history"]),
                s["agreed_epoch_id"],
                s["agreed_spec_hash"],
                s["agreed_code_hash"],
            )
            for s in sorted(link_state, key=lambda x: x["link_id"])
        ],
    )
    return stats


def load_graph(conn: sqlite3.Connection, epoch_id: str) -> ir.Graph:
    g = ir.Graph()
    for r in conn.execute("SELECT * FROM nodes WHERE epoch_id = ? ORDER BY id", (epoch_id,)):
        n = ir.Node(
            side=r["side"],
            kind=r["kind"],
            name=r["name"],
            qualified_name=r["qualified_name"],
            parent_id=r["parent_id"],
            path=r["path"],
            span_start_line=r["span_start_line"],
            span_end_line=r["span_end_line"],
            content_hash=r["content_hash"],
            subtree_hash=r["subtree_hash"],
            level_hint=r["level_hint"],
            attrs=json.loads(r["attrs_json"]),
            spec_ref=json.loads(r["spec_ref_json"]),
        )
        g.nodes[n.id] = n
    for r in conn.execute("SELECT * FROM edges WHERE epoch_id = ? ORDER BY src, kind, dst", (epoch_id,)):
        g.edges[(r["src"], r["kind"], r["dst"])] = ir.Edge(
            src=r["src"],
            dst=r["dst"],
            kind=r["kind"],
            weight=r["weight"],
            attrs=json.loads(r["attrs_json"]),
            provenance=r["provenance"],
        )
    for r in conn.execute("SELECT * FROM unresolved_refs WHERE epoch_id = ? ORDER BY src, ref", (epoch_id,)):
        g.unresolved.append(ir.UnresolvedRef(r["src"], r["ref"], r["ref_kind"], r["reason"]))
    return g


def load_code_facts(conn: sqlite3.Connection, epoch_id: str) -> CodeFacts:
    facts = CodeFacts()
    rows = conn.execute(
        "SELECT v.fact_kind, v.subject_id, v.payload_json FROM epoch_code_facts f"
        " JOIN code_fact_versions v ON v.vid = f.vid WHERE f.seq = ?"
        " ORDER BY v.fact_kind, v.subject_id",
        (epoch_seq(conn, epoch_id),),
    )
    entries = []
    for kind, sid, payload in rows:
        data = json.loads(payload)
        if kind == "events":
            facts.events[sid] = [Event(k, tuple(t), tuple(b), 0) for k, t, b in data]
        elif kind == "wrappers":
            facts.wrappers[sid] = list(data)
        elif kind == "entry":
            entries.extend((sid, h) for h in data)
    facts.entry_ports = sorted(entries)
    return facts


def load_tests(conn: sqlite3.Connection, epoch_id: str) -> dict[str, ir.TestResult]:
    return {
        r["test_node_id"]: ir.TestResult(r["test_node_id"], r["outcome"], r["source_file"], r["duration_ms"])
        for r in conn.execute("SELECT * FROM test_results WHERE epoch_id = ?", (epoch_id,))
    }


def load_link_state(conn: sqlite3.Connection, epoch_id: str) -> dict[str, dict[str, Any]]:
    out = {}
    for r in conn.execute("SELECT * FROM link_state WHERE epoch_id = ?", (epoch_id,)):
        d = dict(r)
        d["history"] = json.loads(d.pop("history_json"))
        out[d["link_id"]] = d
    return out


def load_lineage(conn: sqlite3.Connection, epoch_id: str) -> list[tuple[str, str, str, float]]:
    return [
        (r["old_id"], r["new_id"], r["method"], r["score"])
        for r in conn.execute(
            "SELECT * FROM id_lineage WHERE epoch_id = ? ORDER BY old_id, new_id", (epoch_id,)
        )
    ]


# ---------------------------------------------------------------------------------------------
# derived tables
# ---------------------------------------------------------------------------------------------


@dataclass
class Derived:
    glyphs: list[ir.Glyph]
    workflows: list[ir.Workflow]
    pairing: PairingResult


def derived_rows(e: str, d: Derived) -> dict[str, list[dict[str, Any]]]:
    """Rows of every derived table for epoch `e` (single source for writing and dumping)."""
    out: dict[str, list[dict[str, Any]]] = {t: [] for t in DERIVED_TABLES}
    for g in sorted(d.glyphs, key=lambda g: g.node_id):
        out["glyphs"].append(
            {
                "epoch_id": e,
                "node_id": g.node_id,
                "base_shape": g.base_shape,
                "variant": g.variant,
                "modifiers_json": ids.canonical_json(g.modifiers),
                "size_weight": g.size_weight,
                "has_interior": int(g.has_interior),
            }
        )
    for wf in sorted(d.workflows, key=lambda w: w.workflow_id):
        out["workflows"].append(
            {
                "epoch_id": e,
                "workflow_id": wf.workflow_id,
                "name": wf.name,
                "side": wf.side,
                "entry_node_id": wf.entry_node_id,
                "scenario_id": wf.scenario_id,
                "source": wf.source,
                "attrs_json": ids.canonical_json(wf.attrs),
            }
        )
        for st in wf.steps:
            out["workflow_steps"].append(
                {
                    "epoch_id": e,
                    "workflow_id": wf.workflow_id,
                    "seq": st.seq,
                    "node_ids_json": ids.canonical_json(st.node_ids),
                    "depth": st.depth,
                }
            )
    for w, seq, n in wf_mod.step_nodes(d.workflows):
        out["workflow_step_nodes"].append({"epoch_id": e, "workflow_id": w, "seq": seq, "node_id": n})
    res = d.pairing
    for lk in sorted(res.links, key=lambda x: x.link_id):
        out["links"].append(
            {
                "epoch_id": e,
                "link_id": lk.link_id,
                "spec_node_id": lk.spec_node_id,
                "code_node_id": lk.code_node_id,
                "method": lk.method,
                "status": lk.status,
                "provenance": lk.provenance,
                "evidence_json": ids.canonical_json(lk.evidence),
                "confidence": lk.confidence,
            }
        )
    precedence = list(ir.STATUS_PRECEDENCE)
    for nid, st in sorted(res.statuses.items()):
        out["node_status"].append(
            {
                "epoch_id": e,
                "node_id": nid,
                "status": st.status,
                "reasons_json": ids.canonical_json({"precedence": precedence, "reasons": st.reasons}),
            }
        )
    for nid, c in sorted(res.rollup.items()):
        out["status_rollup"].append({"epoch_id": e, "node_id": nid, "counts_json": ids.canonical_json(c)})
    return out


def write_derived(conn: sqlite3.Connection, e: str, d: Derived) -> None:
    rows = derived_rows(e, d)
    for table in (
        "glyphs",
        "workflows",
        "workflow_steps",
        "workflow_step_nodes",
        "links",
        "node_status",
        "status_rollup",
    ):
        if not rows[table]:
            continue
        cols = list(rows[table][0])
        conn.executemany(
            f"INSERT INTO {table}({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [tuple(r[c] for c in cols) for r in rows[table]],
        )
    conn.executemany(
        "INSERT OR IGNORE INTO epoch_materialized VALUES (?,?)", [(e, t) for t in DERIVED_TABLES]
    )
    conn.execute("UPDATE epochs SET materialized = 1 WHERE epoch_id = ?", (e,))


def write_sources(conn: sqlite3.Connection, sources: dict[str, str]) -> None:
    """Store file texts by content hash (zlib), once (P4: LLM slices are cut from them)."""
    conn.executemany(
        "INSERT OR IGNORE INTO source_blobs VALUES (?, ?)",
        [(h, zlib.compress(t.encode("utf-8"), 6)) for h, t in sorted(sources.items())],
    )


def load_source(conn: sqlite3.Connection, content_hash: str) -> str | None:
    row = conn.execute(
        "SELECT text_blob FROM source_blobs WHERE content_hash = ?", (content_hash,)
    ).fetchone()
    return zlib.decompress(row[0]).decode("utf-8") if row is not None else None


def drop_derived(conn: sqlite3.Connection, e: str) -> None:
    for t in (*LLM_DERIVED_TABLES, *DERIVED_DELETE_ORDER):
        conn.execute(f"DELETE FROM {t} WHERE epoch_id = ?", (e,))
    conn.execute("DELETE FROM epoch_materialized WHERE epoch_id = ?", (e,))
    conn.execute("UPDATE epochs SET materialized = 0 WHERE epoch_id = ?", (e,))


def is_materialized(conn: sqlite3.Connection, e: str) -> bool:
    r = conn.execute("SELECT materialized FROM epochs WHERE epoch_id = ?", (e,)).fetchone()
    return bool(r and r[0])


# ---------------------------------------------------------------------------------------------
# parse cache
# ---------------------------------------------------------------------------------------------


def load_parse_cache(conn: sqlite3.Connection, rules_hash: str, version: str) -> dict[tuple[str, str], Any]:
    out = {}
    for path, chash, blob in conn.execute(
        "SELECT path, content_hash, payload_blob FROM parse_cache"
        " WHERE rules_hash = ? AND extractor_version = ?",
        (rules_hash, version),
    ):
        out[(path, chash)] = json.loads(zlib.decompress(blob).decode("utf-8"))
    return out


def write_parse_cache(
    conn: sqlite3.Connection, entries: dict[str, tuple[str, Any]], rules_hash: str, version: str
) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO parse_cache VALUES (?,?,?,?,?)",
        [
            (path, chash, rules_hash, version, zlib.compress(ids.canonical_json(payload).encode("utf-8"), 6))
            for path, (chash, payload) in sorted(entries.items())
        ],
    )

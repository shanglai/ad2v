"""Derived tables of an epoch, recomputed deterministically from its stored base facts.

Only the head and pinned epochs keep derived rows in the file (format spec §5.3). Any other
epoch is materialized on demand from: its nodes/edges/unresolved refs (views), its code facts
(workflow inputs), its test results, its link_state (history decisions), its lineage, and the
rules/config it was extracted with (by hash).
"""

from __future__ import annotations

import sqlite3

from ad2v import glyphs, history, pairing, store, workflows
from ad2v.manifest import from_config_json


def derive(conn: sqlite3.Connection, epoch_id: str) -> store.Derived:
    """Compute (but do not write) an epoch's derived tables."""
    ep = store.get_epoch(conn, epoch_id)
    graph = store.load_graph(conn, epoch_id)
    facts = store.load_code_facts(conn, epoch_id)
    config = from_config_json(store.load_config_json(conn, ep.config_hash))
    tests = store.load_tests(conn, epoch_id)
    wfs = workflows.build_all(graph, facts, config)
    links, warnings = pairing.pair_links(graph, config, tests)
    history.replay_state(links, store.load_link_state(conn, epoch_id))
    extra = history.Lineage(rows=store.load_lineage(conn, epoch_id)).ambiguous_reasons()
    paired = pairing.finalize(graph, links, warnings, extra)
    return store.Derived(glyphs.compute(graph), wfs, paired)


def materialize(conn: sqlite3.Connection, epoch_id: str) -> bool:
    """Write derived rows for an epoch if missing. Returns True if it did work."""
    if store.is_materialized(conn, epoch_id):
        return False
    store.write_derived(conn, epoch_id, derive(conn, epoch_id))
    return True

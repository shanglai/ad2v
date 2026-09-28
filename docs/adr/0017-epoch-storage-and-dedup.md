# ADR-0017: Multi-epoch storage: versions, integer membership, views

- Status: accepted (P3)
- Context: P3 stores many epochs in one file. The prompt fixes content-based dedup of base facts,
  derived tables only for the head and pinned epochs, a V column class ignored by diff, and views
  shaped exactly like the v0.2 tables. It leaves the physical layout open.
- Decisions:
  1. **Versions plus membership.** Every base fact (node, edge, unresolved ref, test result, code
     fact) is a row in a `*_versions` table keyed by `version_key = v_ + sha256(canonical normative
     payload)[:20]`. An epoch references its versions through an `epoch_*` membership table. The
     views `nodes`, `edges`, `unresolved_refs`, `test_results` join them back into the v0.2 shape.
  2. **Volatile values live in membership rows**, not versions: span lines (`epoch_nodes`) and edge
     `attrs.lines` (`epoch_edges.lines_json`, re-attached by the `edges` view with `json_set`).
     Otherwise every edit that shifts lines would create new versions for the rest of the file, and
     dedup would be poor exactly where edits are common.
  3. **Integer surrogate keys in membership rows.** Each version row has `vid INTEGER PRIMARY KEY`
     (class I, file-local), and membership rows are `(seq, vid[, volatile columns])` in `WITHOUT
     ROWID` tables, with `seq` referencing the UNIQUE `epochs.seq`. The first layout keyed membership
     by `(epoch_id, node_id, version_key)` text. On dispatch it grew by ~5 MB per epoch (3.42× one
     epoch after 9 epochs), because each unchanged node and edge repeated three 22-character ids
     plus two indexes. The integer layout removes both. Measurements are in REPORT §4.
  4. **Node references become validator checks.** Membership rows carry no node ids, so the v0.2
     foreign keys from edges, test results and the derived tables to the node table cannot be SQL
     foreign keys (views cannot be FK targets either). `ad2v validate` checks them explicitly
     (`NODE_REFS` in `validate.py`), and a test corrupts an edge endpoint to prove it. The
     remaining foreign keys (membership → epochs, membership → versions, derived → epochs, workflow
     step chains) stay in the DDL.
  5. **Base facts include what re-materialization needs:** the workflow inputs that are not in the
     graph (`code_fact_versions`: events, retry wrappers, entry bindings), the rules and manifest in
     effect (`rules_versions`, `config_versions`), and the per-epoch link history (`link_state`,
     ADR-0020). Any epoch can then be materialized from the file alone, even after its parent was
     pruned.
  6. **Derived tables keep their v0.2 shape and FK to `epochs`.** They hold rows only for
     materialized epochs (head + pinned). Writing a new head drops the previous head's rows unless
     it is pinned. `dump`, `diff` and `status` derive rows in memory for other epochs.
- Consequences: an unchanged node costs one ~12-byte row per epoch; readers that use the views are
  unaffected by the layout; the invariant "an epoch's views equal a fresh extraction" is tested
  (`tests/test_history.py`).

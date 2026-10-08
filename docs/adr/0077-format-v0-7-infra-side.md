# ADR-0077: Format v0.7: the infra side

- Status: accepted (P10)

## Decisions

1. **A third side, `infra`,** with the kinds:
   - `deployment_unit`, `managed_datastore`, `managed_queue`, `bucket`;
   - `secret_store`, `network`, `scheduler`;
   - `infra_other`, `infra_module`.
   Infra nodes are in the graph (ids, versions, lineage, history) but not on the map: they have
   no `layout` row (`OFF_MAP_KINDS`) and are never part of a map slice. Their glyph rows exist,
   since validation requires one per node. Their `node_status` is `none`.
2. **Edge kinds:**
   - `references` (infra → infra);
   - `wires` (unit → infra resource; `attrs.env_vars`);
   - `deploys` (unit → code container; `attrs.method`, `attrs.env`);
   - `provides_env` (unit → each code node that reads an env var it provides; `attrs.env_vars`).
3. **Epochs:**
   - `infra_hash` (`''` when none) enters the epoch id only when set;
   - `change_kind` gains `infra`.
4. **Derived tables** (materialized like the others; empty without infra):
   - `infra_status` (ADR-0078);
   - `c4_elements` and `c4_relations` (ADR-0079).
   `c4_layout` persists per epoch, like `layout`.
5. **In-place upgrade 0.6 → 0.7,** chained from 0.4 (ADR-0055/0066 pattern):
   - `epochs` and `node_versions` are rebuilt (CHECK constraints), rows copied, `infra_hash = ''`;
   - every view is dropped and recreated from the DDL;
   - the new tables are created;
   - materialized epochs are marked complete for the new derived tables.
   Readers accept 0.4–0.7. `open_rw` upgrades a 0.6 file instead of refusing it, a gap found by
   the new test. The schema files and the format spec are renamed to v0.7, and Appendix A is
   regenerated.
6. **Normative-dump proof** (old code from `git archive 8d817e3`, the P9 commit):
   - payments-recon, kiro, stories and polyglot are identical after masking the epoch id, the
     rules hash (and the `infra` rules key), the format version and the empty `infra_hash`;
   - spec-kit, custom and table differ only by ADR-0073's derived prefixes and their config hash;
   - every fixture gains `c4_*` derived rows.

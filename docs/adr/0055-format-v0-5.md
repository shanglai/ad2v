# ADR-0055: Format v0.5, with an in-place upgrade from v0.4

- Status: accepted (P7)
- Context: the chat agent must write `llm_results` rows (decision 4), but v0.4 constrains
  `llm_results.task` with a CHECK that lists five tasks. The judge roll-up (ADR-0060) needs a
  table. SQLite cannot alter a CHECK constraint.
- Decisions:
  1. **v0.5** changes only informative objects:
     - `llm_results.task` also allows `chat`;
     - a new `judge_rollups` table;
     - `node_status_effective` also reads `judge_rollups`.
     Normative tables, epoch ids and canonical dumps are unchanged. New attributes
     (`attrs.prefix_sources`, `attrs.schema_digest`) are additive.
  2. **Readers** accept 0.4 and 0.5. **Writers** (`store.open_rw`) upgrade a 0.4 file in place,
     in one transaction: create the new `llm_results`, copy, drop, rename, recreate the index,
     view and table, and set `format_version`. A foreign-key check runs afterwards. The upgrade is
     idempotent.
  3. Files renamed: `schema/ad2v-v0.5.sql`, `schema/ir-v0.5.schema.json` (its `format_version`
     const) and `docs/spec/ad2v-format-v0.5.md`.
- Tested: a v0.4 file (rebuilt from v0.5 by the test) refuses a `chat` row. After `open_rw` it
  is v0.5, keeps its rows, accepts `chat`, and its normative dump is byte-identical.

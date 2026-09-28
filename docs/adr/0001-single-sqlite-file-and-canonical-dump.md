# ADR-0001: One SQLite file per project; determinism checked on a canonical dump

- Status: accepted (P1)
- Context: the prompt fixes "one SQLite database" and "canonical dump" as principles. Several details were left open.

## Decisions

1. **`epoch_id` is part of every data table's primary key.** P1 writes one epoch. P2 can store several
   epochs in the same file without changing column meanings. Each epoch is a full snapshot, and
   delta storage is a P2 question (see REPORT §8).
2. **JSON columns are named `*_json`** and hold canonical JSON (sorted keys, compact, UTF-8). The dump
   decodes them so JSONL rows nest naturally.
3. **The dump excludes every `created_at` column and informative meta keys** (`generator`,
   `generator_version`, `repo_root_name`, `created_at`). `repo_root_name` is informative because the
   same repository checked out under a different directory name must dump identically.
4. **Foreign keys are declared and enforced** (`PRAGMA foreign_keys=ON`; writes use deferred FK
   checks). The node self-reference `(epoch_id, parent_id)` is satisfied by NULL for roots.
5. **LLM provenance is enforced by CHECK constraints**: a row with `provenance='llm'` (or
   `source='llm_inferred'`) must carry `model`, `model_version`, `prompt_hash`, `input_hash` and
   `confidence`. `summaries` and `narrations` require them unconditionally.
6. Node and edge ids use 20 hex chars (80 bits) of SHA-256. For a repo with 10^6 nodes, the collision
   probability is about 4e-13.

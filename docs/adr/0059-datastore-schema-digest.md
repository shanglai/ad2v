# ADR-0059: Deterministic datastore schema digests

- Status: accepted (P7)
- Context: the P4 judge missed the planted REQ-009 drift ("classify at most once per run")
  because its slice showed no data shapes (issue 42). Uniqueness lives in the schema, not in the
  function body.
- Decisions:
  1. **Sources**, parsed from the repository text with the stdlib (`ast`, regular expressions).
     No database is contacted.
     - SQLAlchemy declarative classes (`__tablename__`; `Column`/`mapped_column` with type,
       primary key, foreign key, unique, nullable; `UniqueConstraint`/unique `Index` in
       `__table_args__`);
     - `CREATE TABLE` in `*.sql` files (column and table constraints);
     - Pydantic (`BaseModel`/`SQLModel`) classes used by a route: a handler parameter
       (request) or `response_model=` (response), stored on the route as
       `attrs.schema_models`.
  2. **Normative.** The digest is `attrs.schema_digest = {"tables": [...]}` on a `datastore`
     node, sorted. `*.sql` files are now part of the repository tree hash, because they are
     inputs; repositories without SQL files keep their epoch ids.
  3. **Attachment.**
     - A model attaches to every datastore read or written by its module, or by a module that
       imports it.
     - SQL DDL attaches to the only datastore whose libraries include a SQL library.
     - Otherwise a synthetic `datastore:<lib>:models` node under the code system holds it.
  4. **Judge slices** include a fenced "datastore schema digest" part, at most 40 lines, for the
     datastores the judged code reaches (directly, through callees, or down its workflows). A
     table without a unique constraint says so explicitly.
- Fixture:
  - `api/recon_api/models.py` (`classifications`, with no unique constraint on
    (run_id, reference)) and `api/sql/schema.sql` (`ledger`, and `unmatched` with
    `UNIQUE (run_id, reference)`);
  - `classify_run` now saves through `db.save_classifications`, so REQ-009's slice shows the
    missing constraint.

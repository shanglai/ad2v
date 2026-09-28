# ADR-0007: Static resolution heuristics of the Python extractor

- Status: accepted (P1)
- Context: the prompt asks for call resolution "by name and import", resource naming and risk
  detection without running code. The choices below set the precision/recall trade-off.
- Decisions:
  1. **Import roots**: the repo root, every container path, every `src/` directory, and every
     directory with `pyproject.toml`/`setup.py`/`setup.cfg`. A module is indexed under its dotted
     name relative to each root that contains it. Ambiguous names prefer the same container, then
     the shortest path, then lexicographic order.
  2. **Value tracking** is flow-insensitive at module level and flow-sensitive inside functions
     (assignments in source order). It follows module constants across import hops, `with ... as x`,
     and parameter annotations that name a classified library type.
  3. **Objects**: calling a classified constructor (`create_engine`, `httpx.AsyncClient`, ...) gives
     an object bound to a resource. Methods on it touch the resource unless they are listed in
     `pure_methods`. Pure methods return the same resource (`engine.connect()`).
  4. **Chained calls** (`a().b()`): only the dotted part is classified, so
     `session.execute(...).first()` counts once.
  5. **Transitive IO**: a loop's risk takes into account everything reachable through resolved calls
     (fixpoint over the call graph, unbounded depth). Without it, the N+1 in the fixture
     (`match_batch` → `db.fetch_ledger_entry` → `session.execute`) would be missed.
  6. **Behavior ordinals** count every candidate of a kind in a function, emitted or not, so ids do
     not depend on `emit_all`.
  7. **Known gaps (not resolved)**: attribute calls on untyped parameters, `self.x = client` in
     `__init__` used by other methods, dynamic dispatch, decorators that wrap or rename functions,
     `getattr`. See `pending.md`.

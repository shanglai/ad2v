# ADR-0068: Wider default excludes; migration folders keep their SQL

- Status: accepted (P9)
- Context: a brownfield repository carries vendored and generated code: `node_modules/`, `dist/`,
  minified bundles, `.next/`, `target/`, `vendor/`, coverage reports, extra virtual environments
  (`.venv-tools/`). Since P8.1, TypeScript and other unread languages become `not_evaluable`
  modules, so every vendored file inflated the map with noise. Migration folders raise the
  opposite problem. Their Python files (Alembic, Django) are generated history that should not
  pair with requirements. Their `.sql` files, however, are the best schema evidence a repository
  has (ADR-0059).

## Decisions

1. **`DEFAULT_EXCLUDES` adds** `.venv*`, `.next`, `out`, `target`, `vendor`, `coverage`,
   `*.min.js` and `*.map` to the earlier set (`node_modules`, `dist`, `build`, `.git`, `.venv`,
   `__pycache__`, …). A manifest `exclude:` list still adds to the defaults. It does not replace
   them.
2. **`CODE_ONLY_EXCLUDES = ("migrations", "alembic")`.** Code files under those folders are not
   extracted (`code_excluded()`), but `*.sql` files there stay in the walk and feed the datastore
   schema digest.
3. **IaC is not part of the language-scope table.** `.tf`, Pulumi, CloudFormation and Kubernetes or
   Helm YAML are not `not_evaluable` modules: they describe deployment, not behavior. `ad2v init`
   reports them, and P10 may map them.
4. Every existing fixture is unchanged. The brownfield fixture exercises each rule.
   `node_modules/` and `dist/` (with an `app.min.js`) are dropped, `migrations/V2__indices.sql` is
   read, and `migrations/0002_backfill.py` is not.

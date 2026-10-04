# ADR-0053: Route prefixes from settings (issue 70)

- Status: accepted (P7)
- Context: FastAPI apps commonly mount the API under `settings.API_V1_STR`, a pydantic
  `BaseSettings` field whose class default the environment can override. P6.1 left those routes
  `path_unresolved`, so on full-stack-fastapi-template all 23 routes paired as `needs_review`.
- Decisions:
  1. **Off by default.** Without configuration, P6.1 behavior is unchanged: `path_unresolved`
     plus `path_tail`, paired `needs_review`.
  2. **`pairing.path_constants`** (always available) maps an expression to its value:
     `{"settings.API_V1_STR": "/api/v1"}`.
     - Keys match the unresolved expression's source text with all whitespace removed.
     - A route resolved this way carries `attrs.prefix_sources: ["path_constants:<expr>"]`; its
       link carries evidence `prefix_from_path_constants`.
  3. **`pairing.resolve_settings_defaults: true`** (opt-in) reads the class-attribute default of
     a field on a class that subclasses a `settings_bases` rule entry (`pydantic_settings.
     BaseSettings`, `pydantic.BaseSettings`, `pydantic.BaseModel`, `pydantic.v1.BaseSettings`),
     directly or through repository subclasses.
     - Only literal defaults count: a string, a `+` or implicit concatenation of literals, or an
       f-string whose parts are literals. Names, calls and `os.environ` stay unresolved.
     - The instance must be visible statically (`settings = Settings()`, imported anywhere).
     - Such links carry evidence `prefix_from_settings_default` with the setting's qualified name
       and the warning "a default; the environment can override it at run time".
  4. When both are configured, an explicit `path_constants` entry wins: it is checked first.
  5. Both settings are in the manifest, so they enter `config_hash`. When set, they also appear
     in the normative config echo. `settings_bases` is in the rules, so it enters `rules_hash`.
  6. Repository class instances (`Inst`) exist in the static evaluator only while the resolver is
     on, so extraction with it off is unchanged byte for byte.
- Results:
  - Fixture (`api/recon_api/settings.py`, `GET …/{run_id}/audit`): off → `needs_review`;
    manifest → `implemented`; resolver → `implemented` with the warning.
  - full-stack-fastapi-template `cb740b6`: `path_unresolved` 23 → 0 with either mechanism. Five
    seeded samples were read against the source and are correct.

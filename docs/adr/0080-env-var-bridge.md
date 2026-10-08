# ADR-0080: The env-var bridge between code and infra

- Status: accepted (P10)

## Decisions

1. **Code side** (`infra/envreads.py`, tree-sitter, nothing executed):
   - `os.environ[...]`, `os.environ.get`, `os.getenv`, `os.environ.setdefault` (also imported as
     `environ` / `getenv`);
   - pydantic `BaseSettings` fields: `env_prefix + NAME` upper-cased, with `Field(alias=…)` /
     `validation_alias` respected and `env_prefix` read from `model_config =
     SettingsConfigDict(...)` or an inner `class Config`.
   Names attach to the innermost function, class or module holding the read and to its container
   (`attrs.env_reads`). **Only in epochs with infra input:** without infra there is no bridge, and
   the code side's normative output stays as it was.
2. **`deploys`,** per environment, in priority order:
   - (a) the manifest: `infra: {deploys: {"google_cloud_run_v2_service.api": backend}}` (an
     address, with or without index; a list of containers is allowed);
   - (b) a name match: the unit's `name`, its resource name (generic names such as `this` or
     `main` ignored) or its image repository's last segment equals the container's slug, or ends or
     starts with it at a `-` boundary (`conciliacion-backend` ↔ `backend`);
   - (c) env-var overlap: the container's reads are a subset of what the unit provides, with ≥ 2
     names and one best candidate.
   Many-to-many is allowed: one unit may deploy several containers, and units with the same image
   may deploy one container. Ties at one level are `ambiguous`: no edge, the candidates in the
   reasons, and `init` proposes `infra.deploys` placeholders and `init --check` lists them.
3. **`provides_env` / `wires`.** For each env var a deployed container reads:
   - provided by its unit: a `provides_env` edge to the reading node, plus the unit's `wires`
     edge to the resource the value references when known. The reader is `wired`;
   - not provided: `unwired`, with the env var and the unit as evidence.
4. **A website bucket is a static host** (decided here). A GCS bucket with a `website` block, or an
   S3 bucket with a website configuration, can deploy a code container like a unit. It is drawn
   as a `static_site`. The brownfield frontend is published this way.
5. **Fixture.** `fixtures/brownfield-es` gains:
   - a Cloud Run backend (env from Cloud SQL, Pub/Sub and a secret);
   - an orphan bucket and the frontend website bucket;
   - `src/worker` with no infra (`undeployed`);
   - a settings field nothing provides (`EXPORT_BUCKET`, `unwired`);
   - prod and dev plans; dev has no frontend (`count = 0`) and no `EVENTS_TOPIC`.

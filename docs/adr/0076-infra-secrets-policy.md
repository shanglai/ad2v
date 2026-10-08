# ADR-0076: Infra secrets policy: an allowlist, never values

- Status: accepted (P10)
- Context: plan JSON and tfvars routinely contain secrets:
  - database passwords and connection strings;
  - API keys inlined as env var literals;
  - credentials in module source URLs;
  - sensitive outputs.
  A `.ad2v` file is shared, committed and served to MCP hosts. It must never carry one.

## Decisions

1. **An allowlist per resource type** (`infra.yaml` `attrs`), limited to a global set of names:
   `name, location, region, image, min_instances, max_instances, runtime, engine,
   engine_version, tier, website, encrypted, fifo, schedule, versioning, memory, ingress,
   launch_type, desired_count`. Values are stored only as booleans, numbers or strings cut to 200
   characters. Anything not listed is never stored.
2. **Env vars:** names only. Each value is reduced to its source:
   - `reference` to a resource address;
   - `secret` with the secret resource address;
   - `literal`;
   - `unknown` (with `candidates` when several resources could be the source).
   A literal's value is never kept.
3. **Sensitive markers win.** An allowlisted attribute that the plan marks in `sensitive_values`
   is stored as `"sensitive"`. `variables`, `prior_state` and output values are never read.
4. **Derived values are cleaned.**
   - images keep the repository only: no tag, no digest, no `user:pass@`;
   - encryption flags are booleans (a key's name is not stored);
   - module sources become `remote: true|false`, never the URL.
5. **Test.** The GCP and AWS fixtures and the static config plant 15 or more fake secrets
   (`PLANTED…`, a credential in a module URL, a sensitive default). The test extracts all of them
   into one file and asserts that none appears in the `.ad2v` bytes or in its full dump
   (informative rows included).

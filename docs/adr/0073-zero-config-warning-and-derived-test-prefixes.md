# ADR-0073: A warning for maps built without configuration; test-name prefixes from the specs

- Status: accepted (P10)
- Context: P9 measured `fixtures/brownfield-es` with and without `ad2v init`. Zero-config gave a
  misleading map:
  - endpoints looked `missing` and routes looked orphaned (an unresolved settings prefix);
  - one fallback container hid the services;
  - `test_rf_002_…` did not link, because `RF` was not a test-name prefix.
  The user had no way to tell that the map was wrong.

## Decisions

1. **The warning.** When `extract` runs without a manifest (no `--manifest`, no `ad2v.yaml`), it
   checks four conditions, in this order, and prints each one under a single banner that
   recommends `ad2v init`:
   - `unresolved_route_prefixes`: the Python extractor reports a prefix expression it could not
     resolve, through `CodeFacts.diagnostics` (run state, never in the graph). It is also
     recorded when the router itself does not resolve, the zero-config case;
   - `fallback_container`: at most one container, while project manifests exist below the root
     (depth ≤ 3, spec roots aside);
   - `test_prefixes_derived`: spec id prefixes that were not in the configured test-name prefixes
     (see 2);
   - `iac_present`: Terraform or other IaC folders.
2. **Derived prefixes.** The effective `test_name_prefixes` are the configured ones plus the prefixes
   of the spec ids (requirements and spec components) found in this epoch's specs. They are
   computed by reading the specs into a scratch graph before code extraction. They are part of the
   config identity (`config_json.effective.derived_test_prefixes`, only when non-empty), so an
   epoch whose prefixes change gets a new id.
3. **Where it shows.** The conditions are stored in `meta.unconfigured_warnings`, and the derived
   prefixes in `meta.derived_test_name_prefixes`. Both are informative meta: canonical dumps stay
   unchanged. The viewer shows a banner and the MCP overview a line: "This map was built without
   configuration; N things may be wrong. Run `ad2v init`."
4. **Golden changes.**
   - brownfield-es zero-config: RF-002 and RF-003 go `specified` → `implemented`;
   - sdd-presets spec-kit (`SC`), custom (`BILL`) and table (`CAL`, `RNF`): `test_ref_prefixes`
     and `config_hash` change, while links and statuses stay the same.

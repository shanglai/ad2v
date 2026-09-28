# ADR-0015: Pairing and status details not fixed by the P2 prompt

- Status: accepted (P2)
- Decisions:
  1. **Unpaired rows are links with `method = 'none'`.** `missing`/`specified` spec items get a row
     with `code_node_id` NULL, and `orphan` code items a row with `spec_node_id` NULL. Each item's
     status is then queryable in one table. The prompt names four methods; `none` is a fifth value
     for "no pairing", and `llm` is reserved for P4, so P4 does not need a CHECK change.
  2. **Node status `none`.** "Functions, classes and modules are never orphan" needs a status for
     code that no spec coverage applies to (e.g. a function inside an unmapped container). `none`
     is the lowest precedence and renders neutrally (thin solid). It is a `node_status` value only,
     never a link status.
  3. **Inheritance** passes down only `verified`, `implemented` and `specified`. Problem statuses
     (`drift`, `needs_review`, `missing`, `orphan`) stay on the node that has them. Otherwise a
     drifting route would paint its whole container amber, and roll-ups would double count.
  4. **Ports take their handler's links** when they have none (`via_handler`): an annotated handler
     makes its MCP tool `implemented`, not `orphan`.
  5. **Linked tests for `verified`** include tests annotated with any ID in the spec item's own
     `spec_ref`. That is how an OpenAPI endpoint with `x-ad2v-refs: [REQ-001]` becomes `verified`
     when a REQ-001 test passes. A **failing** linked test is evidence (`tests_failed`), not
     `drift`: a red test says the code is wrong, not that code and spec disagree structurally.
  6. **`missing` for spec components** only when a manifest mapping points to a target that does not
     exist. The prompt says "spec_component covered by manifest/name_match rules". Applying that to
     every component (name_match covers all of them in principle) would mark every unmapped
     component `missing`. That is exactly the unprovable absence the prompt wants as `specified`.
  7. **`path_prefix_map` applies to both sides.** The manifest author writes one mapping, and it
     normalizes whichever side carries the prefix. It matches on `/` boundaries only (`/v1` does not
     touch `/v10`).
  8. **`case_insensitive` lowercases the whole normalized path.** Parameters are already `{}`, so
     "literal segments only" is automatic.
  9. **`stale` precedence** is placed between `orphan` and `verified`. The prompt's order does not
     include it, since it is reserved for P3.
  10. **`links.confidence` is `NOT NULL`**, 1.0 for deterministic rows, and marked N/I.
  11. **The `spec_root` qualified name is the system name**, so both roots read the same in a
      viewer. The ids differ because side and kind differ.
  12. Drift "path param count" compares the endpoint's declared `in: path` parameters with the
      route template's parameters. With positional `{}` normalization, the two templates always
      have the same count once they match, so the declared list is the only place a mismatch can
      show up.

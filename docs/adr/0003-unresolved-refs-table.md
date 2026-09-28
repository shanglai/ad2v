# ADR-0003: Dangling spec references go in `unresolved_refs`, not in `edges`

- Status: accepted (P1). Additive: one table not listed in the prompt.
- Context: a code annotation `# ad2v: REQ-099` may name a spec ID that no spec defines. `edges` has
  foreign keys to `nodes`, so an edge cannot point to a node that does not exist. A placeholder node
  would pollute the graph and the glyph map.
- Decision: every explicit reference is kept in the node's `spec_ref`. References that resolve become
  `annotated_as` edges. References that don't resolve become rows in the normative table
  `unresolved_refs(epoch_id, src, ref, ref_kind='spec_id', reason='not_found')`.
- Consequences: P2 can turn these rows into "dangling reference" findings without re-parsing. In a
  later epoch where the ID exists, the same annotation simply produces an edge.

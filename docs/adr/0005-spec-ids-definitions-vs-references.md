# ADR-0005: Where spec IDs are defined vs. referenced; `annotated_as` from spec nodes

- Status: accepted (P1). **Deviation**: the prompt says Gherkin Feature → "`spec_component` or
  `requirement`" and "tags like `@REQ-012` become spec IDs".
- Context: the same ID (`REQ-001`) usually appears in several places: an EARS line in Markdown, a
  Gherkin tag, an OpenAPI operation, and code annotations. If every occurrence *defined* a node with
  qualified name `REQ-001`, they would collide (same id, different content), or the result would
  depend on file order.
- Decision:
  - **Definitions** are Markdown `## Component: ... {#CMP-x}` headings and `- [REQ-x] ...` lines. These
    are the only places where a spec node gets an ID-based qualified name.
  - **References** are Gherkin tags, OpenAPI `x-ad2v-refs`, and code annotations. They go into
    `spec_ref` and resolve to `annotated_as` edges (or to `unresolved_refs`).
  - A Gherkin **Feature is always a `spec_component`** qualified as `<path>::<feature>`. Scenarios are
    path-qualified too.
  - `annotated_as` is therefore also emitted **spec → spec** (scenario → requirement, endpoint →
    requirement, feature → component). The meaning is unchanged: an explicit, deterministic ID
    reference.
- Consequences: identity never depends on file order. Scenario coverage of requirements is already a
  graph query for P2.

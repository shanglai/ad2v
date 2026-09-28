# ad2v spec Markdown convention, v0.1

Status: **draft, normative for extractors**. Reference implementation:
`src/ad2v/extract/spec/markdown.py`.

Most SDD specs are Markdown. ad2v extracts only what the text marks explicitly, deterministically.
Everything else stays as prose, and the extractor does **not** interpret it. Semantic extraction
from prose is an LLM task. It is planned for P3 as a *frozen* step (its output stored with
provenance and reused), and it is never part of the deterministic extractor.

## 1. Components

```markdown
## Component: Reconciliation API {#CMP-001}
```

- A level-2 heading that starts with `Component:` declares a `spec_component`.
- `{#ID}` gives its spec ID, which is also its qualified name. IDs match `[A-Z][A-Z0-9]*-[0-9]+`.
- If no ID is given, the qualified name is `<spec file path>::<name>`. This is allowed but
  discouraged, because renaming the heading changes its identity.
- The component section runs until the next level-1 or level-2 heading. Non-requirement text inside
  the section is stored in `attrs.text`.

## 2. Requirements (EARS)

```markdown
- [REQ-012] When <trigger>, the <system> shall <response>.
```

- A list item (`-` or `*`) that starts with `[ID]` declares a `requirement`. Its qualified name is the
  ID.
- A requirement inside a component section is a child of that component. Otherwise it is a child of
  the file's `spec_doc`.
- The text is matched against the EARS templates, in this order. The first match wins, and
  keywords are case-insensitive:

| `attrs.ears` | template | captured attrs |
|---|---|---|
| `unwanted` | `If <trigger>, then the <system> shall <response>.` | trigger, system, response |
| `event` | `[While <precondition>, ]When <trigger>, the <system> shall <response>.` | precondition?, trigger, system, response |
| `state` | `While <precondition>, the <system> shall <response>.` | precondition, system, response |
| `optional` | `Where <precondition>, the <system> shall <response>.` | precondition, system, response |
| `ubiquitous` | `The <system> shall <response>.` | system, response |
| `null` | anything else | (only `text`) |

A requirement that doesn't match any template is still a requirement, with `ears: null`.

## 3. Everything else

- The file becomes a `spec_doc` node (qualified name = path relative to the spec root). Text that is
  neither a component heading, a requirement line, nor inside a component section is concatenated
  into `attrs.prose`.
- Fenced code blocks (```` ``` ````) are never parsed for components or requirements.
- Level-3+ headings do not end a component section.

## 4. Referencing specs from code

See format spec §3.6. In short: `# ad2v: REQ-012` comments, `ad2v: REQ-012` docstring lines, and
test names such as `test_req_012_*`.

## 5. Other spec formats

- **Gherkin** (`*.feature`): Feature → `spec_component` (`<path>::<feature>`), Rule → prefix of its
  scenarios' names, Scenario / Scenario Outline / Background → `scenario`, steps → `scenario_step`
  (`<scenario>::step[n]`). Tags that match the spec ID pattern (`@REQ-012`) are *references*
  (`spec_ref` + `annotated_as`), not definitions (ADR-0005).
- **OpenAPI 3.x** (any `.yaml`/`.yml`/`.json` whose top-level `openapi` starts with `3`): each
  operation becomes a `spec_endpoint` with qualified name `METHOD /path`. The optional operation
  extension `x-ad2v-refs: [ID, …]` adds references.

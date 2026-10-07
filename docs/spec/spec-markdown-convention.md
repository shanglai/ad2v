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

**Spanish** (P9, ADR-0069). The same five forms, with *deberá(n)*, *debe(n)* or *tendrá que*,
are tried after the English ones. A leading article on the system is dropped:

| `attrs.ears` | plantilla |
|---|---|
| `unwanted` | `Si <disparador>, [entonces ]el <sistema> deberá <respuesta>.` |
| `event` | `[Mientras <precondición>, ]Cuando <disparador>, el <sistema> deberá <respuesta>.` |
| `state` | `Mientras <precondición>, el <sistema> deberá <respuesta>.` |
| `optional` | `Donde <precondición>, el <sistema> deberá <respuesta>.` |
| `ubiquitous` | `El <sistema> deberá <respuesta>.` |

**Titles.** `- [REQ-012] (Exportar a CSV) When …` gives the requirement the title in
parentheses. Without one, ad2v derives up to six words from the response. Titles are display
only: the map reads `REQ-012 · Exportar a CSV`.

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

## 6. SDD presets (P6.1, ADR-0048)

The ad2v convention above is one of four Markdown **presets**. A file is read with exactly one.

| preset | selected when | components | requirements | ids |
|---|---|---|---|---|
| `ad2v` | `## Component: … {#CMP-n}` or an EARS `REQ-n` line | `## Component:` | `- **REQ-n** …` | as written |
| `spec-kit` | `spec.md` with a Functional Requirements heading and `**FR-` lines (github/spec-kit v1.1.0 template) | the feature folder | `**FR-001**: System MUST …`, `**SC-001**` (success criteria) | `<feature>:FR-001` |
| `kiro` | `.kiro/specs/<feature>/requirements.md` | the feature | `### Requirement N[: Title]` with `**User Story:**`; numbered acceptance criteria (EARS) as children | `<PREFIX>-N`, `<PREFIX>-N.M` |
| `custom` | a `spec_markdown` rule with `preset: custom` | `component` regex (optional; group `name`) | `requirement` regex (required; groups `id` and `text`) | as captured |
| `table` (P9) | a Markdown table whose header has an id column and a text column | the heading above the table; a `Componente`/`Component` cell → a sub-component | one per row whose id fits the grammar | as written |
| `stories` (P9) | `HU-n`/`US-n` headings or items with "Como … quiero …" / "As a … I want …" | the heading above | the story; each acceptance criterion a child | `HU-001`, `HU-001.N` |

Selection: the first `spec_markdown` rule in `ad2v.yaml` whose glob matches wins; otherwise
auto-detection in the order kiro, spec-kit, ad2v, table, stories.

```yaml
spec_markdown:
  - glob: "docs/requirements/*.md"
    preset: custom
    requirement: '^- \[(?P<id>BIL-[0-9]+)\] (?P<text>.+)$'
  - glob: ".kiro/specs/payments/requirements.md"
    preset: kiro
    id_prefix: PAY            # instead of PAYMENTS
```

- **spec-kit**: user stories become `scenario` nodes. Their `**Given**`/`**When**`/`**Then**`
  clauses become steps. `[NEEDS CLARIFICATION: …]` sets `attrs.needs_clarification`.
- **Kiro**: the prefix is the feature folder slug, upper-case alphanumerics of up to 12
  characters (`order-export` → `ORDEREXPORT`, `001-auth` → `K001AUTH`). If two features share a
  prefix, the second (in path order) gets `2`, then `3`. Each criterion's EARS pattern is
  parsed (`attrs.ears`: `event`, `state`, `optional`, `unwanted`, `ubiquitous`).
- **custom**: lines that look like ids but do not match are listed in the doc node's
  `attrs.skipped_ids`.
- Tests cite namespaced ids by name (`test_fr_001_*`). Words before the prefix narrow the
  namespace: `test_refunds_fr_001_*` → `002-refunds:FR-001`. An ambiguous reference is
  `needs_review`.
- **table**: header names are matched without regard to case or accents:
  - id: `ID`, `Id`, `Clave`, `Identificador`, `Código`, `Req`;
  - text: `Descripción`, `Requerimiento`, `Requisito`, `Description`, `Requirement`;
  - optional: `Título`/`Nombre`/`Title`, `Prioridad`/`Priority`, `Tipo`/`Type`,
    `Componente`/`Módulo`/`Component`.
  `\|` and pipes inside code spans are text, and `<br>` is a space. A row continued on the next
  line is merged and noted in `table_notes`. Rows whose id does not fit are listed in
  `skipped_ids`, repeated ids in `duplicate_ids`. A `Tipo` of *No funcional* / *Non-functional* /
  *NFR* / *Calidad* marks the row non-functional.
- **stories**: "Como <rol>, quiero <acción>, para <beneficio>" (or "As a …, I want …, so that
  …"). The criteria list ("Criterios de aceptación" / "Acceptance criteria") can be numbered,
  bulleted or written as Dado/Cuando/Entonces (Given/When/Then), on one line or several. Each
  criterion is a child requirement with its `gwt` triple or EARS form.
- **Non-functional**: ids with a prefix in `spec_ids.nonfunctional_prefixes` (default `RNF`,
  `NFR`, `NF`) are `requirement_type: nonfunctional`. They are counted apart and badged NFR.
- Spanish Gherkin (`# language: es`, `Característica` / `Escenario` / `Dado` / `Cuando` /
  `Entonces`) is read like English.
- Not parsed: Kiro `design.md`/`tasks.md`, spec-kit `plan.md`/`tasks.md`.

## 7. Where specs are found (ADR-0047)

`--spec` (repeatable) beats `spec_root` in `ad2v.yaml` (a string or a list), which beats
auto-detection: the first of `specs/`, `spec/`, `docs/specs/`, `.kiro/specs/`, `sdd/`,
`docs/sdd/` that holds a recognized file, plus a root `openapi.{yaml,yml,json}`.
`--no-spec-autodetect` turns that off. Code under a spec root is never extracted as code.
`ad2v init` (ADR-0071) also finds spec folders with other names, by content, and proposes them
as `spec_root`.

## 8. No convention at all: bootstrap from prose (ADR-0049)

`ad2v specs bootstrap --from docs/ --plan` lists prose files with no recognized structure and
estimates an LLM pass. `--yes --max-cost-usd N` writes proposals in this convention, with `-X`
ids, to `<spec root>/.ad2v-extracted/`. `ad2v specs review` compares them with existing specs.
`ad2v specs approve <file>` moves one into the spec tree; nothing is normative before that.

# ADR-0069: Team SDD formats (tables, user stories), Spanish EARS and Gherkin, titles, non-functional requirements

- Status: accepted (P9)
- Context: teams that write specs by hand, in Spanish as often as in English, rarely use the ad2v
  convention, spec-kit or Kiro. They use a requirements table (`| ID | Descripción | Prioridad |`)
  and user stories ("Como operador, quiero…, para…") with acceptance criteria. They also write EARS
  in Spanish ("Cuando …, el sistema deberá …"). Read by the P6.1 readers, these files became prose
  that needed an LLM bootstrap, although they are fully structured. The map also showed bare ids
  (`RF-007`) where a reader needs a few words, and non-functional requirements ("conciliar 100.000
  movimientos en menos de un minuto") showed as plain `specified` items, as if they were missing
  features.

## Decisions

1. **Two new presets behind the ADR-0048 mechanism** (`extract/spec/team.py`), auto-detected by
   shape after kiro, spec-kit and ad2v, or named in `spec_markdown:`:
   - `table`: a header with an id column and a text column (Spanish or English names, matched
     without regard to case or accents). Optional title, priority, type and component columns.
     Escaped `\|` and pipes inside code spans are handled, `<br>` becomes a space, and a row
     continued on the next line is merged and reported. A row whose id does not match the spec-id
     grammar is skipped and reported. Duplicate ids are reported. The nearest heading becomes a
     `spec_component`. A `Componente` cell becomes a sub-component, which pairs by name like any
     component (`from_column: true`).
   - `stories`: `HU-001` / `US-001` headings or list items, "Como/As a … quiero/I want … para/so
     that …" (actor, action and benefit kept in `attrs`), and acceptance criteria that are numbered,
     bulleted or written as Dado/Cuando/Entonces (Given/When/Then). Each criterion becomes a child
     requirement `HU-001.N`, with its `gwt` triple or EARS form.
2. **Spanish EARS** (`markdown.EARS_ES`): *Si* (unwanted), *Cuando* (event), *Mientras* (state),
   *Donde* (optional) and the ubiquitous form, with the modals *deberá(n)*, *debe(n)* and *tendrá
   que*. `parse_ears` tries English first. The prose validator for `specs bootstrap` accepts the
   same modals.
3. **Spanish Gherkin** needs no new code: `# language: es` is parsed by gherkin-official, and the
   keyword types (Context/Action/Outcome/Conjunction) are stored with each step.
4. **Titles** (`titles.py`, `attrs.title`). An explicit title wins: a table title column, a story
   or Kiro heading, or the convention's new `- [REQ-001] (Título corto) …`. Otherwise one is
   derived: the GWT *then*, the story action, the EARS response or the text, minus the system
   phrase, cut to 6 words at a word boundary, with no trailing function words (Spanish and English)
   and the first letter upper-case. This is deterministic, and a title is display only: it never
   changes ids or pairing.
5. **Non-functional requirements.** `attrs.requirement_type = "nonfunctional"` applies to ids whose
   prefix is in `spec_ids.nonfunctional_prefixes` (default `RNF`, `NFR`, `NF`), or when a table type
   column says so (`No funcional`, `Non-functional`, `NFR`, `Calidad`, …). They pair like any
   requirement, but they are counted apart: in `ad2v status`, in the MCP overview
   (`nonfunctional_requirements`) and in `scripts/dogfood_counts.py`. The viewer gives them an NFR
   badge and a note.
6. Test-name prefixes are unchanged by default (`REQ`, `CMP`, `FR`). `ad2v init` proposes the
   prefixes it finds (`RF`, `HU`, `RNF`, …) under `spec_ids.test_name_prefixes`.

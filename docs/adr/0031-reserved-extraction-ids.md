# ADR-0031: Reserved `-X` spec IDs for LLM-proposed items

- Status: accepted (P4)
- Context: the prompt asks for proposed IDs "in a reserved range (`REQ-X001`…)" that still go
  through the normal Markdown parser once a human approves them. The P3 grammar
  `[A-Z][A-Z0-9]*-[0-9]+` does not accept `REQ-X001`.
- Decisions:
  1. The spec ID grammar becomes `[A-Z][A-Z0-9]*-X?[0-9]+` (`ids.SPEC_ID_PATTERN`, shared by the
     Markdown, Gherkin and code-annotation parsers). This is additive: every old ID still parses,
     and IDs with `-X` never collide with human ones. The local-facts cache version goes to
     `python-local-2`.
  2. `.ad2v-extracted` is in the default excludes. Proposals live there and are never extracted,
     until a human moves or renames the file; that act is the approval.
  3. After approval the IDs may stay as they are (they parse) or be renamed by the human.

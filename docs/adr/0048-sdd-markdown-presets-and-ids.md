# ADR-0048: SDD Markdown presets and spec ids

- Status: accepted (P6.1)
- Context: teams write requirements with spec-kit, Kiro or their own Markdown. The ad2v
  convention (`## Component: X {#CMP-001}`) is not what they use.
- Pinned sources (read 2026-10-03):
  - **spec-kit**: github/spec-kit commit `ae5ade7234be5cb1d975f736c4e06dd46d1326d6`
    (release v1.1.0), `templates/spec-template.md`. Layout
    `specs/<NNN|YYYYMMDD-HHMMSS>-<name>/spec.md`; `**FR-001**: System MUST …`; success criteria
    `**SC-001**`; user stories with `**Given** … **When** … **Then**`;
    `[NEEDS CLARIFICATION: …]` markers.
  - **Kiro**: kiro.dev/docs/specs (updated 2026-10-02) and the feature-specs page (2026-08-04),
    checked against real repositories (sebsto/wispr, crawlab-team/artipub, evrignaud/fim):
    `.kiro/specs/<feature>/requirements.md`, `### Requirement N[: Title]`, `**User Story:**`,
    `#### Acceptance Criteria` with numbered EARS criteria in both generations (`WHEN … THEN the X
    SHALL …` and `WHEN …, THE X SHALL …`).
- Decisions:
  1. **Presets**: `ad2v` (P2 convention), `spec-kit`, `kiro`, `custom` (regexes from the
     manifest). Selection: a `spec_markdown` rule in `ad2v.yaml` (`{glob, preset, …}`) wins.
     Otherwise auto-detect by path and content: Kiro needs `/.kiro/specs/<f>/requirements.md`;
     spec-kit needs a `spec.md` with a Functional Requirements heading and `**FR-` lines (so
     spec-kit's own `checklists/requirements.md` is not Kiro); then the ad2v convention. An unknown
     preset, or `custom` without a `requirement` regex, is an error.
  2. **Ids.** The grammar becomes
     `(?:[a-z0-9][a-z0-9-]*:)?[A-Z][A-Z0-9]*-X?[0-9]+(?:\.[0-9]+)?`:
     - spec-kit ids are namespaced by the feature folder: `001-payments:FR-001`,
       `001-payments:SC-001` (`category: success_criterion`, a deviation: SC items are
       requirements so tests can reference them);
     - Kiro ids are synthesized: `ORDEREXPORT-1` for Requirement 1 and `ORDEREXPORT-1.2` for its
       second criterion (a child). The prefix is the feature slug, upper-case alphanumerics of
       up to 12 characters, with `K` in front if it starts with a digit. Collisions get a
       deterministic suffix (`AUTH`, `AUTH2`) in sorted path order;
     - `custom` takes the ids its regex captures; non-matching ids are listed in
       `skipped_ids`.
  3. **References.** Code and tests may cite `FR-001` without the namespace. When exactly one
     namespace has it, that is the target. When several do, the edge gets `attrs.ambiguous` and
     the link is `needs_review` with evidence `ambiguous_spec_ref` listing the candidates. A
     test-name hint (`test_payments_fr_001`) narrows the namespace.
  4. Line endings and a BOM do not change the output (tested with a CRLF+BOM copy of every
     preset fixture).
- Not parsed yet (pending.md): Kiro `design.md`/`tasks.md`, spec-kit `plan.md`/`tasks.md`,
  Markdown tables of requirements, sub-ids in test names.

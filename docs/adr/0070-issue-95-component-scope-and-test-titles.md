# ADR-0070: Requirements under an out-of-scope component; test titles in unread languages (issue 95)

- Status: accepted (P9); closes issue 95 (opened in P8.1, ADR-0066 "Not done")
- Context: ADR-0066 made unread code `not_evaluable`, but two gaps remained. First, a requirement
  that belongs to a spec component mapped to an all-TypeScript container stayed `specified`, as if
  nothing had been built. Second, the most common way a TypeScript team names a requirement in its
  tests, `it("RF-008 shows the pending count", …)`, was invisible: only `ad2v:` comments were read.

## Decisions

1. **Component scope.** When a `spec_component` pairs (manifest, name or `manifest_link`) with
   code whose link is `not_evaluable`, each requirement under it that nothing else links becomes
   `not_evaluable`. Its evidence is `{kind: component_out_of_scope, component, languages}`. A
   requirement with its own evaluated link keeps that status. The card names the component and the
   languages.
2. **Test titles in unextracted files.** In a module with `attrs.extracted = false`, string titles
   of `it`, `test`, `describe`, `context` and `suite` calls, `@DisplayName("…")`, Kotlin backtick
   test names and Go `func TestRF001_2` become spec references. Their source is
   `spec_ref_sources: {RF-008: [test_title]}`, and the link evidence is `test_in_unread_language`.
3. **Never `verified`.** ad2v has no results for those tests: JUnit from a JavaScript runner is not
   mapped to unread modules. The link stays `not_evaluable`. Any id that fits the spec-id grammar
   inside a test title counts, as with `ad2v:` comments. Other strings are never read.
4. The polyglot fixture gains `web/src/cart.test.ts` and REQ-004. REQ-003 (under the web component)
   is now `not_evaluable` through `component_out_of_scope`. The brownfield fixture shows both rules
   in Spanish (RF-007/009 by component, RF-008 by test title).

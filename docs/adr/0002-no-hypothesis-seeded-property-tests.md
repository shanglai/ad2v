# ADR-0002: Seeded randomized tests instead of `hypothesis`

- Status: accepted (P1). **Deviation** from the prompt's default tool, as the prompt anticipated.
- Context: the prompt asks for property-based tests of the projection invariant with `hypothesis`,
  provided its license is not copyleft. **`hypothesis` is MPL-2.0**, a weak copyleft license, and the
  project rule is "no GPL/LGPL/AGPL/MPL dependencies", including dev dependencies.
- Decision: property tests draw inputs from `random.Random(987654)`: 500 random traces, both
  DFS-shaped and arbitrary depth sequences, each checked at every detail level. They assert the same
  invariants a `hypothesis` test would. The seed makes failures reproducible.
- Consequences: failing cases are not shrunk. If a failure shows up, the assertion shows the depth
  sequence, and a unit test for it is added by hand.

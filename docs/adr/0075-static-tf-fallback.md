# ADR-0075: The static `.tf` fallback (python-hcl2), infra roots, plan wins

- Status: accepted (P10)
- Context: `history` never has a plan per commit, and many users will not produce one. The
  `.tf` files still say a lot: resources, env var names, references.

## Decisions

1. **Parser.** python-hcl2 8.1.4 (MIT) was evaluated with its full tree:
   - lark 1.3.1 (MIT);
   - regex 2026.9.29 (Apache-2.0 AND CNRI-Python), both permissive.
   The license gate is green with 14 distributions. It is used, pinned (`python-hcl2==8.1.4`,
   `lark==1.3.1`). It is imported only when a static read happens. No minimal stdlib reader was
   needed.
2. **Infra roots.** `infra_root: [infra]` in `ad2v.yaml` lists Terraform root modules: every
   `*.tf` in the folder, not recursive. A root must stay inside the repository. `ad2v init`
   proposes the roots it finds (folders named `modules` excluded). Without `infra_root` there is no
   static read: the zero-config warning (ADR-0073) points at it.
3. **Limits** (documented in `docs/infra.md`):
   - `count`/`for_each` are not expanded: one node with `attrs.multiplicity = "unresolved"`;
   - local modules are followed one level; deeper calls are reported, and remote modules are
     recorded as `infra_module` nodes (`remote: true`);
   - variables stay unresolved and their defaults are never stored;
   - only literals are known, and `locals` are followed for references;
   - `dynamic` blocks and `jsonencode(...)` are opaque (ECS container definitions give names only
     in a plan);
   - files over 4 MB are skipped, at most 2,000 per root; a file that does not parse is reported,
     never fatal.
4. **Environments.** There is one static environment per infra root: `default` for one root,
   otherwise the folder's name.
5. **Plan wins.** When a plan and a static read cover the same environment (same name, or the
   single root against every plan environment), the plan's resources are used. The static read only
   fills gaps: resources that the plan's *configuration* does not declare at all, which means the
   plan is older than the `.tf`. Those nodes keep `source: static` with `gap_fill: true`, and the
   environment root lists them (`filled_from_static`). A resource with `count = 0` is declared, so
   it is not a gap.
6. **History.** Each commit's static read is an epoch input. A commit that only changes `infra/`
   gives an `infra` epoch, and the plan given to the first history epoch is carried forward
   (`gitsource.run_history(infra_plans=…)`).

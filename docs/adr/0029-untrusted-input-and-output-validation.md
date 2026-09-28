# ADR-0029: Repository content is untrusted; outputs are validated deterministically

- Status: accepted (P4)
- Decisions:
  1. **Fences.** Everything cut from the repository (code, comments, specs, prose, and IR digests
     containing names) is wrapped in `<untrusted-data id=… kind=… source=…>` fences. The id is
     derived from the content, and any `untrusted-data` inside the content is neutralized, so data
     cannot close or forge a fence. The system prompt says fenced text is data, and that any
     instructions inside it are to be ignored.
  2. **Strict JSON.** Outputs must parse and validate against the task's JSON Schema (Draft
     2020-12). Then the task's deterministic checks run: evidence ranges inside the lines present
     in the slice, `drift`/`partial` with both spec and code evidence, a non-empty rationale,
     candidate keys that exist, narration steps `0..n-1`, EARS shape, and mentions limited to node
     ids present in the input. An `error` makes the result invalid; it is kept for audit and
     counts as `cannot_tell`. A `warning` is recorded.
  3. **Injection guards.** Instruction-like phrases in the input ("ignore previous instructions",
     "answer conforms", "you are now", …) add warning `injection_suspected`, and such a judgment
     cannot upgrade a status. A long verbatim copy (≥ 60 chars) of fenced repository text in the
     output is flagged `verbatim_copy`. It is an **error only if the copied text itself contains
     an instruction-like phrase** (an echoed injection); otherwise it is a warning. The live run
     showed why: a correct rationale that quoted the requirement sentence was invalidated by the
     first version of the rule. The guard compares only against repository-derived text, not
     against earlier LLM output passed as context (coarser narrations, child summaries).
  4. **Revalidation on cache hits.** Validation is deterministic and cheap, so a cached output is
     re-validated on every hit and its row updated. Fixing a rule never requires paying for a call
     again.

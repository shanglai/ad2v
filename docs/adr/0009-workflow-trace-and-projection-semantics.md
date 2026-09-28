# ADR-0009: Workflow trace and projection semantics

- Status: accepted (P1). §4 amended by ADR-0013 (containment projection is now the default).
- Decisions:
  1. **Depth** is call depth: the port is 0 and its handler 1. A resource touch is one level below
     the function that makes it.
  2. Behavior nodes that lexically enclose a call **ride along** in the callee's step
     (`[loop, fetch_ledger_entry]`). Retry or transaction decorators ride along with the decorated
     function (`[retry, fetch_statement]`).
  3. A fan-out produces **one step that lists all parallel callees**, then expands each callee in
     order.
  4. **Projection is by call depth**, not by containment. `project(steps, k)` groups each step with
     its nearest preceding step of depth ≤ k. That group key only moves forward, so groups are
     contiguous and partition the trace by construction. More detail never merges steps (tested).
     A projection by `contains` ancestry ("collapse by container") can be added later with the same
     return type.
  5. Spec workflows put the Background steps first (from the same Rule, or at feature level).

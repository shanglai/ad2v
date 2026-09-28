# ADR-0011: Content-anchored behavior identity

- Status: accepted (P2). Supersedes the behavior row of format spec v0.1 §3.3. Decided in the P2
  prompt (P1 open question 5).
- Context: v0.1 named behavior nodes `<enclosing>@<kind>#<n>`, where `n` was the ordinal among
  that kind's candidates in the function. Inserting an unrelated loop *above* an existing loop
  renamed it (issue 9 in P1). That breaks the stable-identity principle exactly where P3's
  incremental runs and `stale` detection need it.
- Decision: `<enclosing qname>@<kind>#<anchor>[~n]`, where
  `anchor = sha256_hex(" ".join(header.split()))[:8]` and the header is the construct's
  identifying text: the loop iterable (or `while` condition, or the comprehension's first iterable),
  the decorator for retry/transaction decorators, the argument list of a gather-style fan-out, the
  call expression for executor fan-outs, `Retrying(...)` and `llm_call`, and the with-item for `with
  X.begin()`. Duplicate headers of the same kind in the same scope get `~2`, `~3` in source order.
  Anchors count every candidate, emitted or not.
- Consequences:
  - Inserting or removing an unrelated construct no longer renames the others (tested:
    `test_behavior_ids_survive_an_inserted_loop`). Whitespace inside the header does not matter
    (`test_whitespace_in_header_does_not_change_anchor`).
  - Editing a loop's *header* (e.g. `for tx in transactions` → `for tx in batch`) gives it a new id.
    That is acceptable: it is arguably a different loop, and body edits keep the id.
  - Two loops over the same iterable in one function are ordered by `~n`, so reordering those two
    swaps their ids. This is rare, and documented.
  - 8 hex chars = 32 bits per (scope, kind). A collision needs two *different* headers in the same
    function with the same prefix (≈ 1 in 4·10^9 per pair), and would produce the `~2` suffix rather
    than a crash.
- **One-time id change (safe now, because no external consumers exist and P3 has not stored
  epochs).** In the fixture, all 5 emitted behavior nodes changed ids:

| v0.1 qualified name (suffix) | v0.1 id | v0.2 suffix | v0.2 id |
|---|---|---|---|
| `match_batch@loop#1` | `n_0f37514c69acb5fb770a` | `loop#81dc075c` | `n_92ae1d94a62c8e94d5ca` |
| `classify_unmatched@loop#1` | `n_59033ecedb18bef00ed1` | `loop#bc51e9e6` | `n_71c4fa5e27cf0f45defe` |
| `classify_unmatched@llm_call#1` | `n_eabf505283be102d667d` | `llm_call#67251e28` | `n_023708a64609ad8bd24c` |
| `fetch_statement@retry#1` | `n_b05c2eb7d48b4bceb527` | `retry#297043df` | `n_b2233d0ad432de1f27f5` |
| `fetch_all_statements@fan_out#1` | `n_4c81eff790b623b320da` | `fan_out#809d9005` | `n_f027eae4f6041f58aa8f` |

  No other id changed because of this ADR. The goldens (`expected.yaml` risks, traces and
  severity) were updated.

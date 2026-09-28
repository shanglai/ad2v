# ADR-0019: Test results carry forward; "fresh" results; change_kind

- Status: accepted (P3)
- Decisions:
  1. **Carry forward.** An extraction without `--test-results` inherits the parent's test results
     and `test_results_hash`. Otherwise every history step without a CI artifact would turn
     `verified` links into `implemented`, and the history would flap. The epoch attrs record
     `tests_carried` so the carry is visible.
  2. **Fresh results.** Results are fresh when files were given and their hash differs from the
     parent's. Only fresh passing results can clear a `code_changed_unverified` stale (`retested`,
     ADR-0020). Re-ingesting the same file does not count as re-testing.
  3. **Test-result versions** exclude nothing: `duration_ms` is part of the payload. A JUnit file
     whose only change is timing therefore gives a new epoch with `change_kind = tests_only`. That is
     what the history fixture's step 5b exercises.
  4. **`change_kind`** compares the five input hashes with the parent's: `initial` without a parent;
     `code`, `spec`, `code+spec`, `rules`, `config`, `tests_only` for those exact sets; `mixed`
     otherwise. When no hash changed, nothing is written ("no changes"), so there is no `none`.

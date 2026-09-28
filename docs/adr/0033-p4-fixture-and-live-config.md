# ADR-0033: P4 fixture additions and where the live LLM config lives

- Status: accepted (P4)
- Decisions:
  1. **Planted semantics** (P4 §5.1), with neutral code comments that give the model no hint:
     - REQ-003 is kept, but `amounts_match` now uses `tolerance_cents = 5` inline (drift);
     - new REQ-009 "at most once per run" with `classify_run`, which re-classifies per match
       attempt (drift);
     - new REQ-010 asks for four logged fields and `run_nightly` logs two (partial);
     - REQ-001 is the clear conforming case.

     `expected-judgments.yaml` labels all 11 judgeable links. REQ-006 is labeled `partial` on an
     honest reading of the code.
  2. **Suggestion decoy:** `worker/recon_worker/archive.py::purge_approved_runs` is lexically the
     top candidate for REQ-007 ("approve … run") but only deletes old runs.
  3. **Prose doc:** `specs/operations.md` holds free prose only.
  4. The golden `expected.yaml` changed only by these additions (counts, one risky loop, the
     rollups, and the CLI "Top 6"). No existing id changed.
  5. The live config is `fixtures/payments-recon/llm-vertex.yaml`, with the same `llm:` shape as
     ad2v.yaml, passed with `--manifest`. It stays out of `ad2v.yaml` so offline tests never see
     a live provider.

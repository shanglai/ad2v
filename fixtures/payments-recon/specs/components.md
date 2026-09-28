# Payments reconciliation: specification

This system reconciles bank statements against the internal ledger every night and on demand.
It is operated by the finance-ops team.

## Component: Reconciliation API {#CMP-001}

Serves operators and agents over HTTP and MCP.

- [REQ-001] When an operator submits a set of account ids, the reconciliation API shall start a reconciliation run.
- [REQ-002] When a run starts, the matcher shall pair each bank transaction with a ledger entry by reference and amount.
- [REQ-003] The matcher shall treat amounts that differ by at most one cent as equal.
- [REQ-004] If a transaction remains unmatched, then the classifier shall assign a probable-cause label.
- [REQ-006] When an agent requests a run summary, the MCP server shall return totals for matched and unmatched transactions.
- [REQ-007] When a reviewer approves a completed run, the reconciliation API shall mark the run as approved.
- [REQ-009] If a transaction remains unmatched, then the classifier shall classify it at most once per run.

## Component: Nightly worker {#CMP-002}

Runs the nightly batch and integrates with Pub/Sub.

- [REQ-005] When a nightly run completes, the worker shall publish a run-completed event.
- [REQ-008] While the bank statement feed is unavailable, the worker shall retry with bounded exponential backoff.
- [REQ-010] When a nightly run completes, the worker shall log the run id, the matched count, the unmatched count and the run duration.

## Notes

Runs are immutable once approved. Audit sampling uses a fixed seed so that reviews are
reproducible.

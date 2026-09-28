# payments-recon (ad2v fixture)

A small FastAPI payment-reconciliation service with specs. **This code is only parsed, never run.**
It deliberately contains the patterns that ad2v P1 must detect. See `expected.yaml`.

- `api/`: FastAPI service (`replicas: 2`). It has routes, an N+1 matcher, an LLM classifier, a bank
  client with an unbounded tenacity retry and an `asyncio.gather` fan-out, and a FastMCP tool.
- `worker/`: a nightly job, a Typer CLI, and a Pub/Sub publisher and subscriber.
- `specs/`: OpenAPI, Gherkin and Markdown (EARS) specs.

Randomness is seeded with 987654.

| # | deliberate pattern | where |
|---|---|---|
| 1 | spec'd endpoint not implemented (future `missing`) | `POST /v1/reconciliations/{run_id}/approve` in `specs/openapi.yaml` and scenario "Approve a reconciliation run" |
| 2 | route with no spec (future `orphan`) | `GET /internal/debug/stats` in `api/recon_api/main.py` |
| 3 | DB query per item (`io_in_loop`, N+1) | `matching.match_batch` loop → `db.fetch_ledger_entry` |
| 4 | LLM call in a loop (`llm_in_loop`) | `classify.classify_unmatched` |
| 5 | tenacity retry without `stop=` (`unbounded_retry`) | `bank_client.fetch_statement` |
| 6 | `asyncio.gather` fan-out (`fan_out`) | `bank_client.fetch_all_statements` |
| 7 | `@mcp.tool` | `mcp_server.reconciliation_summary` |
| 8 | Pub/Sub publish (queue) | `worker/recon_worker/events.py` |
| 9 | `# ad2v: REQ-xxx` annotations (one dangling: REQ-099) | routes, matching, classify, events, db |
| 10 | two containers, `api` with `replicas: 2` | `ad2v.yaml` |
| 11 | semantic drift no structural rule catches (P4): the spec says one cent, the code allows 5 | REQ-003, `matching.amounts_match` |
| 12 | semantic drift (P4): "at most once per run", re-classified per match attempt | REQ-009, `classify.classify_run` |
| 13 | partial implementation (P4): 2 of 4 required log fields | REQ-010, `jobs.run_nightly` |
| 14 | lexical decoy for suggestions (P4): "approved runs", but it purges them | `archive.purge_approved_runs` vs REQ-007 |
| 15 | free prose only (P4 prose extraction) | `specs/operations.md` |

Human labels for every judgeable link: `expected-judgments.yaml`. The live LLM config used in P4:
`llm-vertex.yaml`.

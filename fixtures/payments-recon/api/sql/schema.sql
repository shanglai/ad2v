-- Ledger and unmatched rows (P7 fixture: SQL DDL in the schema digest).
CREATE TABLE IF NOT EXISTS ledger (
    reference    TEXT PRIMARY KEY,
    amount_cents INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS unmatched (
    run_id    TEXT NOT NULL REFERENCES recon_runs(run_id),
    reference TEXT NOT NULL,
    UNIQUE (run_id, reference)
);

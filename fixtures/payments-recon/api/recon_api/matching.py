"""Pair bank transactions with ledger entries."""

import uuid

from recon_api import db

AMOUNT_TOLERANCE_CENTS = 1


def match_batch(transactions: list[dict]) -> dict:
    """Match every transaction against the ledger.

    ad2v: REQ-002
    """
    matches, unmatched = [], []
    for tx in transactions:
        entry = db.fetch_ledger_entry(tx["reference"])  # one query per transaction (N+1)
        if entry is not None and amounts_match(tx["amount_cents"], entry["amount_cents"]):
            matches.append({"tx": tx, "entry": entry})
        else:
            unmatched.append(tx)
    return {"run_id": str(uuid.uuid4()), "matches": matches, "unmatched": unmatched}


# ad2v: REQ-003
def amounts_match(a_cents: int, b_cents: int) -> bool:
    return abs(a_cents - b_cents) <= AMOUNT_TOLERANCE_CENTS

"""Nightly reconciliation job."""

import random

from recon_api.matching import match_batch

from recon_worker.events import publish_run_completed

AUDIT_SEED = 987654
AUDIT_SAMPLE_SIZE = 5


def run_nightly(transactions: list[dict]) -> list[dict]:
    result = match_batch(transactions)
    rng = random.Random(AUDIT_SEED)
    sample = rng.sample(result["matches"], k=min(AUDIT_SAMPLE_SIZE, len(result["matches"])))
    publish_run_completed(result["run_id"], len(result["matches"]))
    return sample

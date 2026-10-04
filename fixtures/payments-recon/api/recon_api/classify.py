"""Label unmatched transactions with a probable cause using an LLM."""

import os

import litellm

from recon_api import db

CLASSIFIER_MODEL = os.environ.get("RECON_CLASSIFIER_MODEL", "gpt-4o-mini")
LABELS = ("timing", "fee", "fx", "duplicate", "unknown")


def classify_unmatched(rows: list[dict]) -> list[dict]:
    # ad2v: REQ-004
    out = []
    for row in rows:
        resp = litellm.completion(
            model=CLASSIFIER_MODEL,
            messages=[{"role": "user", "content": f"Classify {row} as one of {LABELS}"}],
        )
        out.append({**row, "label": resp.choices[0].message.content.strip()})
    return out


def classify_run(run: dict) -> list[dict]:
    """Label the unmatched transactions of a reconciliation run.

    ad2v: REQ-009
    """
    labelled = []
    for attempt in run["match_attempts"]:
        labelled.extend(classify_unmatched(attempt["unmatched"]))
    db.save_classifications(run["run_id"], labelled)
    return labelled

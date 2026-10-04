"""Order export (P6.1 Kiro preset fixture). Kiro has no textual ids: ad2v synthesizes them."""

import csv
import io


def export_orders(rows: list[dict]) -> str:
    # ad2v: ORDEREXPORT-1.1, ORDEREXPORT-1.2
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["order", "amount_cents"])
    for r in rows:
        w.writerow([r["order"], r["amount_cents"]])
    return out.getvalue()


def to_cents(amount: float) -> int:
    # ad2v: ORDEREXPORT-2.1
    return round(amount * 100)

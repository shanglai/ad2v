"""Billing (P6.1 custom preset fixture)."""

_next = 0


def issue_invoice(order_id: str) -> int:
    # ad2v: BILL-1, BILL-2
    global _next
    _next += 1
    return _next

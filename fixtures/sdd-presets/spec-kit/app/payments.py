"""Card payments and refunds (P6.1 spec-kit preset fixture)."""


def record_attempt(order_id: str, ok: bool) -> dict:
    # ad2v: 001-payments:FR-002
    return {"order": order_id, "ok": ok}


def charge(order_id: str, total_cents: int) -> bool:
    # ad2v: FR-001
    # A bare FR-001: both 001-payments and 002-refunds define it, so this is never guessed.
    record_attempt(order_id, True)
    return total_cents > 0


def refund(order_id: str, amount_cents: int, charged_cents: int, agent: str) -> int:
    return min(amount_cents, charged_cents)

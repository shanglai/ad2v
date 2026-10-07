"""Backfill script kept next to the SQL migrations (excluded from code extraction)."""


def upgrade(conn) -> None:
    conn.execute("UPDATE movimientos SET estado = 'pendiente' WHERE estado IS NULL")

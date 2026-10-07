"""Reconciliation service of the `table` preset fixture (P9). No ad2v annotations: links come
from test names."""


def iniciar_conciliacion(extracto: list[dict]) -> dict:
    return {"movimientos": len(extracto)}


def exportar_csv(corrida: dict) -> str:
    return "id,monto\n"

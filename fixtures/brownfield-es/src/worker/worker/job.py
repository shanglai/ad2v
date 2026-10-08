import os

COLA_URL = os.environ["COLA_URL"]
LOTE = int(os.getenv("TAMANO_LOTE", "100"))


def procesar_lote(mensajes: list[dict]) -> int:
    return len(mensajes[:LOTE])

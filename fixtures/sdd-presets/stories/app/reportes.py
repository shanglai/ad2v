"""Reports of the `stories` preset fixture (P9). No ad2v annotations: links come from test names."""


def exportar(corrida: dict) -> str:
    return "pareja,monto\n"


def descargar_reporte(corrida: dict) -> bytes:
    return b"%PDF"

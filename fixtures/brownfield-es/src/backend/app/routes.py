from fastapi import APIRouter

from app import conciliacion

router = APIRouter()


@router.post("/conciliaciones")
def iniciar_conciliacion(extracto: list[dict]) -> dict:
    return {"id": conciliacion.iniciar(extracto)}


@router.get("/conciliaciones/{id}")
def obtener_corrida(id: str) -> dict:
    return conciliacion.obtener(id)


@router.get("/conciliaciones/{id}/exportar")
def exportar_corrida(id: str) -> str:
    return conciliacion.exportar_csv(id)

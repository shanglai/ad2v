from app.db import SessionLocal
from app.models import Corrida, Movimiento


def iniciar(extracto: list[dict]) -> str:
    with SessionLocal() as s:
        corrida = Corrida(id="c1", estado="abierta")
        s.add(corrida)
        for m in extracto:
            s.add(Movimiento(corrida_id=corrida.id, monto=m["monto"], estado=emparejar(m)))
        s.commit()
        return corrida.id


def emparejar(movimiento: dict) -> str:
    return "conciliado" if movimiento.get("referencia") else "pendiente"


def obtener(corrida_id: str) -> dict:
    with SessionLocal() as s:
        c = s.get(Corrida, corrida_id)
        return {"id": c.id, "estado": c.estado}


def exportar_csv(corrida_id: str) -> str:
    return "movimiento,monto,estado\n"

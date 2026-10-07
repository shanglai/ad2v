from sqlalchemy import Column, DateTime, Integer, Numeric, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Corrida(Base):
    __tablename__ = "corridas"
    id = Column(String, primary_key=True)
    estado = Column(String, nullable=False)
    aprobada_por = Column(String)
    aprobada_en = Column(DateTime)


class Movimiento(Base):
    __tablename__ = "movimientos"
    id = Column(Integer, primary_key=True)
    corrida_id = Column(String, nullable=False)
    monto = Column(Numeric, nullable=False)
    estado = Column(String, nullable=False)

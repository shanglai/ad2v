"""ORM models for the reconciliation tables (P7 fixture: the datastore schema digest).

`classifications` has no uniqueness on (run_id, reference): nothing in the schema stops a
transaction from being classified twice in one run (REQ-009 says at most once per run).
"""

from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class ReconRun(Base):
    __tablename__ = "recon_runs"
    run_id = Column(String, primary_key=True)
    matched = Column(Integer, nullable=False)


class Classification(Base):
    __tablename__ = "classifications"
    id = Column(Integer, primary_key=True)
    run_id = Column(String, ForeignKey("recon_runs.run_id"), nullable=False)
    reference = Column(String, nullable=False)
    label = Column(String)

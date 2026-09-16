import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, Float, Integer, String
from sqlalchemy.orm import Mapped

from app.database import Base

PROCESS_ROUTE = ["ETCH", "CVD", "CMP", "INSPECT"]


class EquipmentStatus(str, enum.Enum):
    RUN = "RUN"
    IDLE = "IDLE"
    DOWN = "DOWN"


class LotStatus(str, enum.Enum):
    WAITING = "WAITING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    HOLD = "HOLD"


class Equipment(Base):
    __tablename__ = "equipment"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    process_step = Column(String, index=True)
    status = Column(Enum(EquipmentStatus), default=EquipmentStatus.IDLE)
    run_seconds: Mapped[float] = Column(Float, default=0.0)
    last_status_change = Column(DateTime, default=datetime.utcnow)


class Lot(Base):
    __tablename__ = "lots"

    id = Column(Integer, primary_key=True, index=True)
    product = Column(String, index=True)
    quantity = Column(Integer)
    step_index = Column(Integer, default=0)
    status = Column(Enum(LotStatus), default=LotStatus.WAITING)
    is_scrap = Column(Integer, default=0)  # 0/1 flag, simple yield model
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

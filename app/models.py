import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, Enum, Float, ForeignKey, Integer, String, UniqueConstraint
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


class LotEventType(str, enum.Enum):
    LOT_CREATED = "LOT_CREATED"
    LOT_HELD = "LOT_HELD"
    LOT_RELEASED_FROM_HOLD = "LOT_RELEASED_FROM_HOLD"
    PROCESS_COMPLETED = "PROCESS_COMPLETED"
    LOT_COMPLETED = "LOT_COMPLETED"


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


class LotEvent(Base):
    """Immutable journal entry for reconstructing a lot's production history.

    This is deliberately a database journal, not a broker message.  It is
    committed in the same transaction as the Lot state change so traceability
    does not depend on an external messaging system being available.
    """

    __tablename__ = "lot_events"
    __table_args__ = (
        UniqueConstraint("lot_id", "sequence_number", name="uq_lot_event_sequence"),
    )

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String, unique=True, index=True, default=lambda: str(uuid4()))
    lot_id = Column(Integer, ForeignKey("lots.id"), nullable=False, index=True)
    sequence_number = Column(Integer, nullable=False)
    event_type = Column(Enum(LotEventType), nullable=False, index=True)
    process_step = Column(String, nullable=True, index=True)
    equipment_id = Column(Integer, ForeignKey("equipment.id"), nullable=True, index=True)
    from_status = Column(Enum(LotStatus), nullable=True)
    to_status = Column(Enum(LotStatus), nullable=False)
    occurred_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

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
    QUALITY_HOLD = "QUALITY_HOLD"
    REWORK = "REWORK"
    SCRAPPED = "SCRAPPED"


class LotEventType(str, enum.Enum):
    LOT_CREATED = "LOT_CREATED"
    LOT_HELD = "LOT_HELD"
    LOT_RELEASED_FROM_HOLD = "LOT_RELEASED_FROM_HOLD"
    PROCESS_COMPLETED = "PROCESS_COMPLETED"
    LOT_COMPLETED = "LOT_COMPLETED"
    DEFECT_RECORDED = "DEFECT_RECORDED"
    LOT_SCRAPPED = "LOT_SCRAPPED"
    LOT_REWORKED = "LOT_REWORKED"
    LOT_REWORK_RELEASED = "LOT_REWORK_RELEASED"


class InspectionResult(str, enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class QualityDisposition(str, enum.Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    SCRAP = "SCRAP"
    REWORK = "REWORK"


class WorkOrderStatus(str, enum.Enum):
    CREATED = "CREATED"
    RELEASED = "RELEASED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Product(Base):
    __tablename__ = "products"

    code = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    route_name = Column(String, nullable=False, default="DEFAULT_ROUTE")
    route_version = Column(Integer, nullable=False, default=1)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id = Column(Integer, primary_key=True, index=True)
    order_no = Column(String, nullable=False, unique=True, index=True)
    product_code = Column(String, ForeignKey("products.code"), nullable=False, index=True)
    planned_quantity = Column(Integer, nullable=False)
    released_quantity = Column(Integer, nullable=False, default=0)
    completed_quantity = Column(Integer, nullable=False, default=0)
    priority = Column(Integer, nullable=False, default=5)
    due_at = Column(DateTime, nullable=True, index=True)
    status = Column(
        Enum(WorkOrderStatus), nullable=False, default=WorkOrderStatus.CREATED, index=True
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Equipment(Base):
    __tablename__ = "equipment"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    process_step = Column(String, index=True)
    status = Column(Enum(EquipmentStatus), default=EquipmentStatus.IDLE)
    run_seconds: Mapped[float] = Column(Float, default=0.0)
    down_seconds: Mapped[float] = Column(Float, default=0.0)
    dispatch_count = Column(Integer, nullable=False, default=0)
    last_status_change = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


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


class EquipmentDowntimeEvent(Base):
    """One DOWN stretch for one piece of equipment: when it started, when (if
    ever) it ended, and why.

    ``Equipment.down_seconds`` only ever holds a running total, so it cannot
    answer "how many times has this tool gone down" or "how long did each
    individual outage last" — both are needed for MTBF/MTTR and for auditing
    that the running total itself is right. ``ended_at``/``duration_seconds``
    stay NULL while the outage is still open (mirrors LotEvent's open/closed
    HOLD pairing in _equipment_hold_wait_metrics).
    """

    __tablename__ = "equipment_downtime_events"

    id = Column(Integer, primary_key=True, index=True)
    equipment_id = Column(Integer, ForeignKey("equipment.id"), nullable=False, index=True)
    reason = Column(String, nullable=False)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    ended_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)


class WorkOrderLot(Base):
    __tablename__ = "work_order_lots"
    __table_args__ = (UniqueConstraint("lot_id", name="uq_work_order_lot_lot_id"),)

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False, index=True)
    lot_id = Column(Integer, ForeignKey("lots.id"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class QualityInspection(Base):
    __tablename__ = "quality_inspections"
    __table_args__ = (
        UniqueConstraint("lot_id", "attempt_number", name="uq_quality_lot_attempt"),
    )

    id = Column(Integer, primary_key=True, index=True)
    inspection_id = Column(String, unique=True, index=True, default=lambda: str(uuid4()))
    lot_id = Column(Integer, ForeignKey("lots.id"), nullable=False, index=True)
    attempt_number = Column(Integer, nullable=False)
    process_step = Column(String, nullable=False, index=True)
    equipment_id = Column(Integer, ForeignKey("equipment.id"), nullable=True, index=True)
    result = Column(Enum(InspectionResult), nullable=False, index=True)
    defect_code = Column(String, nullable=True, index=True)
    disposition = Column(
        Enum(QualityDisposition), nullable=False, default=QualityDisposition.NONE, index=True
    )
    inspected_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class AnomalyLog(Base):
    """Persisted record of a quality anomaly the system detected on its own.

    /quality/anomalies computes this signal live from QualityInspection rows
    on every request and forgets it the moment the response is sent — there
    was no history of *when* an anomaly first appeared or how it evolved.
    The simulation engine periodically runs the same detection and writes a
    row here (throttled per equipment so a standing anomaly doesn't spam one
    row per tick), giving the dashboard's Anomaly Log page something to show
    and a paper trail independent of any one live poll.
    """

    __tablename__ = "anomaly_log"

    id = Column(Integer, primary_key=True, index=True)
    detected_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    equipment_id = Column(Integer, ForeignKey("equipment.id"), nullable=False, index=True)
    equipment_name = Column(String, nullable=False)
    process_step = Column(String, nullable=False, index=True)
    severity = Column(String, nullable=False, index=True)
    defect_rate = Column(Float, nullable=False)
    peer_mean_rate = Column(Float, nullable=False)
    z_score = Column(Float, nullable=True)
    total_inspections = Column(Integer, nullable=False)
    method = Column(String, nullable=False)
    note = Column(String, nullable=True)

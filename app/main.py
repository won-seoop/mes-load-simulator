from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, pstdev

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import case, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine, get_db
from app.models import (
    PROCESS_ROUTE,
    AnomalyLog,
    Equipment,
    EquipmentStatus,
    InspectionResult,
    Lot,
    LotEvent,
    LotEventType,
    LotStatus,
    Product,
    QualityDisposition,
    QualityInspection,
    WorkOrder,
    WorkOrderLot,
    WorkOrderStatus,
)
from app.schemas import (
    AnomalyLogOut,
    EquipmentOut,
    EquipmentQualityAnomalyOut,
    EquipmentStatusUpdate,
    LotCreate,
    LotEventOut,
    LotOut,
    MetricsOut,
    ProductCreate,
    ProductOut,
    QualityDispositionCreate,
    QualityInspectionCreate,
    QualityInspectionOut,
    QualityMetricsOut,
    QualityAnomalyReportOut,
    ReworkReleaseCreate,
    WorkOrderCreate,
    WorkOrderLotCreate,
    WorkOrderOut,
)
from app.simulation import engine as simulation_engine
from app.state_machine import ensure_lot_transition
from app.timeutils import kst_midnight_utc

Base.metadata.create_all(bind=engine)

app = FastAPI(title="MES Simulator", version="0.1.0")

DEFAULT_PRODUCTS = (
    ("WAFER-A", "Wafer A"),
    ("WAFER-B", "Wafer B"),
    ("PANEL-X", "Panel X"),
    ("PANEL-Y", "Panel Y"),
)

# A lot may be sent through one corrective rework cycle. Repeatedly routing a
# known-bad lot through the same equipment hides a persistent defect and can
# grow WIP forever, so a second failed inspection must be dispositioned SCRAP.
MAX_REWORK_CYCLES = 1
ANOMALY_MIN_INSPECTIONS = 10
ANOMALY_MIN_RATE_DELTA = 0.10
ANOMALY_MIN_Z_SCORE = 2.0


def _append_lot_event(
    db: Session,
    lot: Lot,
    event_type: LotEventType,
    *,
    to_status: LotStatus,
    from_status: LotStatus | None = None,
    process_step: str | None = None,
    equipment_id: int | None = None,
    occurred_at: datetime | None = None,
) -> LotEvent:
    """Append the next immutable event for a lot inside the caller's transaction."""
    last_sequence = (
        db.query(func.max(LotEvent.sequence_number))
        .filter(LotEvent.lot_id == lot.id)
        .scalar()
        or 0
    )
    event = LotEvent(
        lot_id=lot.id,
        sequence_number=last_sequence + 1,
        event_type=event_type,
        process_step=process_step,
        equipment_id=equipment_id,
        from_status=from_status,
        to_status=to_status,
        occurred_at=occurred_at or datetime.utcnow(),
    )
    db.add(event)
    # SessionLocal uses autoflush=False. Flush here so another event appended
    # in the same transaction observes this sequence number.
    db.flush()
    return event


def _effective_run_seconds(eq: Equipment, now: datetime) -> float:
    """run_seconds plus any time accrued in the current RUN stretch that
    hasn't been flushed into run_seconds yet (that only happens on the next
    status change)."""
    if eq.status == EquipmentStatus.RUN:
        return eq.run_seconds + (now - eq.last_status_change).total_seconds()
    return eq.run_seconds


def _equipment_hold_wait_metrics(db: Session, now: datetime) -> dict:
    """How long lots actually wait in equipment-down HOLD, from the event journal.

    The Lot table only shows that a lot is currently HOLD, not since when, so
    a stuck lot and a lot held one second ago look identical. This walks the
    LOT_HELD / LOT_RELEASED_FROM_HOLD journal to recover both how long
    currently-held lots have been waiting and how long past holds took to
    clear, which is what actually locates a bottleneck step.
    """
    hold_events = (
        db.query(LotEvent)
        .filter(
            LotEvent.event_type.in_(
                [LotEventType.LOT_HELD, LotEventType.LOT_RELEASED_FROM_HOLD]
            )
        )
        .order_by(LotEvent.lot_id, LotEvent.sequence_number)
        .all()
    )
    resolved_durations: list[float] = []
    open_hold_started_at: dict[int, datetime] = {}
    for event in hold_events:
        if event.event_type == LotEventType.LOT_HELD:
            open_hold_started_at[event.lot_id] = event.occurred_at
        else:
            started_at = open_hold_started_at.pop(event.lot_id, None)
            if started_at is not None:
                resolved_durations.append((event.occurred_at - started_at).total_seconds())

    held_lot_ids = {
        lot_id for (lot_id,) in db.query(Lot.id).filter(Lot.status == LotStatus.HOLD).all()
    }
    current_waits = [
        (now - started_at).total_seconds()
        for lot_id, started_at in open_hold_started_at.items()
        if lot_id in held_lot_ids
    ]

    return {
        "lots_on_hold_count": len(current_waits),
        "longest_current_hold_seconds": round(max(current_waits), 1) if current_waits else None,
        "avg_resolved_hold_seconds": (
            round(mean(resolved_durations), 1) if resolved_durations else None
        ),
    }


def _compare_and_set_lot(
    db: Session,
    lot: Lot,
    *,
    expected_status: LotStatus,
    expected_step_index: int,
    expected_updated_at: datetime | None = None,
    values: dict,
) -> bool:
    """Apply one lot transition only if its observed state is still current.

    SQLite serializes concurrent writers. Once the first request commits, a
    competing request's conditional UPDATE matches zero rows and becomes a
    business conflict instead of advancing the same lot twice.
    """
    conditions = [
        Lot.id == lot.id,
        Lot.status == expected_status,
        Lot.step_index == expected_step_index,
    ]
    if expected_updated_at is not None:
        conditions.append(Lot.updated_at == expected_updated_at)
    result = db.execute(
        update(Lot)
        .where(*conditions)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        return False
    db.expire(lot)
    db.refresh(lot)
    return True


def _raise_lot_conflict(lot_id: int) -> None:
    raise HTTPException(
        409,
        f"lot {lot_id} changed concurrently; reload its current state and retry",
    )


def _complete_work_order_for_lot(db: Session, lot: Lot, now: datetime) -> None:
    association = (
        db.query(WorkOrderLot).filter(WorkOrderLot.lot_id == lot.id).one_or_none()
    )
    if not association:
        return
    db.execute(
        update(WorkOrder)
        .where(WorkOrder.id == association.work_order_id)
        .values(
            completed_quantity=WorkOrder.completed_quantity + lot.quantity,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    db.flush()
    work_order = db.get(WorkOrder, association.work_order_id)
    db.refresh(work_order)
    if work_order.completed_quantity >= work_order.planned_quantity:
        work_order.status = WorkOrderStatus.COMPLETED


@app.on_event("startup")
def seed_equipment():
    db = SessionLocal()
    try:
        if db.query(Equipment).count() == 0:
            for step in PROCESS_ROUTE:
                for i in range(1, 4):
                    db.add(
                        Equipment(
                            name=f"{step}-{i:02d}",
                            process_step=step,
                            status=EquipmentStatus.IDLE,
                        )
                    )
        for code, name in DEFAULT_PRODUCTS:
            if not db.get(Product, code):
                db.add(Product(code=code, name=name))
        db.commit()
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/products", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db)):
    return db.query(Product).order_by(Product.code).all()


@app.post("/products", response_model=ProductOut)
def create_product(body: ProductCreate, db: Session = Depends(get_db)):
    product = Product(**body.model_dump())
    db.add(product)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"product {body.code} already exists")
    db.refresh(product)
    return product


@app.post("/work-orders", response_model=WorkOrderOut)
def create_work_order(body: WorkOrderCreate, db: Session = Depends(get_db)):
    product = db.get(Product, body.product_code)
    if not product:
        raise HTTPException(422, f"product {body.product_code} does not exist")
    if not product.is_active:
        raise HTTPException(409, f"product {body.product_code} is inactive")
    work_order = WorkOrder(**body.model_dump(), status=WorkOrderStatus.CREATED)
    db.add(work_order)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"work order {body.order_no} already exists")
    db.refresh(work_order)
    return work_order


@app.get("/work-orders", response_model=list[WorkOrderOut])
def list_work_orders(db: Session = Depends(get_db)):
    return db.query(WorkOrder).order_by(WorkOrder.id.desc()).limit(200).all()


@app.get("/work-orders/{work_order_id}", response_model=WorkOrderOut)
def get_work_order(work_order_id: int, db: Session = Depends(get_db)):
    work_order = db.get(WorkOrder, work_order_id)
    if not work_order:
        raise HTTPException(404, "work order not found")
    return work_order


@app.post("/work-orders/{work_order_id}/release", response_model=WorkOrderOut)
def release_work_order(work_order_id: int, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    result = db.execute(
        update(WorkOrder)
        .where(
            WorkOrder.id == work_order_id,
            WorkOrder.status == WorkOrderStatus.CREATED,
        )
        .values(status=WorkOrderStatus.RELEASED, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        work_order = db.get(WorkOrder, work_order_id)
        if not work_order:
            raise HTTPException(404, "work order not found")
        raise HTTPException(409, f"work order is {work_order.status}, cannot release")
    db.commit()
    return db.get(WorkOrder, work_order_id)


@app.post("/work-orders/{work_order_id}/lots", response_model=LotOut)
def create_work_order_lot(
    work_order_id: int,
    body: WorkOrderLotCreate,
    db: Session = Depends(get_db),
):
    work_order = db.get(WorkOrder, work_order_id)
    if not work_order:
        raise HTTPException(404, "work order not found")
    now = datetime.utcnow()
    result = db.execute(
        update(WorkOrder)
        .where(
            WorkOrder.id == work_order_id,
            WorkOrder.status.in_(
                [WorkOrderStatus.RELEASED, WorkOrderStatus.IN_PROGRESS]
            ),
            WorkOrder.released_quantity + body.quantity
            <= WorkOrder.planned_quantity,
        )
        .values(
            released_quantity=WorkOrder.released_quantity + body.quantity,
            status=WorkOrderStatus.IN_PROGRESS,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        current = db.get(WorkOrder, work_order_id)
        if current.status not in (
            WorkOrderStatus.RELEASED,
            WorkOrderStatus.IN_PROGRESS,
        ):
            raise HTTPException(409, f"work order is {current.status}, cannot create lot")
        raise HTTPException(409, "lot quantity exceeds remaining planned quantity")

    lot = Lot(
        product=work_order.product_code,
        quantity=body.quantity,
        status=LotStatus.WAITING,
    )
    db.add(lot)
    db.flush()
    db.add(WorkOrderLot(work_order_id=work_order_id, lot_id=lot.id))
    _append_lot_event(
        db,
        lot,
        LotEventType.LOT_CREATED,
        to_status=LotStatus.WAITING,
        occurred_at=now,
    )
    db.commit()
    db.refresh(lot)
    return lot


@app.get("/work-orders/{work_order_id}/lots", response_model=list[LotOut])
def list_work_order_lots(work_order_id: int, db: Session = Depends(get_db)):
    if not db.get(WorkOrder, work_order_id):
        raise HTTPException(404, "work order not found")
    return (
        db.query(Lot)
        .join(WorkOrderLot, WorkOrderLot.lot_id == Lot.id)
        .filter(WorkOrderLot.work_order_id == work_order_id)
        .order_by(Lot.id)
        .all()
    )


@app.get("/equipment", response_model=list[EquipmentOut])
def list_equipment(db: Session = Depends(get_db)):
    return db.query(Equipment).all()


@app.get("/equipment/{equipment_id}/events", response_model=list[LotEventOut])
def list_equipment_events(equipment_id: int, db: Session = Depends(get_db)):
    """Recent lot events this equipment appears in — process dispatches and,
    for INSPECT tools, the quality events recorded with its equipment_id too
    (inspect_lot/disposition_lot pass the inspecting tool's id through) —
    so one feed covers both a station's process activity and its defect
    history without a second endpoint."""
    if not db.get(Equipment, equipment_id):
        raise HTTPException(404, "equipment not found")
    return (
        db.query(LotEvent)
        .filter(LotEvent.equipment_id == equipment_id)
        .order_by(LotEvent.occurred_at.desc())
        .limit(100)
        .all()
    )


@app.patch("/equipment/{equipment_id}/status", response_model=EquipmentOut)
def set_equipment_status(
    equipment_id: int, body: EquipmentStatusUpdate, db: Session = Depends(get_db)
):
    eq = db.get(Equipment, equipment_id)
    if not eq:
        raise HTTPException(404, "equipment not found")
    now = datetime.utcnow()
    if eq.status == EquipmentStatus.RUN:
        eq.run_seconds += (now - eq.last_status_change).total_seconds()
    eq.status = body.status
    eq.last_status_change = now
    db.commit()
    db.refresh(eq)
    return eq


@app.post("/lots", response_model=LotOut)
def create_lot(body: LotCreate, db: Session = Depends(get_db)):
    lot = Lot(product=body.product, quantity=body.quantity, status=LotStatus.WAITING)
    db.add(lot)
    db.flush()
    _append_lot_event(
        db,
        lot,
        LotEventType.LOT_CREATED,
        to_status=LotStatus.WAITING,
        occurred_at=lot.created_at,
    )
    db.commit()
    db.refresh(lot)
    return lot


@app.get("/lots", response_model=list[LotOut])
def list_lots(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Lot)
    if status:
        q = q.filter(Lot.status == status)
    return q.order_by(Lot.id.desc()).limit(200).all()


@app.get("/lots/{lot_id}", response_model=LotOut)
def get_lot(lot_id: int, db: Session = Depends(get_db)):
    lot = db.get(Lot, lot_id)
    if not lot:
        raise HTTPException(404, "lot not found")
    return lot


@app.get("/lots/{lot_id}/events", response_model=list[LotEventOut])
def list_lot_events(lot_id: int, db: Session = Depends(get_db)):
    if not db.get(Lot, lot_id):
        raise HTTPException(404, "lot not found")
    return (
        db.query(LotEvent)
        .filter(LotEvent.lot_id == lot_id)
        .order_by(LotEvent.sequence_number)
        .all()
    )


@app.post("/lots/{lot_id}/advance", response_model=LotOut)
def advance_lot(lot_id: int, db: Session = Depends(get_db)):
    lot = db.get(Lot, lot_id)
    if not lot:
        raise HTTPException(404, "lot not found")
    if lot.status not in (LotStatus.WAITING, LotStatus.PROCESSING, LotStatus.HOLD):
        raise HTTPException(409, f"lot is {lot.status}, cannot advance")
    # A HOLD lot is retried at its current step once equipment frees up,
    # rather than being stuck forever (equipment down is a transient state).

    previous_status = lot.status
    step = PROCESS_ROUTE[lot.step_index]
    now = datetime.utcnow()
    candidates = (
        db.query(Equipment)
        .filter(Equipment.process_step == step, Equipment.status != EquipmentStatus.DOWN)
        .all()
    )
    # Wall-clock RUN time converges even when assignments are skewed because
    # this simulator leaves tools in RUN. Use completed dispatch count as the
    # primary fairness signal and run time only as a deterministic tie-breaker.
    eq = min(
        candidates,
        key=lambda e: (e.dispatch_count, _effective_run_seconds(e, now), e.id),
        default=None,
    )
    if not eq:
        if previous_status != LotStatus.HOLD:
            ensure_lot_transition(previous_status, LotStatus.HOLD)
            transitioned = _compare_and_set_lot(
                db,
                lot,
                expected_status=previous_status,
                expected_step_index=lot.step_index,
                values={"status": LotStatus.HOLD, "updated_at": now},
            )
            if not transitioned:
                _raise_lot_conflict(lot_id)
            _append_lot_event(
                db,
                lot,
                LotEventType.LOT_HELD,
                from_status=previous_status,
                to_status=LotStatus.HOLD,
                process_step=step,
                occurred_at=now,
            )
        db.commit()
        db.refresh(lot)
        return lot

    if eq.status == EquipmentStatus.RUN:
        eq.run_seconds += (now - eq.last_status_change).total_seconds()
    eq.status = EquipmentStatus.RUN
    eq.last_status_change = now
    eq.dispatch_count += 1

    expected_step_index = lot.step_index
    next_step_index = expected_step_index + 1
    next_status = (
        LotStatus.QUALITY_HOLD
        if next_step_index >= len(PROCESS_ROUTE)
        else LotStatus.PROCESSING
    )
    ensure_lot_transition(previous_status, next_status)
    transition_values = {
        "step_index": next_step_index,
        "status": next_status,
        "updated_at": now,
    }

    transitioned = _compare_and_set_lot(
        db,
        lot,
        expected_status=previous_status,
        expected_step_index=expected_step_index,
        values=transition_values,
    )
    if not transitioned:
        _raise_lot_conflict(lot_id)

    if previous_status == LotStatus.HOLD:
        _append_lot_event(
            db,
            lot,
            LotEventType.LOT_RELEASED_FROM_HOLD,
            from_status=LotStatus.HOLD,
            to_status=LotStatus.PROCESSING,
            process_step=step,
            equipment_id=eq.id,
            occurred_at=now,
        )

    process_from_status = (
        LotStatus.PROCESSING if previous_status == LotStatus.HOLD else previous_status
    )
    _append_lot_event(
        db,
        lot,
        LotEventType.PROCESS_COMPLETED,
        from_status=process_from_status,
        to_status=lot.status,
        process_step=step,
        equipment_id=eq.id,
        occurred_at=now,
    )
    db.commit()
    db.refresh(lot)
    return lot


@app.get("/lots/{lot_id}/inspections", response_model=list[QualityInspectionOut])
def list_quality_inspections(lot_id: int, db: Session = Depends(get_db)):
    if not db.get(Lot, lot_id):
        raise HTTPException(404, "lot not found")
    return (
        db.query(QualityInspection)
        .filter(QualityInspection.lot_id == lot_id)
        .order_by(QualityInspection.attempt_number)
        .all()
    )


@app.post("/lots/{lot_id}/inspections", response_model=QualityInspectionOut)
def inspect_lot(
    lot_id: int,
    body: QualityInspectionCreate,
    db: Session = Depends(get_db),
):
    lot = db.get(Lot, lot_id)
    if not lot:
        raise HTTPException(404, "lot not found")
    if lot.status != LotStatus.QUALITY_HOLD:
        raise HTTPException(409, f"lot is {lot.status}, not awaiting inspection")
    if body.result == InspectionResult.FAIL and not body.defect_code:
        raise HTTPException(422, "defect_code is required for failed inspection")
    if body.result == InspectionResult.PASS and body.defect_code:
        raise HTTPException(422, "passing inspection cannot have a defect_code")

    pending_failure = (
        db.query(QualityInspection)
        .filter(
            QualityInspection.lot_id == lot_id,
            QualityInspection.result == InspectionResult.FAIL,
            QualityInspection.disposition == QualityDisposition.PENDING,
        )
        .first()
    )
    if pending_failure:
        raise HTTPException(409, "failed inspection requires disposition first")

    last_process = (
        db.query(LotEvent)
        .filter(
            LotEvent.lot_id == lot_id,
            LotEvent.event_type == LotEventType.PROCESS_COMPLETED,
            LotEvent.process_step == "INSPECT",
        )
        .order_by(LotEvent.sequence_number.desc())
        .first()
    )
    attempt_number = (
        db.query(func.max(QualityInspection.attempt_number))
        .filter(QualityInspection.lot_id == lot_id)
        .scalar()
        or 0
    ) + 1
    now = datetime.utcnow()
    previous_updated_at = lot.updated_at
    next_status = (
        LotStatus.DONE if body.result == InspectionResult.PASS else LotStatus.QUALITY_HOLD
    )
    values = {"status": next_status, "updated_at": now}
    if next_status == LotStatus.DONE:
        ensure_lot_transition(LotStatus.QUALITY_HOLD, LotStatus.DONE)
        values["completed_at"] = now
    transitioned = _compare_and_set_lot(
        db,
        lot,
        expected_status=LotStatus.QUALITY_HOLD,
        expected_step_index=lot.step_index,
        expected_updated_at=previous_updated_at,
        values=values,
    )
    if not transitioned:
        _raise_lot_conflict(lot_id)

    inspection = QualityInspection(
        lot_id=lot_id,
        attempt_number=attempt_number,
        process_step="INSPECT",
        equipment_id=last_process.equipment_id if last_process else None,
        result=body.result,
        defect_code=body.defect_code,
        disposition=(
            QualityDisposition.NONE
            if body.result == InspectionResult.PASS
            else QualityDisposition.PENDING
        ),
        inspected_at=now,
    )
    db.add(inspection)
    if body.result == InspectionResult.FAIL:
        _append_lot_event(
            db,
            lot,
            LotEventType.DEFECT_RECORDED,
            from_status=LotStatus.QUALITY_HOLD,
            to_status=LotStatus.QUALITY_HOLD,
            process_step="INSPECT",
            equipment_id=inspection.equipment_id,
            occurred_at=now,
        )
    else:
        _append_lot_event(
            db,
            lot,
            LotEventType.LOT_COMPLETED,
            from_status=LotStatus.QUALITY_HOLD,
            to_status=LotStatus.DONE,
            process_step="INSPECT",
            equipment_id=inspection.equipment_id,
            occurred_at=now,
        )
        _complete_work_order_for_lot(db, lot, now)
    db.commit()
    db.refresh(inspection)
    return inspection


@app.post("/lots/{lot_id}/quality-disposition", response_model=LotOut)
def disposition_lot(
    lot_id: int,
    body: QualityDispositionCreate,
    db: Session = Depends(get_db),
):
    if body.disposition not in (QualityDisposition.SCRAP, QualityDisposition.REWORK):
        raise HTTPException(422, "disposition must be SCRAP or REWORK")
    lot = db.get(Lot, lot_id)
    if not lot:
        raise HTTPException(404, "lot not found")
    if lot.status != LotStatus.QUALITY_HOLD:
        raise HTTPException(409, f"lot is {lot.status}, cannot disposition")
    inspection = (
        db.query(QualityInspection)
        .filter(
            QualityInspection.lot_id == lot_id,
            QualityInspection.result == InspectionResult.FAIL,
            QualityInspection.disposition == QualityDisposition.PENDING,
        )
        .order_by(QualityInspection.attempt_number.desc())
        .first()
    )
    if not inspection:
        raise HTTPException(409, "no failed inspection is awaiting disposition")

    if body.disposition == QualityDisposition.REWORK:
        previous_reworks = (
            db.query(QualityInspection)
            .filter(
                QualityInspection.lot_id == lot_id,
                QualityInspection.disposition == QualityDisposition.REWORK,
            )
            .count()
        )
        if previous_reworks >= MAX_REWORK_CYCLES:
            raise HTTPException(
                409,
                "maximum rework cycles reached; SCRAP disposition is required",
            )

    now = datetime.utcnow()
    next_status = (
        LotStatus.SCRAPPED
        if body.disposition == QualityDisposition.SCRAP
        else LotStatus.REWORK
    )
    ensure_lot_transition(LotStatus.QUALITY_HOLD, next_status)
    values = {"status": next_status, "updated_at": now}
    if next_status == LotStatus.SCRAPPED:
        values["is_scrap"] = 1
    transitioned = _compare_and_set_lot(
        db,
        lot,
        expected_status=LotStatus.QUALITY_HOLD,
        expected_step_index=lot.step_index,
        expected_updated_at=lot.updated_at,
        values=values,
    )
    if not transitioned:
        _raise_lot_conflict(lot_id)
    inspection.disposition = body.disposition
    _append_lot_event(
        db,
        lot,
        (
            LotEventType.LOT_SCRAPPED
            if next_status == LotStatus.SCRAPPED
            else LotEventType.LOT_REWORKED
        ),
        from_status=LotStatus.QUALITY_HOLD,
        to_status=next_status,
        process_step="INSPECT",
        equipment_id=inspection.equipment_id,
        occurred_at=now,
    )
    db.commit()
    db.refresh(lot)
    return lot


@app.post("/lots/{lot_id}/rework-release", response_model=LotOut)
def release_rework(
    lot_id: int,
    body: ReworkReleaseCreate,
    db: Session = Depends(get_db),
):
    lot = db.get(Lot, lot_id)
    if not lot:
        raise HTTPException(404, "lot not found")
    if lot.status != LotStatus.REWORK:
        raise HTTPException(409, f"lot is {lot.status}, cannot release rework")
    now = datetime.utcnow()
    ensure_lot_transition(LotStatus.REWORK, LotStatus.WAITING)
    transitioned = _compare_and_set_lot(
        db,
        lot,
        expected_status=LotStatus.REWORK,
        expected_step_index=lot.step_index,
        expected_updated_at=lot.updated_at,
        values={
            "status": LotStatus.WAITING,
            "step_index": body.step_index,
            "updated_at": now,
        },
    )
    if not transitioned:
        _raise_lot_conflict(lot_id)
    _append_lot_event(
        db,
        lot,
        LotEventType.LOT_REWORK_RELEASED,
        from_status=LotStatus.REWORK,
        to_status=LotStatus.WAITING,
        process_step=PROCESS_ROUTE[body.step_index],
        occurred_at=now,
    )
    db.commit()
    db.refresh(lot)
    return lot


@app.get("/quality/metrics", response_model=QualityMetricsOut)
def quality_metrics(db: Session = Depends(get_db)):
    total = db.query(QualityInspection).count()
    passed = db.query(QualityInspection).filter(QualityInspection.result == InspectionResult.PASS).count()
    failed = total - passed
    inspected_lots = db.query(func.count(func.distinct(QualityInspection.lot_id))).scalar() or 0
    first_pass = db.query(QualityInspection).filter(
        QualityInspection.attempt_number == 1,
        QualityInspection.result == InspectionResult.PASS,
    ).count()
    scrap_count = db.query(QualityInspection).filter(
        QualityInspection.disposition == QualityDisposition.SCRAP
    ).count()
    rework_count = db.query(QualityInspection).filter(
        QualityInspection.disposition == QualityDisposition.REWORK
    ).count()
    process_rows = (
        db.query(QualityInspection.process_step, func.count(QualityInspection.id))
        .filter(QualityInspection.result == InspectionResult.FAIL)
        .group_by(QualityInspection.process_step)
        .all()
    )
    equipment_rows = (
        db.query(Equipment.name, func.count(QualityInspection.id))
        .join(QualityInspection, QualityInspection.equipment_id == Equipment.id)
        .filter(QualityInspection.result == InspectionResult.FAIL)
        .group_by(Equipment.name)
        .all()
    )
    return QualityMetricsOut(
        total_inspections=total,
        pass_count=passed,
        fail_count=failed,
        defect_rate=round(failed / total, 4) if total else 0.0,
        first_pass_yield=round(first_pass / inspected_lots, 4) if inspected_lots else 1.0,
        scrap_count=scrap_count,
        rework_count=rework_count,
        rework_rate=round(rework_count / inspected_lots, 4) if inspected_lots else 0.0,
        defects_by_process=dict(process_rows),
        defects_by_equipment=dict(equipment_rows),
    )


ANOMALY_METHOD = "same-process peer defect-rate comparison"


def _detect_quality_anomalies(db: Session) -> list[EquipmentQualityAnomalyOut]:
    """Detect equipment-correlated quality shifts using transparent peer statistics.

    This deterministic baseline deliberately stays outside an LLM. An agent may
    explain and investigate these results, but the underlying counts, rates and
    thresholds remain reproducible from inspection records. Shared by the
    /quality/anomalies endpoint and the simulation engine's periodic check
    that persists findings to AnomalyLog, so both always agree on what counts
    as an anomaly.
    """
    rows = (
        db.query(
            Equipment.id,
            Equipment.name,
            Equipment.process_step,
            func.count(QualityInspection.id),
            func.sum(
                case((QualityInspection.result == InspectionResult.FAIL, 1), else_=0)
            ),
        )
        .join(QualityInspection, QualityInspection.equipment_id == Equipment.id)
        .group_by(Equipment.id, Equipment.name, Equipment.process_step)
        .all()
    )
    samples = [
        {
            "equipment_id": equipment_id,
            "equipment_name": equipment_name,
            "process_step": process_step,
            "total": int(total),
            "failures": int(failures or 0),
            "rate": (failures or 0) / total,
        }
        for equipment_id, equipment_name, process_step, total, failures in rows
        if total >= ANOMALY_MIN_INSPECTIONS
    ]

    anomalies = []
    for sample in samples:
        peer_rates = [
            peer["rate"]
            for peer in samples
            if peer["process_step"] == sample["process_step"]
            and peer["equipment_id"] != sample["equipment_id"]
        ]
        if len(peer_rates) < 2:
            continue
        peer_mean = mean(peer_rates)
        peer_stddev = pstdev(peer_rates)
        rate_delta = sample["rate"] - peer_mean
        z_score = rate_delta / peer_stddev if peer_stddev > 0 else None
        exceeds_statistical_guard = (
            z_score is not None and z_score >= ANOMALY_MIN_Z_SCORE
        ) or (peer_stddev == 0 and rate_delta > 0)
        if rate_delta < ANOMALY_MIN_RATE_DELTA or not exceeds_statistical_guard:
            continue
        severity = (
            "CRITICAL"
            if rate_delta >= 0.30
            else "WARNING"
            if rate_delta >= 0.15
            else "WATCH"
        )
        anomalies.append(
            EquipmentQualityAnomalyOut(
                equipment_id=sample["equipment_id"],
                equipment_name=sample["equipment_name"],
                process_step=sample["process_step"],
                total_inspections=sample["total"],
                fail_count=sample["failures"],
                defect_rate=round(sample["rate"], 4),
                peer_mean_rate=round(peer_mean, 4),
                peer_stddev=round(peer_stddev, 4),
                z_score=round(z_score, 2) if z_score is not None else None,
                rate_delta=round(rate_delta, 4),
                severity=severity,
            )
        )

    anomalies.sort(key=lambda item: item.rate_delta, reverse=True)
    return anomalies


@app.get("/quality/anomalies", response_model=QualityAnomalyReportOut)
def quality_anomalies(db: Session = Depends(get_db)):
    return QualityAnomalyReportOut(
        generated_at=datetime.utcnow(),
        method=ANOMALY_METHOD,
        minimum_inspections=ANOMALY_MIN_INSPECTIONS,
        minimum_rate_delta=ANOMALY_MIN_RATE_DELTA,
        minimum_z_score=ANOMALY_MIN_Z_SCORE,
        anomalies=_detect_quality_anomalies(db),
    )


@app.get("/quality/anomaly-log", response_model=list[AnomalyLogOut])
def quality_anomaly_log(db: Session = Depends(get_db)):
    """Persisted history of anomalies the system has detected over time —
    unlike /quality/anomalies (a live snapshot recomputed on every request
    and forgotten immediately after), these rows are written once each time
    the simulation engine's periodic check finds a *new* anomaly (throttled
    per equipment), so this is what answers "when did this first show up."
    """
    return (
        db.query(AnomalyLog)
        .order_by(AnomalyLog.detected_at.desc())
        .limit(100)
        .all()
    )


@app.get("/metrics", response_model=MetricsOut)
def metrics(db: Session = Depends(get_db)):
    wip_count = db.query(Lot).filter(
        Lot.status.in_(
            [LotStatus.WAITING, LotStatus.PROCESSING, LotStatus.HOLD, LotStatus.QUALITY_HOLD, LotStatus.REWORK]
        )
    ).count()

    today_start = kst_midnight_utc(datetime.utcnow())
    completed_today_q = db.query(Lot).filter(
        Lot.status == LotStatus.DONE, Lot.completed_at >= today_start
    )
    completed_today = completed_today_q.count()
    scrap_count = db.query(Lot).filter(Lot.is_scrap == 1).count()
    total_completed = db.query(Lot).filter(Lot.status == LotStatus.DONE).count()
    completed_outcomes = total_completed + scrap_count
    yield_rate = total_completed / completed_outcomes if completed_outcomes else 1.0

    avg_cycle = (
        db.query(func.avg(func.strftime("%s", Lot.completed_at) - func.strftime("%s", Lot.created_at)))
        .filter(Lot.status == LotStatus.DONE)
        .scalar()
    )

    now = datetime.utcnow()
    equipment_utilization = {
        eq.name: round(_effective_run_seconds(eq, now), 1) for eq in db.query(Equipment).all()
    }

    window_start = datetime.utcnow() - timedelta(hours=1)
    throughput = completed_today_q.filter(Lot.completed_at >= window_start).count()
    hold_wait = _equipment_hold_wait_metrics(db, now)

    return MetricsOut(
        wip_count=wip_count,
        completed_today=completed_today,
        scrap_count=scrap_count,
        yield_rate=round(yield_rate, 4),
        avg_cycle_time_seconds=round(avg_cycle, 1) if avg_cycle is not None else None,
        equipment_utilization=equipment_utilization,
        throughput_per_hour=throughput,
        **hold_wait,
    )


@app.post("/simulation/start")
async def start_simulation():
    """Start the autonomous simulation engine (app/simulation.py).

    Defined async so it runs on the event loop thread rather than in
    Starlette's sync-route threadpool — asyncio.create_task() inside
    SimulationEngine.start() requires a running loop on the calling thread.
    """
    simulation_engine.start()
    return simulation_engine.status()


@app.post("/simulation/stop")
async def stop_simulation():
    simulation_engine.stop()
    return simulation_engine.status()


@app.get("/simulation/status")
async def simulation_status():
    return simulation_engine.status()


@app.on_event("shutdown")
def stop_simulation_on_shutdown():
    simulation_engine.stop()


# Mounted last so it only serves paths no API route above already claimed
# (Starlette tries routes in registration order, first match wins) — the
# static dashboard reads live data from the JSON endpoints above via fetch().
app.mount(
    "/",
    StaticFiles(directory=Path(__file__).parent / "static", html=True),
    name="dashboard",
)

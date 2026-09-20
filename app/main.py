import random
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine, get_db
from app.models import (
    PROCESS_ROUTE,
    Equipment,
    EquipmentStatus,
    Lot,
    LotEvent,
    LotEventType,
    LotStatus,
    Product,
    WorkOrder,
    WorkOrderLot,
    WorkOrderStatus,
)
from app.schemas import (
    EquipmentOut,
    EquipmentStatusUpdate,
    LotCreate,
    LotEventOut,
    LotOut,
    MetricsOut,
    ProductCreate,
    ProductOut,
    WorkOrderCreate,
    WorkOrderLotCreate,
    WorkOrderOut,
)
from app.state_machine import ensure_lot_transition
from app.timeutils import kst_midnight_utc

Base.metadata.create_all(bind=engine)

app = FastAPI(title="MES Simulator", version="0.1.0")

SCRAP_PROBABILITY = 0.03
DEFAULT_PRODUCTS = (
    ("WAFER-A", "Wafer A"),
    ("WAFER-B", "Wafer B"),
    ("PANEL-X", "Panel X"),
    ("PANEL-Y", "Panel Y"),
)


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


def _compare_and_set_lot(
    db: Session,
    lot: Lot,
    *,
    expected_status: LotStatus,
    expected_step_index: int,
    values: dict,
) -> bool:
    """Apply one lot transition only if its observed state is still current.

    SQLite serializes concurrent writers. Once the first request commits, a
    competing request's conditional UPDATE matches zero rows and becomes a
    business conflict instead of advancing the same lot twice.
    """
    result = db.execute(
        update(Lot)
        .where(
            Lot.id == lot.id,
            Lot.status == expected_status,
            Lot.step_index == expected_step_index,
        )
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
    if lot.status == LotStatus.DONE:
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
    # Dispatch to the least-utilized available tool of this step (instead of
    # always the same one) so parallel equipment capacity is actually used.
    eq = min(candidates, key=lambda e: _effective_run_seconds(e, now), default=None)
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

    expected_step_index = lot.step_index
    next_step_index = expected_step_index + 1
    next_status = (
        LotStatus.DONE
        if next_step_index >= len(PROCESS_ROUTE)
        else LotStatus.PROCESSING
    )
    next_is_scrap = 1 if lot.is_scrap or random.random() < SCRAP_PROBABILITY else 0
    ensure_lot_transition(previous_status, next_status)
    transition_values = {
        "step_index": next_step_index,
        "status": next_status,
        "is_scrap": next_is_scrap,
        "updated_at": now,
    }
    if next_status == LotStatus.DONE:
        transition_values["completed_at"] = now

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
    if lot.status == LotStatus.DONE:
        _append_lot_event(
            db,
            lot,
            LotEventType.LOT_COMPLETED,
            from_status=LotStatus.DONE,
            to_status=LotStatus.DONE,
            process_step=step,
            equipment_id=eq.id,
            occurred_at=now,
        )
        association = (
            db.query(WorkOrderLot).filter(WorkOrderLot.lot_id == lot.id).one_or_none()
        )
        if association:
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

    db.commit()
    db.refresh(lot)
    return lot


@app.get("/metrics", response_model=MetricsOut)
def metrics(db: Session = Depends(get_db)):
    wip_count = db.query(Lot).filter(Lot.status.in_([LotStatus.WAITING, LotStatus.PROCESSING])).count()

    today_start = kst_midnight_utc(datetime.utcnow())
    completed_today_q = db.query(Lot).filter(
        Lot.status == LotStatus.DONE, Lot.completed_at >= today_start
    )
    completed_today = completed_today_q.count()
    scrap_count = db.query(Lot).filter(Lot.is_scrap == 1).count()
    total_lots = db.query(Lot).count()
    yield_rate = 1.0 - (scrap_count / total_lots) if total_lots else 1.0

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

    return MetricsOut(
        wip_count=wip_count,
        completed_today=completed_today,
        scrap_count=scrap_count,
        yield_rate=round(yield_rate, 4),
        avg_cycle_time_seconds=round(avg_cycle, 1) if avg_cycle is not None else None,
        equipment_utilization=equipment_utilization,
        throughput_per_hour=throughput,
    )

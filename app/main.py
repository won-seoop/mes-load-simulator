import random
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine, get_db
from app.models import PROCESS_ROUTE, Equipment, EquipmentStatus, Lot, LotStatus
from app.schemas import (
    EquipmentOut,
    EquipmentStatusUpdate,
    LotCreate,
    LotOut,
    MetricsOut,
)
from app.timeutils import kst_midnight_utc

Base.metadata.create_all(bind=engine)

app = FastAPI(title="MES Simulator", version="0.1.0")

SCRAP_PROBABILITY = 0.03


def _effective_run_seconds(eq: Equipment, now: datetime) -> float:
    """run_seconds plus any time accrued in the current RUN stretch that
    hasn't been flushed into run_seconds yet (that only happens on the next
    status change)."""
    if eq.status == EquipmentStatus.RUN:
        return eq.run_seconds + (now - eq.last_status_change).total_seconds()
    return eq.run_seconds


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
            db.commit()
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok"}


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


@app.post("/lots/{lot_id}/advance", response_model=LotOut)
def advance_lot(lot_id: int, db: Session = Depends(get_db)):
    lot = db.get(Lot, lot_id)
    if not lot:
        raise HTTPException(404, "lot not found")
    if lot.status == LotStatus.DONE:
        raise HTTPException(400, f"lot is {lot.status}, cannot advance")
    # A HOLD lot is retried at its current step once equipment frees up,
    # rather than being stuck forever (equipment down is a transient state).

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
        lot.status = LotStatus.HOLD
        db.commit()
        db.refresh(lot)
        return lot

    if eq.status == EquipmentStatus.RUN:
        eq.run_seconds += (now - eq.last_status_change).total_seconds()
    eq.status = EquipmentStatus.RUN
    eq.last_status_change = now

    if random.random() < SCRAP_PROBABILITY:
        lot.is_scrap = 1

    lot.step_index += 1
    lot.status = LotStatus.PROCESSING
    lot.updated_at = now

    if lot.step_index >= len(PROCESS_ROUTE):
        lot.status = LotStatus.DONE
        lot.completed_at = now

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

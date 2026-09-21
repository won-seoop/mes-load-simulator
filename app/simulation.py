"""In-process autonomous simulation engine.

Locust drives the API from *outside* to test throughput and concurrency.
This engine instead runs *inside* the server and advances lots through the
factory on realistic wall-clock timers, so the dashboard can show a factory
that keeps moving on its own — lots queuing and clearing steps, equipment
tripping DOWN and recovering, inspections passing or failing — without any
external caller.

It deliberately does not duplicate business logic. Every state change goes
through the exact same route functions the HTTP API and Locust use
(imported lazily from app.main to avoid a circular import, since app.main
imports this module's singleton `engine`), so the simulation clock and a
real API call can never disagree about what a valid transition is.
"""

import asyncio
import logging
import random
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

logger = logging.getLogger("app.simulation")

from app.database import SessionLocal
from app.models import (
    Equipment,
    EquipmentStatus,
    InspectionResult,
    Lot,
    LotStatus,
    PROCESS_ROUTE,
    Product,
    QualityDisposition,
    QualityInspection,
)

DEFECT_CODES = [
    "PARTICLE_CONTAMINATION",
    "ETCH_OVER_ETCH",
    "CVD_THICKNESS_DRIFT",
    "CMP_SCRATCH",
]

_ACTIVE_WIP_STATUSES = (
    LotStatus.WAITING,
    LotStatus.PROCESSING,
    LotStatus.HOLD,
    LotStatus.QUALITY_HOLD,
    LotStatus.REWORK,
)


@dataclass
class SimulationConfig:
    lot_arrival_seconds: float = 4.0
    step_dwell_min_seconds: float = 6.0
    step_dwell_max_seconds: float = 14.0
    equipment_down_probability_per_tick: float = 0.004
    equipment_down_min_seconds: float = 10.0
    equipment_down_max_seconds: float = 30.0
    defect_rate: float = 0.1
    max_wip: int = 40

    def clamped(self) -> "SimulationConfig":
        c = SimulationConfig(**asdict(self))
        if c.step_dwell_max_seconds < c.step_dwell_min_seconds:
            c.step_dwell_max_seconds = c.step_dwell_min_seconds
        if c.equipment_down_max_seconds < c.equipment_down_min_seconds:
            c.equipment_down_max_seconds = c.equipment_down_min_seconds
        return c


class SimulationEngine:
    """Ticks once a second, advancing due lots and toggling equipment faults."""

    TICK_SECONDS = 1.0

    def __init__(self) -> None:
        self._config = SimulationConfig()
        self._running = False
        self._task: asyncio.Task | None = None
        self._started_at: datetime | None = None
        self._ticks = 0
        self._next_lot_arrival_at: datetime | None = None
        self._next_action: dict[int, datetime] = {}  # lot_id -> next action due time
        self._next_equipment_recovery: dict[int, datetime] = {}
        self._events: deque[str] = deque(maxlen=40)
        self._mes_main = None  # lazily imported to avoid a circular import

    # -- public control ---------------------------------------------------
    def status(self) -> dict:
        return {
            "running": self._running,
            "started_at": self._started_at,
            "ticks": self._ticks,
            "config": asdict(self._config),
            "recent_events": list(self._events)[::-1],
        }

    def start(self, config: SimulationConfig | None = None) -> None:
        if config is not None:
            self._config = config.clamped()
        if self._running:
            return
        self._running = True
        self._started_at = datetime.utcnow()
        self._ticks = 0
        self._next_lot_arrival_at = datetime.utcnow()
        self._log("시뮬레이션 시작")
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._running:
            self._log("시뮬레이션 정지")
        self._running = False

    # -- scheduler loop -----------------------------------------------------
    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while self._running:
            try:
                await loop.run_in_executor(None, self._tick_once)
            except Exception as exc:  # pragma: no cover - defensive, keeps the loop alive
                self._log(f"⚠️ tick 오류: {exc}")
            self._ticks += 1
            await asyncio.sleep(self.TICK_SECONDS)

    # -- one synchronous tick (directly unit-testable, no asyncio needed) --
    def _tick_once(self, now: datetime | None = None) -> None:
        if self._mes_main is None:
            from app import main as mes_main

            self._mes_main = mes_main
        mes_main = self._mes_main
        now = now or datetime.utcnow()

        db = SessionLocal()
        try:
            self._maybe_recover_equipment(db, now, mes_main)
            self._maybe_trip_equipment(db, now, mes_main)
            self._maybe_spawn_lot(db, now, mes_main)
            self._advance_due_lots(db, now, mes_main)
        finally:
            db.close()

    def _log(self, message: str) -> None:
        stamp = datetime.utcnow().strftime("%H:%M:%S")
        self._events.append(f"[{stamp}] {message}")

    def _schedule(self, lot_id: int, now: datetime) -> None:
        dwell = random.uniform(
            self._config.step_dwell_min_seconds, self._config.step_dwell_max_seconds
        )
        self._next_action[lot_id] = now + timedelta(seconds=dwell)

    # -- equipment faults -----------------------------------------------
    def _maybe_trip_equipment(self, db: Session, now: datetime, mes_main) -> None:
        for eq in db.query(Equipment).filter(Equipment.status != EquipmentStatus.DOWN).all():
            if random.random() >= self._config.equipment_down_probability_per_tick:
                continue
            mes_main.set_equipment_status(
                eq.id, mes_main.EquipmentStatusUpdate(status=EquipmentStatus.DOWN), db=db
            )
            recovery = random.uniform(
                self._config.equipment_down_min_seconds,
                self._config.equipment_down_max_seconds,
            )
            self._next_equipment_recovery[eq.id] = now + timedelta(seconds=recovery)
            self._log(f"⚠️ 설비 {eq.name} DOWN (복구까지 약 {recovery:.0f}s)")

    def _maybe_recover_equipment(self, db: Session, now: datetime, mes_main) -> None:
        due_ids = [eid for eid, when in self._next_equipment_recovery.items() if when <= now]
        for eid in due_ids:
            self._next_equipment_recovery.pop(eid, None)
            eq = db.get(Equipment, eid)
            if eq is None or eq.status != EquipmentStatus.DOWN:
                continue
            mes_main.set_equipment_status(
                eid, mes_main.EquipmentStatusUpdate(status=EquipmentStatus.IDLE), db=db
            )
            self._log(f"설비 {eq.name} 복구")

    # -- lot arrivals -----------------------------------------------------
    def _maybe_spawn_lot(self, db: Session, now: datetime, mes_main) -> None:
        if self._next_lot_arrival_at is None or now < self._next_lot_arrival_at:
            return
        self._next_lot_arrival_at = now + timedelta(seconds=self._config.lot_arrival_seconds)

        wip = db.query(Lot).filter(Lot.status.in_(_ACTIVE_WIP_STATUSES)).count()
        if wip >= self._config.max_wip:
            return
        products = [p.code for p in db.query(Product).filter(Product.is_active == 1).all()]
        if not products:
            return

        product = random.choice(products)
        quantity = random.randint(10, 50)
        lot = mes_main.create_lot(mes_main.LotCreate(product=product, quantity=quantity), db=db)
        self._schedule(lot.id, now)
        self._log(f"신규 로트 #{lot.id} 투입 ({product} x{quantity})")

    # -- lot progression --------------------------------------------------
    def _advance_due_lots(self, db: Session, now: datetime, mes_main) -> None:
        due_lot_ids = [lot_id for lot_id, when in self._next_action.items() if when <= now]
        for lot_id in due_lot_ids:
            lot = db.get(Lot, lot_id)
            if lot is None:
                self._next_action.pop(lot_id, None)
                continue
            try:
                self._act_on_lot(db, lot, now, mes_main)
            except HTTPException:
                # Transient business conflict (e.g. concurrent change) — retry shortly.
                self._next_action[lot_id] = now + timedelta(seconds=2)
            except Exception as exc:
                # A single lot's bug (e.g. an unreachable state transition) must
                # never abort the whole tick — that would silently freeze every
                # other lot behind it and re-fire forever, since this lot stays
                # in _next_action with a now-past due time. Isolate per lot,
                # back off longer than the transient-conflict case, and log to
                # both the dashboard feed and the server log (the latter is what
                # external health checks actually grep for).
                self._next_action[lot_id] = now + timedelta(seconds=15)
                logger.warning("tick error advancing lot #%s: %r", lot_id, exc)
                self._log(f"⚠️ 로트 #{lot_id} 처리 오류: {exc}")

    def _act_on_lot(self, db: Session, lot: Lot, now: datetime, mes_main) -> None:
        if lot.status in (LotStatus.WAITING, LotStatus.PROCESSING, LotStatus.HOLD):
            before_step = lot.step_index
            updated = mes_main.advance_lot(lot.id, db=db)
            if updated.status == LotStatus.HOLD:
                self._next_action[lot.id] = now + timedelta(seconds=5)
            elif updated.status == LotStatus.QUALITY_HOLD:
                self._schedule(lot.id, now)
                self._log(f"로트 #{lot.id} 전체 공정 완료 → 검사 대기")
            else:
                step_name = (
                    PROCESS_ROUTE[before_step] if before_step < len(PROCESS_ROUTE) else "?"
                )
                self._schedule(lot.id, now)
                self._log(f"로트 #{lot.id} {step_name} 완료 → 다음 공정")
        elif lot.status == LotStatus.QUALITY_HOLD:
            self._do_inspection(db, lot, now, mes_main)
        elif lot.status == LotStatus.REWORK:
            mes_main.release_rework(lot.id, mes_main.ReworkReleaseCreate(step_index=2), db=db)
            self._schedule(lot.id, now)
            self._log(f"로트 #{lot.id} 재작업 투입 (CMP부터 재개)")
        else:
            self._next_action.pop(lot.id, None)

    def _do_inspection(self, db: Session, lot: Lot, now: datetime, mes_main) -> None:
        pending = (
            db.query(QualityInspection)
            .filter(
                QualityInspection.lot_id == lot.id,
                QualityInspection.result == InspectionResult.FAIL,
                QualityInspection.disposition == QualityDisposition.PENDING,
            )
            .first()
        )
        if pending:
            previous_reworks = (
                db.query(QualityInspection)
                .filter(
                    QualityInspection.lot_id == lot.id,
                    QualityInspection.disposition == QualityDisposition.REWORK,
                )
                .count()
            )
            disposition = (
                QualityDisposition.REWORK if previous_reworks < 1 else QualityDisposition.SCRAP
            )
            mes_main.disposition_lot(
                lot.id, mes_main.QualityDispositionCreate(disposition=disposition), db=db
            )
            if disposition == QualityDisposition.SCRAP:
                self._next_action.pop(lot.id, None)
                self._log(f"로트 #{lot.id} 재발 불량 → SCRAP")
            else:
                self._schedule(lot.id, now)
                self._log(f"로트 #{lot.id} 1차 불량 → REWORK 1회 허용")
            return

        passed = random.random() >= self._config.defect_rate
        if passed:
            mes_main.inspect_lot(
                lot.id, mes_main.QualityInspectionCreate(result=InspectionResult.PASS), db=db
            )
            self._next_action.pop(lot.id, None)
            self._log(f"로트 #{lot.id} 검사 합격 → DONE")
        else:
            defect_code = random.choice(DEFECT_CODES)
            mes_main.inspect_lot(
                lot.id,
                mes_main.QualityInspectionCreate(
                    result=InspectionResult.FAIL, defect_code=defect_code
                ),
                db=db,
            )
            self._schedule(lot.id, now)
            self._log(f"로트 #{lot.id} 검사 불합격 ({defect_code})")


engine = SimulationEngine()

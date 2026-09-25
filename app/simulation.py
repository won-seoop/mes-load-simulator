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

from app import control_tower, equipment_agent, llm_agent
from app.database import SessionLocal
from app.models import (
    AnomalyLog,
    Equipment,
    EquipmentStatus,
    InspectionResult,
    Lot,
    LotEvent,
    LotEventType,
    LotStatus,
    PROCESS_ROUTE,
    Product,
    QualityDisposition,
    QualityInspection,
)

# How often (in simulated wall-clock seconds) the engine re-runs anomaly
# detection, and how long a given equipment's last logged anomaly suppresses
# a fresh row — otherwise a standing anomaly would write a new AnomalyLog
# entry on every check while it persists, drowning out genuinely new ones.
ANOMALY_CHECK_INTERVAL_SECONDS = 30.0
ANOMALY_LOG_SUPPRESS_SECONDS = 300.0

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
        self._next_anomaly_check_at: datetime | None = None
        # equipment_id -> (injected defect rate, expires_at); scenario injection only
        self._defect_bias: dict[int, tuple[float, datetime]] = {}
        self._events: deque[str] = deque(maxlen=40)
        self._mes_main = None  # lazily imported to avoid a circular import

    # -- public control ---------------------------------------------------
    def status(self) -> dict:
        return {
            "running": self._running,
            "started_at": self._started_at,
            "ticks": self._ticks,
            "config": asdict(self._config),
            "defect_bias": {
                str(eq_id): {"defect_rate": rate, "expires_at": expires}
                for eq_id, (rate, expires) in self._defect_bias.items()
                if expires > datetime.utcnow()
            },
            "recent_events": list(self._events)[::-1],
        }

    def inject_defect_bias(
        self, equipment_id: int, defect_rate: float, duration_seconds: float, name: str
    ) -> datetime:
        """Scenario injection: inspections of lots that last ran on this INSPECT
        tool fail at `defect_rate` until it expires, instead of the global rate."""
        expires = datetime.utcnow() + timedelta(seconds=duration_seconds)
        self._defect_bias[equipment_id] = (defect_rate, expires)
        self._log(f"시나리오 주입: {name} 불량률 {defect_rate * 100:.0f}% ({duration_seconds:.0f}초)")
        return expires

    def clear_defect_bias(self) -> None:
        self._defect_bias.clear()

    def _defect_rate_for(self, db: Session, lot_id: int) -> float:
        if not self._defect_bias:
            return self._config.defect_rate
        last = (
            db.query(LotEvent)
            .filter(
                LotEvent.lot_id == lot_id,
                LotEvent.event_type == LotEventType.PROCESS_COMPLETED,
                LotEvent.process_step == "INSPECT",
            )
            .order_by(LotEvent.sequence_number.desc())
            .first()
        )
        bias = self._defect_bias.get(last.equipment_id) if last is not None else None
        if bias is not None and bias[1] > datetime.utcnow():
            return bias[0]
        return self._config.defect_rate

    def start(self, config: SimulationConfig | None = None) -> None:
        if config is not None:
            self._config = config.clamped()
        if self._running:
            return
        self._running = True
        self._started_at = datetime.utcnow()
        self._ticks = 0
        self._next_lot_arrival_at = datetime.utcnow()
        self._next_anomaly_check_at = datetime.utcnow()
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
            self._maybe_check_anomalies(db, now, mes_main)
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
                eq.id,
                mes_main.EquipmentStatusUpdate(status=EquipmentStatus.DOWN, reason="RANDOM_FAULT"),
                db=db,
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

    # -- quality anomaly detection -----------------------------------------
    def _maybe_check_anomalies(self, db: Session, now: datetime, mes_main) -> None:
        if (
            self._next_anomaly_check_at is not None
            and now < self._next_anomaly_check_at
        ):
            return
        self._next_anomaly_check_at = now + timedelta(seconds=ANOMALY_CHECK_INTERVAL_SECONDS)

        anomalies = mes_main._detect_quality_anomalies(db)
        self._propose_actions(db, anomalies, now)
        for anomaly in anomalies:
            suppress_since = now - timedelta(seconds=ANOMALY_LOG_SUPPRESS_SECONDS)
            recent = (
                db.query(AnomalyLog)
                .filter(
                    AnomalyLog.equipment_id == anomaly.equipment_id,
                    AnomalyLog.detected_at >= suppress_since,
                )
                .first()
            )
            if recent is not None:
                continue
            db.add(
                AnomalyLog(
                    detected_at=now,
                    equipment_id=anomaly.equipment_id,
                    equipment_name=anomaly.equipment_name,
                    process_step=anomaly.process_step,
                    severity=anomaly.severity,
                    defect_rate=anomaly.defect_rate,
                    peer_mean_rate=anomaly.peer_mean_rate,
                    z_score=anomaly.z_score,
                    total_inspections=anomaly.total_inspections,
                    method=mes_main.ANOMALY_METHOD,
                )
            )
            db.commit()
            self._log(
                f"⚠️ 품질 이상 감지: {anomaly.equipment_name} ({anomaly.process_step}) "
                f"{anomaly.severity} — 불량률 {anomaly.defect_rate * 100:.1f}% "
                f"vs 동료 {anomaly.peer_mean_rate * 100:.1f}%"
            )

    # WATCH is left to the anomaly log; only WARNING/CRITICAL ask a human.
    _APPROVAL_RISK_BY_SEVERITY = {"WARNING": "HIGH", "CRITICAL": "CRITICAL"}

    def _quality_proposal(self, anomaly) -> control_tower.Proposal | None:
        """Rule-based baseline 'quality agent': one proposal per detected anomaly."""
        risk = self._APPROVAL_RISK_BY_SEVERITY.get(anomaly.severity)
        if risk is None:
            return None
        z = f"{anomaly.z_score:.2f}" if anomaly.z_score is not None else "N/A"
        return control_tower.Proposal(
            source_agent="rule:quality-anomaly",
            equipment_id=anomaly.equipment_id,
            equipment_name=anomaly.equipment_name,
            title=f"{anomaly.equipment_name} 품질 이상 ({anomaly.process_step})",
            proposal=f"{anomaly.equipment_name} 신규 배정을 중지하고 점검한다",
            evidence=(
                f"불량률 {anomaly.defect_rate * 100:.1f}% vs 동일 공정 동료 평균 "
                f"{anomaly.peer_mean_rate * 100:.1f}% · z-score {z} · "
                f"검사 {anomaly.total_inspections}건"
            ),
            risk_level=risk,
            action_kind="STOP_NEW_DISPATCH",
            dedupe_key=f"quality-anomaly:{anomaly.equipment_id}",
        )

    def _propose_actions(self, db: Session, anomalies, now: datetime) -> None:
        """Agents only propose; the control tower merges, gates and queues. A
        standing condition folds into one approval row rather than one per cycle."""
        proposals = [p for a in anomalies if (p := self._quality_proposal(a)) is not None]
        proposals += equipment_agent.propose_from_downtime(db, now)
        proposals += equipment_agent.propose_from_concurrent_downs(db, now)
        try:
            proposals += llm_agent.propose(db, llm_agent.get_client("root-cause"), proposals, now)
        except Exception as exc:  # the rule-based baseline must survive any LLM-side failure
            logger.warning("llm agent skipped: %s", exc)

        def advisor(planned):
            try:
                return llm_agent.advise(db, llm_agent.get_client("tower-advisor"), planned, now)
            except Exception as exc:
                logger.warning("control tower advisor skipped: %s", exc)
                return planned

        control_tower.process(db, proposals, now, advisor=advisor)

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

        passed = random.random() >= self._defect_rate_for(db, lot.id)
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

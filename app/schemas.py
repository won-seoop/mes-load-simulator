from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models import (
    EquipmentStatus,
    InspectionResult,
    LotEventType,
    LotStatus,
    QualityDisposition,
    WorkOrderStatus,
)


class ProductOut(BaseModel):
    code: str
    name: str
    route_name: str
    route_version: int
    is_active: int

    class Config:
        from_attributes = True


class ProductCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    route_name: str = Field(default="DEFAULT_ROUTE", min_length=1, max_length=128)
    route_version: int = Field(default=1, ge=1)
    is_active: int = Field(default=1, ge=0, le=1)


class EquipmentOut(BaseModel):
    id: int
    name: str
    process_step: str
    status: EquipmentStatus
    run_seconds: float
    dispatch_count: int
    # OEE Availability for this equipment alone (see app.main._equipment_oee).
    # Performance is None until the tool has completed at least one dispatch
    # with nonzero elapsed run time — there is nothing to measure yet.
    # Quality is deliberately not attributed per-equipment: only inspection
    # stations produce pass/fail data, so a per-tool quality number would be
    # fabricated for the other three steps. Full three-factor OEE is only
    # computed at the factory level in /metrics.
    availability: Optional[float] = None
    performance: Optional[float] = None
    # MTBF/MTTR derived from EquipmentDowntimeEvent (see app.main._equipment_reliability).
    # None until this tool has logged at least one DOWN event, not a fabricated 0.
    mtbf_seconds: Optional[float] = None
    mttr_seconds: Optional[float] = None

    class Config:
        from_attributes = True


class EquipmentStatusUpdate(BaseModel):
    status: EquipmentStatus
    # Who/what caused this transition (e.g. "RANDOM_FAULT" from the
    # autonomous simulation, "FAULT_INJECTION" from Locust). Defaults to
    # "MANUAL" for operator/dashboard-initiated calls that omit it.
    reason: Optional[str] = None


class EquipmentDowntimeEventOut(BaseModel):
    id: int
    equipment_id: int
    reason: str
    started_at: datetime
    ended_at: Optional[datetime]
    duration_seconds: Optional[float]

    class Config:
        from_attributes = True


class LotCreate(BaseModel):
    product: str
    quantity: int = 25


class LotOut(BaseModel):
    id: int
    product: str
    quantity: int
    step_index: int
    status: LotStatus
    is_scrap: int
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


class LotEventOut(BaseModel):
    event_id: str
    lot_id: int
    sequence_number: int
    event_type: LotEventType
    process_step: Optional[str]
    equipment_id: Optional[int]
    from_status: Optional[LotStatus]
    to_status: LotStatus
    occurred_at: datetime

    class Config:
        from_attributes = True


class WorkOrderCreate(BaseModel):
    order_no: str = Field(min_length=1, max_length=64)
    product_code: str = Field(min_length=1, max_length=64)
    planned_quantity: int = Field(gt=0)
    priority: int = Field(default=5, ge=1, le=10)
    due_at: Optional[datetime] = None


class WorkOrderOut(BaseModel):
    id: int
    order_no: str
    product_code: str
    planned_quantity: int
    released_quantity: int
    completed_quantity: int
    priority: int
    due_at: Optional[datetime]
    status: WorkOrderStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkOrderLotCreate(BaseModel):
    quantity: int = Field(gt=0)


class QualityInspectionCreate(BaseModel):
    result: InspectionResult
    defect_code: Optional[str] = Field(default=None, max_length=64)


class QualityInspectionOut(BaseModel):
    inspection_id: str
    lot_id: int
    attempt_number: int
    process_step: str
    equipment_id: Optional[int]
    result: InspectionResult
    defect_code: Optional[str]
    disposition: QualityDisposition
    inspected_at: datetime

    class Config:
        from_attributes = True


class QualityDispositionCreate(BaseModel):
    disposition: QualityDisposition


class ReworkReleaseCreate(BaseModel):
    step_index: int = Field(ge=0, lt=4)


class QualityMetricsOut(BaseModel):
    total_inspections: int
    pass_count: int
    fail_count: int
    defect_rate: float
    first_pass_yield: float
    scrap_count: int
    rework_count: int
    rework_rate: float
    defects_by_process: dict
    defects_by_equipment: dict


class EquipmentQualityAnomalyOut(BaseModel):
    equipment_id: int
    equipment_name: str
    process_step: str
    total_inspections: int
    fail_count: int
    defect_rate: float
    peer_mean_rate: float
    peer_stddev: float
    z_score: Optional[float]
    rate_delta: float
    severity: str


class QualityAnomalyReportOut(BaseModel):
    generated_at: datetime
    method: str
    minimum_inspections: int
    minimum_rate_delta: float
    minimum_z_score: float
    anomalies: list[EquipmentQualityAnomalyOut]


class AnomalyLogOut(BaseModel):
    id: int
    detected_at: datetime
    equipment_id: int
    equipment_name: str
    process_step: str
    severity: str
    defect_rate: float
    peer_mean_rate: float
    z_score: Optional[float]
    total_inspections: int
    method: str
    note: Optional[str]

    class Config:
        from_attributes = True


class MetricsOut(BaseModel):
    wip_count: int
    completed_today: int
    scrap_count: int
    yield_rate: float
    avg_cycle_time_seconds: Optional[float]
    equipment_utilization: dict
    throughput_per_hour: float
    lots_on_hold_count: int
    longest_current_hold_seconds: Optional[float]
    avg_resolved_hold_seconds: Optional[float]
    # OEE = Availability x Performance x Quality, averaged across equipment
    # (see app.main._equipment_oee for the per-equipment formulas and the
    # denominators/window each factor uses). None while there isn't enough
    # data yet (e.g. nothing has been dispatched) rather than a fabricated 0.
    oee_availability: Optional[float]
    oee_performance: Optional[float]
    oee_quality: float
    oee: Optional[float]

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

    class Config:
        from_attributes = True


class EquipmentStatusUpdate(BaseModel):
    status: EquipmentStatus


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


class MetricsOut(BaseModel):
    wip_count: int
    completed_today: int
    scrap_count: int
    yield_rate: float
    avg_cycle_time_seconds: Optional[float]
    equipment_utilization: dict
    throughput_per_hour: float

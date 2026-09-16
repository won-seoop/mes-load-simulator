from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models import EquipmentStatus, LotStatus


class EquipmentOut(BaseModel):
    id: int
    name: str
    process_step: str
    status: EquipmentStatus
    run_seconds: float

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


class MetricsOut(BaseModel):
    wip_count: int
    completed_today: int
    scrap_count: int
    yield_rate: float
    avg_cycle_time_seconds: Optional[float]
    equipment_utilization: dict
    throughput_per_hour: float

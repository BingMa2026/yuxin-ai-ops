"""Operator-only duration adjustment contracts."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class DurationAdjustSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: Literal["grant", "deduct"]
    days: int = Field(strict=True, ge=1, le=3650)
    catalog_plan_id: int | None = Field(default=None, gt=0)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=500)]
    idempotency_key: Annotated[str, StringConstraints(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9:_-]+$")]
    expected_expires_at: datetime | None = None


class DurationAdjustmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    direction: Literal["grant", "deduct"]
    days: int
    seconds_delta: int
    before_expires_at: datetime | None
    after_expires_at: datetime
    reason: str
    operator_name: str
    created_time: datetime


class DurationPlanOption(BaseModel):
    id: int
    name: str


class DurationStateOut(BaseModel):
    status: str
    expires_at: datetime | None
    remaining_seconds: int
    server_time: datetime
    catalog_plan_id: int | None
    plans: list[DurationPlanOption]
    records: list[DurationAdjustmentOut]

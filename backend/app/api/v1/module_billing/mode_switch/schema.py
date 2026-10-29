from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

BillingMode = Literal["credits", "duration"]


class ModeSwitchPreviewIn(BaseModel):
    target_mode: BillingMode
    catalog_plan_id: int = Field(gt=0)
    expected_mode_version: int = Field(ge=1)


class ModeSwitchConfirmation(BaseModel):
    expected_mode_version: int = Field(ge=1)
    accept_reset: Literal[True]


class ResetItem(BaseModel):
    kind: Literal["credit_grant", "subscription_cycle", "subscription"]
    id: int
    source: str
    available: int = 0
    pending: int = 0
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class ResetSummary(BaseModel):
    available_credits_to_expire: int = 0
    pending_credits_to_expire: int = 0
    duration_seconds_to_expire: int = 0
    items: list[ResetItem] = Field(default_factory=list)


class ModeSwitchPreviewOut(BaseModel):
    source_mode: BillingMode | None
    target_mode: BillingMode
    policy_version: int
    mode_version: int
    can_switch: bool
    blocked_reason: str | None = None
    requires_reset_confirmation: bool
    reset_summary: ResetSummary

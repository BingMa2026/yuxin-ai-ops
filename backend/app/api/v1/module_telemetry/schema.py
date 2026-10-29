import json
import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SAFE_METADATA_KEYS = {
    "artifact_type",
    "client_platform",
    "count",
    "document_type",
    "duration_ms",
    "error_category",
    "feature",
    "file_extension",
    "file_size_bucket",
    "model_business_code",
    "model_code",
    "operation",
    "page_count",
    "progress_bucket",
    "reason_code",
    "result",
    "retry_count",
    "route",
    "source_type",
    "stage",
    "status",
    "success",
    "workflow",
}


def _validate_scalar(value: Any) -> None:
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("遥测元数据不能包含非有限数值")
        return
    if isinstance(value, str):
        if len(value) > 256:
            raise ValueError("遥测元数据文本不能超过 256 个字符")
        return
    raise ValueError("遥测元数据只允许标量或标量数组")


class TelemetryEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    event_type: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_.-]*$")
    occurred_at: datetime
    source: Literal["web", "desktop", "openworker"]
    client_version: str | None = Field(default=None, max_length=64)
    session_ref: str | None = Field(default=None, max_length=128)
    project_ref: str | None = Field(default=None, max_length=128)
    task_ref: str | None = Field(default=None, max_length=128)
    critical: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 24:
            raise ValueError("单个遥测事件最多包含 24 个元数据字段")
        unknown = sorted(set(value) - _SAFE_METADATA_KEYS)
        if unknown:
            raise ValueError(f"遥测元数据包含未允许字段: {', '.join(unknown)}")
        for item in value.values():
            if isinstance(item, list):
                if len(item) > 50:
                    raise ValueError("遥测元数据数组最多包含 50 项")
                for nested in item:
                    _validate_scalar(nested)
            else:
                _validate_scalar(item)
        if len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()) > 4096:
            raise ValueError("单个遥测事件元数据不能超过 4KB")
        return value


class TelemetryBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[TelemetryEventIn] = Field(min_length=1, max_length=100)


class TelemetryBatchOut(BaseModel):
    accepted: int = Field(ge=0)
    duplicated: int = Field(ge=0)


class TelemetryTypeCount(BaseModel):
    event_type: str
    count: int


class TelemetryDiagnosticsOut(BaseModel):
    app_id: int
    total_events: int = 0
    latest_event_at: datetime | None = None
    latest_received_at: datetime | None = None
    latest_client_version: str | None = None
    delivery_delay_seconds: int | None = None
    event_types: list[TelemetryTypeCount] = Field(default_factory=list)


class TelemetryEventDiagnosticOut(BaseModel):
    event_id: str
    event_type: str
    occurred_at: datetime
    received_at: datetime
    user_id: int
    client_version: str | None = None
    source: str
    critical: bool

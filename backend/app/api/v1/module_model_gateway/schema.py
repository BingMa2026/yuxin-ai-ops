import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.v1.module_billing.reservation_policy import MAX_MODEL_REQUEST_SECONDS
from app.api.v1.module_speech.catalog_schema import SpeechPricing, SpeechProtocol
from app.core.base_schema import BaseSchema

from .generation_policy import GenerationSettings, validate_answer_budget


class ProviderTemplateOut(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    max_timeout_seconds: int = MAX_MODEL_REQUEST_SECONDS
    code: str
    name: str
    protocol: str
    field_schema: list[dict]
    default_endpoint: str | None = None
    logo_key: str | None = None
    description: str | None = None
    recommended_model: str | None = None
    adapter_ready: bool = False
    custom: bool
    order: int
    status: str


class CustomProviderTemplateCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=2, max_length=64)
    default_endpoint: str = Field(min_length=8, max_length=500)
    field_schema: list[dict] = Field(default_factory=lambda: [{"key": "api_key", "label": "API Key", "type": "password", "required": True, "secret": True}])


class ProviderAccountCreate(BaseModel):
    template_id: int
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=2, max_length=64)
    endpoint: str = Field(min_length=8, max_length=500)
    settings: dict[str, Any]
    timeout_seconds: int = Field(default=120, ge=1, le=MAX_MODEL_REQUEST_SECONDS)
    retry_count: int = Field(default=1, ge=0, le=5)
    status: Literal["active", "inactive"] = "inactive"


class ProviderAccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=64)
    endpoint: str | None = Field(default=None, min_length=8, max_length=500)
    settings: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int | None = Field(default=None, ge=1, le=MAX_MODEL_REQUEST_SECONDS)
    retry_count: int | None = Field(default=None, ge=0, le=5)


class ProviderConnectionTest(BaseModel):
    template_id: int = Field(gt=0)
    endpoint: str = Field(default="", max_length=500)
    settings: dict[str, Any]
    timeout_seconds: int = Field(default=30, ge=1, le=60)


class ProviderAccountOut(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    template_id: int
    code: str
    name: str
    endpoint: str
    masked_summary: dict
    timeout_seconds: int
    retry_count: int
    status: str
    connection_status: str
    last_verified_at: datetime | None = None
    last_error: str | None = None


class ModelCatalogCreate(BaseModel):
    provider_account_id: int
    provider_model_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    context_length: int | None = Field(default=None, ge=1)
    speech_protocol: SpeechProtocol | None = None
    speech_pricing: SpeechPricing | None = None
    supports_stream: bool = True
    supports_tools: bool = False
    supports_vision: bool = False
    supports_pdf: bool = False
    input_cost_per_million: float = Field(default=0, ge=0)
    output_cost_per_million: float = Field(default=0, ge=0)
    input_credits_per_1k: int = Field(default=0, ge=0)
    output_credits_per_1k: int = Field(default=0, ge=0)
    minimum_credits: int = Field(default=1, ge=1)
    status: Literal["active", "inactive"] = "inactive"


class ModelCatalogUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    context_length: int | None = Field(default=None, ge=1)
    speech_protocol: SpeechProtocol | None = None
    speech_pricing: SpeechPricing | None = None
    supports_stream: bool | None = None
    supports_tools: bool | None = None
    supports_vision: bool | None = None
    supports_pdf: bool | None = None
    input_cost_per_million: float | None = Field(default=None, ge=0)
    output_cost_per_million: float | None = Field(default=None, ge=0)
    input_credits_per_1k: int | None = Field(default=None, ge=0)
    output_credits_per_1k: int | None = Field(default=None, ge=0)
    minimum_credits: int | None = Field(default=None, ge=1)


class ModelCatalogOut(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    provider_account_id: int
    provider_model_id: str
    display_name: str
    context_length: int | None = None
    speech_protocol: SpeechProtocol | None = None
    speech_pricing: SpeechPricing | None = None
    supports_stream: bool
    supports_tools: bool
    supports_vision: bool
    supports_pdf: bool
    input_cost_per_million: float
    output_cost_per_million: float
    cache_read_cost_per_million: float = 0
    cache_write_cost_per_million: float = 0
    reasoning_cost_per_million: float = 0
    price_version_id: int | None = None
    price_source: str | None = None
    input_credits_per_1k: int
    output_credits_per_1k: int
    minimum_credits: int
    status: str


class PurchasePriceCreate(BaseModel):
    catalog_model_id: int = Field(gt=0)
    region: str | None = Field(default=None, max_length=64)
    service_tier: str = Field(default="standard", max_length=32)
    billing_mode: str = Field(default="realtime", max_length=32)
    context_min: int = Field(default=0, ge=0)
    context_max: int | None = Field(default=None, ge=1)
    currency: str = Field(default="CNY", min_length=3, max_length=8)
    exchange_rate_to_cny: float = Field(default=1, gt=0)
    input_cost_per_million: float = Field(ge=0)
    cache_read_cost_per_million: float = Field(default=0, ge=0)
    cache_write_cost_per_million: float = Field(default=0, ge=0)
    output_cost_per_million: float = Field(ge=0)
    reasoning_cost_per_million: float = Field(default=0, ge=0)
    source: Literal["manual", "provider", "official_price"] = "manual"
    effective_from: datetime

    @model_validator(mode="after")
    def validate_context_range(self):
        if self.context_max is not None and self.context_max < self.context_min:
            raise ValueError("上下文区间上限不能小于下限")
        return self


class PurchasePriceOut(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    provider_account_id: int
    catalog_model_id: int
    provider_model_id: str
    region: str | None = None
    service_tier: str
    billing_mode: str
    context_min: int
    context_max: int | None = None
    currency: str
    exchange_rate_to_cny: float
    input_cost_per_million: float
    cache_read_cost_per_million: float
    cache_write_cost_per_million: float
    output_cost_per_million: float
    reasoning_cost_per_million: float
    source: str
    effective_from: datetime
    effective_until: datetime | None = None
    status: str


class FinanceProfileUpsert(BaseModel):
    adapter_type: Literal[
        "alibaba_bss",
        "deepseek",
        "openai_admin",
        "anthropic_admin",
        "aws_cost_explorer",
        "google_cloud_billing",
        "manual",
    ]
    settings: dict[str, Any] = Field(default_factory=dict)
    balance_warning_yuan: float | None = Field(default=None, ge=0)
    status: Literal["active", "inactive"] = "active"


class FinanceProfileOut(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    provider_account_id: int
    adapter_type: str
    masked_summary: dict
    capabilities: dict
    balance_warning_yuan: float | None = None
    status: str
    connection_status: str
    last_synced_at: datetime | None = None
    last_bill_at: datetime | None = None
    last_error: str | None = None


class BalanceSnapshotOut(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    provider_account_id: int
    currency: str
    available_amount: float
    cash_amount: float | None = None
    granted_amount: float | None = None
    amount_yuan: float | None = None
    fetched_at: datetime
    source: str


class ProviderBillOut(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    provider_account_id: int
    external_id: str
    provider_model_id: str | None = None
    billing_type: str
    attribution_key: str | None = None
    currency: str
    amount_original: float
    amount_yuan: float
    usage_detail: dict
    service_start_at: datetime
    service_end_at: datetime
    source: str
    reconciliation_method: str


class ResourcePackageOut(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    external_id: str
    name: str
    package_type: str | None = None
    total_amount: float
    remaining_amount: float
    unit: str
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    status: str
    fetched_at: datetime
    source: str


class FinanceSummaryOut(BaseModel):
    profile: FinanceProfileOut | None = None
    latest_balance: BalanceSnapshotOut | None = None
    month_bill_yuan: float = 0
    last_bill_at: datetime | None = None
    request_cost_yuan: float = 0
    speech_cost_yuan: float = 0
    unknown_cost_calls: int = 0
    month_request_count: int = 0
    difference_yuan: float = 0
    reconciliation_coverage_rate: float = 0
    resource_packages: list[ResourcePackageOut] = Field(default_factory=list)


class FinanceSyncRequest(BaseModel):
    range_start: datetime | None = None
    range_end: datetime | None = None


class ManualBillImportItem(BaseModel):
    external_id: str = Field(min_length=1, max_length=192)
    provider_model_id: str | None = Field(default=None, max_length=128)
    billing_type: str = Field(default="inference", max_length=48)
    attribution_key: str | None = Field(default=None, max_length=128)
    currency: str = Field(default="CNY", min_length=3, max_length=8)
    amount_original: float
    exchange_rate: float = Field(default=1, gt=0)
    usage_detail: dict[str, Any] = Field(default_factory=dict)
    service_start_at: datetime
    service_end_at: datetime


class ManualBillImport(BaseModel):
    items: list[ManualBillImportItem] = Field(min_length=1, max_length=5000)


class DiscoveredModelOut(BaseModel):
    provider_model_id: str
    display_name: str
    owned_by: str | None = None
    already_synced: bool = False
    price_matched: bool = False
    gateway_compatible: bool = True


class AppModelBindingCreate(BaseModel):
    catalog_model_id: int
    public_model_code: str = Field(pattern=r"^[a-zA-Z0-9_.-]{2,64}$")
    client_display_name: str = Field(min_length=1, max_length=128)
    visible: bool = True
    user_selectable: bool = True
    is_default: bool = False
    input_credits_per_1k: int | None = Field(default=None, ge=0)
    output_credits_per_1k: int | None = Field(default=None, ge=0)
    fallback_binding_id: int | None = None
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    order: int = 999
    status: Literal["active", "inactive"] = "inactive"


class AppModelBindingUpdate(BaseModel):
    client_display_name: str | None = Field(default=None, min_length=1, max_length=128)
    visible: bool | None = None
    user_selectable: bool | None = None
    is_default: bool | None = None
    input_credits_per_1k: int | None = Field(default=None, ge=0)
    output_credits_per_1k: int | None = Field(default=None, ge=0)
    fallback_binding_id: int | None = None
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    order: int | None = None


class AppModelBindingOut(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    app_id: int
    catalog_model_id: int
    public_model_code: str
    client_display_name: str
    visible: bool
    user_selectable: bool
    is_default: bool
    input_credits_per_1k: int | None = None
    output_credits_per_1k: int | None = None
    fallback_binding_id: int | None = None
    order: int
    status: str


class AppModelRouteCreate(BaseModel):
    business_code: Literal["chat_default", "document_intelligence", "semantic_review"]
    name: str = Field(min_length=2, max_length=64)
    primary_binding_id: int
    fallback_binding_ids: list[int] = Field(default_factory=list)
    timeout_seconds: int = Field(default=120, ge=1, le=MAX_MODEL_REQUEST_SECONDS)
    max_output_tokens: int | None = Field(default=None, ge=1)
    generation_settings: GenerationSettings | None = None
    allow_tools: bool = True
    allow_user_model: bool = True
    status: Literal["active", "inactive"] = "inactive"

    @model_validator(mode="after")
    def validate_bindings(self):
        validate_answer_budget(self.generation_settings, self.max_output_tokens)
        if self.primary_binding_id in self.fallback_binding_ids or len(set(self.fallback_binding_ids)) != len(self.fallback_binding_ids):
            raise ValueError("主模型不能出现在备用模型中，备用模型不能重复")
        return self


class AppModelRouteOut(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    app_id: int
    business_code: str
    name: str
    primary_binding_id: int
    fallback_binding_ids: list[int]
    timeout_seconds: int
    max_output_tokens: int | None = None
    generation_settings: GenerationSettings | None = None
    allow_tools: bool
    allow_user_model: bool
    status: str


class ClientModelOption(BaseModel):
    code: str
    name: str
    context_window: int | None = Field(default=None, ge=1)
    is_default: bool
    user_selectable: bool
    supports_tools: bool
    supports_vision: bool
    supports_pdf: bool
    supports_thinking: bool = False


class ClientModelRoute(BaseModel):
    business_code: Literal["chat_default", "document_intelligence", "semantic_review"]
    name: str
    primary_model_code: str
    primary_model_name: str
    fallback_model_codes: list[str] = Field(default_factory=list)
    timeout_seconds: int
    max_output_tokens: int | None = None
    generation_settings: GenerationSettings | None = None
    generation_policy_status: Literal["LEGACY_UNMANAGED", "GOVERNED"] = "LEGACY_UNMANAGED"
    allow_tools: bool
    allow_user_model: bool


class ClientModelRequestReceipt(BaseModel):
    """Finite accounting evidence; never an output or business checkpoint receipt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["model-request-receipt/v1"] = "model-request-receipt/v1"
    request_id: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{8,128}$")
    execution_status: Literal["UNKNOWN", "SUCCEEDED", "FAILED", "CANCELLED"]
    settlement_status: Literal["UNKNOWN", "RESERVED", "SETTLED", "RELEASED"]
    reserved_credits: int | None = Field(default=None, ge=0)
    charged_credits: int | None = Field(default=None, ge=0)
    reported_charged_credits: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    usage_complete: bool | None = None
    usage_basis: Literal["UNKNOWN", "ESTIMATED", "OBSERVED_PARTIAL", "REPORTED"]
    error_code: (
        Literal[
            "UPSTREAM_TOTAL_TIMEOUT",
            "UPSTREAM_IDLE_TIMEOUT",
            "UPSTREAM_CONNECT_TIMEOUT",
            "UPSTREAM_RATE_LIMITED",
            "UPSTREAM_AUTH_REJECTED",
            "UPSTREAM_REQUEST_REJECTED",
            "UPSTREAM_SERVER_ERROR",
            "UPSTREAM_PROTOCOL_ERROR",
            "UPSTREAM_UNAVAILABLE",
            "UPSTREAM_INTERRUPTED",
            "CLIENT_CANCELLED",
            "UNKNOWN_ERROR",
        ]
        | None
    ) = None
    reservation_created_at: datetime | None = None
    completed_at: datetime | None = None
    settled_at: datetime | None = None
    server_content_available: Literal[False] = False
    receipt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ClientModelConfig(BaseModel):
    platform_model_enabled: bool = True
    allow_custom_model: bool = False
    app_id: int | None = None
    user_id: int | None = None
    version: int
    service_status: Literal["available", "unavailable"]
    updated_at: datetime | None = None
    models: list[ClientModelOption]
    routes: list[ClientModelRoute]


class RuntimeTokenOut(BaseModel):
    token: str
    expires_in: int
    token_type: str = "Bearer"


class RuntimeMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict] | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict] | None = None


class RuntimeCompletionRequest(BaseModel):
    cloud_task_id: int | None = Field(default=None, gt=0)
    request_id: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{8,128}$")
    business_code: Literal["chat_default", "document_intelligence", "semantic_review"] = "chat_default"
    model: str | None = Field(default=None, max_length=64)
    thinking: bool | None = Field(default=None, strict=True)
    messages: list[RuntimeMessage] = Field(min_length=1, max_length=200)
    tools: list[dict] | None = None
    tool_choice: Literal["auto", "none", "required"] | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = Field(default=None, strict=True)
    response_format: dict[str, Any] | None = None
    thinking_budget_tokens: int | None = Field(default=None, ge=1, le=8192)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=1, le=131072)

    @model_validator(mode="after")
    def validate_model_options(self):
        if self.thinking_budget_tokens is not None and self.thinking is not True:
            raise ValueError("思考预算仅可用于已开启的思考模式")
        if self.response_format is not None:
            kind = self.response_format.get("type")
            if isinstance(kind, str) and kind in {"text", "json_object"}:
                valid = set(self.response_format) == {"type"}
            elif kind == "json_schema":
                schema = self.response_format.get("json_schema")
                valid = (
                    set(self.response_format) == {"type", "json_schema"}
                    and isinstance(schema, dict)
                    and isinstance(schema.get("name"), str)
                    and 0 < len(schema["name"]) <= 64
                    and isinstance(schema.get("schema"), dict)
                    and len(json.dumps(schema, ensure_ascii=False)) <= 32768
                )
            else:
                valid = False
            if not valid:
                raise ValueError("模型输出格式参数无效")
        if isinstance(self.tool_choice, dict):
            function = self.tool_choice.get("function")
            valid = (
                set(self.tool_choice) == {"type", "function"}
                and self.tool_choice.get("type") == "function"
                and isinstance(function, dict)
                and set(function) == {"name"}
                and isinstance(function.get("name"), str)
            )
            offered = {tool.get("function", {}).get("name") for tool in (self.tools or []) if isinstance(tool, dict) and isinstance(tool.get("function"), dict)}
            if not valid or function["name"] not in offered:
                raise ValueError("指定的模型工具不在本次可用工具中")
        elif self.tool_choice in {"required", "auto"} and not self.tools:
            raise ValueError("当前请求没有可用的模型工具")
        return self


class RuntimeCompletionOut(BaseModel):
    request_id: str
    model: str
    content: str = ""
    reasoning_content: str = ""
    tool_calls: list[dict] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    charged_credits: int | None = 0
    settlement_status: Literal["SETTLED", "PENDING"] = "SETTLED"
    finish_reason: str | None = Field(default=None, max_length=64)
    effective_max_output_tokens: int | None = Field(default=None, ge=1, le=131072)
    generation_settings: GenerationSettings | None = None
    generation_policy_status: Literal["LEGACY_UNMANAGED", "GOVERNED"] = "LEGACY_UNMANAGED"


class ResourceStatusUpdate(BaseModel):
    status: Literal["active", "inactive"]

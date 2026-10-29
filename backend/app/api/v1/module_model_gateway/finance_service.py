from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_schema import AuthSchema
from app.core.exceptions import CustomException

from .cost_usage import RequestCostUsage, bill_cost_in_period
from .model import (
    ModelCatalogModel,
    ModelCostReconciliationModel,
    ModelProviderAccountModel,
    ModelProviderBalanceSnapshotModel,
    ModelProviderBillItemModel,
    ModelProviderFinanceProfileModel,
    ModelProviderResourcePackageSnapshotModel,
    ModelProviderSyncTaskModel,
    ModelPurchasePriceVersionModel,
    ModelUsageModel,
)
from .schema import (
    BalanceSnapshotOut,
    FinanceProfileOut,
    FinanceProfileUpsert,
    FinanceSummaryOut,
    FinanceSyncRequest,
    ManualBillImport,
    ProviderBillOut,
    PurchasePriceCreate,
    PurchasePriceOut,
    ResourcePackageOut,
)
from .secret_codec import decrypt_settings, encrypt_settings

FINANCE_CAPABILITIES: dict[str, dict[str, bool]] = {
    "alibaba_bss": {"balance": True, "usage": True, "bill": True, "resource_pack": True, "price_sync": False},
    "deepseek": {"balance": True, "usage": False, "bill": False, "resource_pack": False, "price_sync": False},
    "openai_admin": {"balance": False, "usage": True, "bill": True, "resource_pack": False, "price_sync": False},
    "anthropic_admin": {"balance": False, "usage": True, "bill": True, "resource_pack": False, "price_sync": False},
    "aws_cost_explorer": {"balance": False, "usage": True, "bill": True, "resource_pack": False, "price_sync": False},
    "google_cloud_billing": {"balance": False, "usage": False, "bill": False, "resource_pack": False, "price_sync": False},
    "manual": {"balance": False, "usage": False, "bill": True, "resource_pack": False, "price_sync": False},
}


def _masked(settings: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in settings.items():
        if any(marker in key.lower() for marker in ("key", "secret", "token", "password")):
            text = str(value or "")
            result[key] = f"••••{text[-4:]}" if len(text) >= 4 else ("••••" if text else "")
        else:
            result[key] = value
    return result


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception as exc:
        raise CustomException(msg="供应商返回了无法识别的金额") from exc


def _optional_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _cny(amount: Decimal, currency: str, settings: dict[str, Any]) -> tuple[Decimal, Decimal]:
    if currency.upper() == "CNY":
        return amount, Decimal("1")
    rate = _decimal(settings.get("exchange_rate_to_cny"))
    if rate <= 0:
        raise CustomException(msg=f"{currency} 财务数据需要配置兑人民币汇率")
    return amount * rate, rate


def _alibaba_encode(value: Any) -> str:
    return quote(str(value), safe="~")


def _alibaba_rpc_params(action: str, settings: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, str]:
    params: dict[str, Any] = {
        "AccessKeyId": settings.get("access_key_id"),
        "Action": action,
        "Format": "JSON",
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": uuid.uuid4().hex,
        "SignatureVersion": "1.0",
        "Timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Version": "2017-12-14",
        **(extra or {}),
    }
    if not params["AccessKeyId"] or not settings.get("access_key_secret"):
        raise CustomException(msg="请配置阿里云 RAM AccessKey ID 和 Secret")
    canonical = "&".join(f"{_alibaba_encode(key)}={_alibaba_encode(value)}" for key, value in sorted(params.items()))
    string_to_sign = f"GET&%2F&{_alibaba_encode(canonical)}"
    digest = hmac.new(f"{settings['access_key_secret']}&".encode(), string_to_sign.encode(), hashlib.sha1).digest()
    params["Signature"] = base64.b64encode(digest).decode()
    return {key: str(value) for key, value in params.items()}


class ProviderFinanceAdapter:
    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings

    async def fetch_balance(self) -> list[dict[str, Any]]:
        return []

    async def fetch_bills(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return []

    async def fetch_resource_packages(self) -> list[dict[str, Any]]:
        return []


class DeepSeekFinanceAdapter(ProviderFinanceAdapter):
    async def fetch_balance(self) -> list[dict[str, Any]]:
        api_key = str(self.settings.get("api_key") or "")
        if not api_key:
            raise CustomException(msg="请配置 DeepSeek 财务 API Key")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                "https://api.deepseek.com/user/balance",
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            )
        response.raise_for_status()
        body = response.json()
        result = []
        for item in body.get("balance_infos") or []:
            currency = str(item.get("currency") or "CNY").upper()
            total = _decimal(item.get("total_balance"))
            amount_yuan, rate = _cny(total, currency, self.settings)
            result.append(
                {
                    "currency": currency,
                    "available_amount": total,
                    "cash_amount": _decimal(item.get("topped_up_balance")),
                    "granted_amount": _decimal(item.get("granted_balance")),
                    "amount_yuan": amount_yuan,
                    "exchange_rate": rate,
                    "source": "deepseek_balance_api",
                    "raw_summary": {"is_available": bool(body.get("is_available", True))},
                }
            )
        return result


class OpenAIFinanceAdapter(ProviderFinanceAdapter):
    async def fetch_bills(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        admin_key = str(self.settings.get("admin_key") or "")
        if not admin_key:
            raise CustomException(msg="请配置 OpenAI Organization Admin Key")
        params: dict[str, Any] = {
            "start_time": int(start.timestamp()),
            "end_time": int(end.timestamp()),
            "bucket_width": "1d",
            "limit": min(max((end - start).days + 1, 1), 180),
        }
        rows: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=60) as client:
            while True:
                response = await client.get(
                    "https://api.openai.com/v1/organization/costs",
                    params=params,
                    headers={"Authorization": f"Bearer {admin_key}"},
                )
                response.raise_for_status()
                body = response.json()
                for bucket in body.get("data") or []:
                    bucket_start = datetime.fromtimestamp(int(bucket.get("start_time") or 0), UTC)
                    bucket_end = datetime.fromtimestamp(int(bucket.get("end_time") or 0), UTC)
                    for index, item in enumerate(bucket.get("results") or []):
                        amount_data = item.get("amount") or {}
                        amount = _decimal(amount_data.get("value"))
                        currency = str(amount_data.get("currency") or "USD").upper()
                        amount_yuan, rate = _cny(amount, currency, self.settings)
                        external = ":".join(str(part or "-") for part in (bucket.get("start_time"), item.get("line_item"), item.get("project_id"), index))
                        rows.append(
                            {
                                "external_id": external,
                                "provider_model_id": item.get("model"),
                                "billing_type": str(item.get("line_item") or "inference"),
                                "attribution_key": item.get("project_id"),
                                "currency": currency,
                                "amount_original": amount,
                                "amount_yuan": amount_yuan,
                                "exchange_rate": rate,
                                "usage_detail": {},
                                "service_start_at": bucket_start,
                                "service_end_at": bucket_end,
                                "source": "openai_costs_api",
                            }
                        )
                cursor = body.get("next_page")
                if not cursor:
                    break
                params["page"] = cursor
        return rows


class AnthropicFinanceAdapter(ProviderFinanceAdapter):
    async def fetch_bills(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        admin_key = str(self.settings.get("admin_key") or "")
        if not admin_key:
            raise CustomException(msg="请配置 Anthropic Admin Key")
        params: dict[str, Any] = {
            "starting_at": start.isoformat().replace("+00:00", "Z"),
            "ending_at": end.isoformat().replace("+00:00", "Z"),
            "bucket_width": "1d",
        }
        rows: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=60) as client:
            while True:
                response = await client.get(
                    "https://api.anthropic.com/v1/organizations/cost_report",
                    params=params,
                    headers={"x-api-key": admin_key, "anthropic-version": "2023-06-01"},
                )
                response.raise_for_status()
                body = response.json()
                for bucket in body.get("data") or []:
                    bucket_start = datetime.fromisoformat(str(bucket["starting_at"]).replace("Z", "+00:00"))
                    bucket_end = datetime.fromisoformat(str(bucket["ending_at"]).replace("Z", "+00:00"))
                    for index, item in enumerate(bucket.get("results") or []):
                        amount = _decimal(item.get("amount")) / Decimal("100")
                        currency = str(item.get("currency") or "USD").upper()
                        amount_yuan, rate = _cny(amount, currency, self.settings)
                        rows.append(
                            {
                                "external_id": f"{bucket.get('starting_at')}:{item.get('description') or index}:{item.get('workspace_id') or '-'}",
                                "provider_model_id": item.get("model"),
                                "billing_type": str(item.get("description") or "inference"),
                                "attribution_key": item.get("workspace_id"),
                                "currency": currency,
                                "amount_original": amount,
                                "amount_yuan": amount_yuan,
                                "exchange_rate": rate,
                                "usage_detail": {},
                                "service_start_at": bucket_start,
                                "service_end_at": bucket_end,
                                "source": "anthropic_cost_report",
                            }
                        )
                cursor = body.get("next_page")
                if not cursor:
                    break
                params["page"] = cursor
        return rows


class AlibabaFinanceAdapter(ProviderFinanceAdapter):
    endpoint = "https://business.aliyuncs.com/"

    async def _rpc(self, action: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params = _alibaba_rpc_params(action, self.settings, extra)
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.get(self.endpoint, params=params)
        except httpx.RequestError:
            raise CustomException(msg=f"阿里云财务接口 {action} 网络请求失败，请稍后重试") from None
        try:
            body = response.json()
        except ValueError:
            raise CustomException(msg=f"阿里云财务接口 {action} 返回非 JSON 响应（HTTP {response.status_code}）") from None
        if not isinstance(body, dict):
            raise CustomException(msg=f"阿里云财务接口 {action} 返回格式异常（HTTP {response.status_code}）")
        code = str(body.get("Code") or "")
        if not response.is_success or body.get("Success") is False or code.lower() not in {"", "success", "200"}:
            detail = f"{code or 'UnknownError'}：{body.get('Message') or '请求失败'}"
            if body.get("RequestId"):
                detail += f"（RequestId: {body['RequestId']}）"
            detail = re.sub(r"https?://\S+", "[请求地址已隐藏]", detail)
            for secret in (params["AccessKeyId"], self.settings["access_key_secret"], params["Signature"]):
                for value in (str(secret), _alibaba_encode(secret)):
                    detail = detail.replace(value, "[已隐藏]")
            raise CustomException(msg=f"阿里云财务接口 {action} 失败（HTTP {response.status_code}）：{detail}"[:450])
        return body

    async def fetch_balance(self) -> list[dict[str, Any]]:
        body = await self._rpc("QueryAccountBalance")
        data = body.get("Data")
        if not isinstance(data, dict) or data.get("AvailableAmount") in (None, ""):
            raise CustomException(msg="阿里云财务接口未返回有效余额，请检查账号财务权限")
        amount = _decimal(data["AvailableAmount"])
        currency = str(data.get("Currency") or "CNY").upper()
        amount_yuan, rate = _cny(amount, currency, self.settings)
        return [
            {
                "currency": currency,
                "available_amount": amount,
                "cash_amount": _decimal(data.get("AvailableCashAmount")),
                "granted_amount": _decimal(data.get("CreditAmount")),
                "amount_yuan": amount_yuan,
                "exchange_rate": rate,
                "source": "alibaba_bss_balance",
                "raw_summary": {"account_scope": "aliyun_account"},
            }
        ]

    async def fetch_bills(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        month = datetime(start.year, start.month, 1, tzinfo=UTC)
        while month < end:
            next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
            page = 1
            while True:
                body = await self._rpc(
                    "QueryInstanceBill",
                    {"BillingCycle": month.strftime("%Y-%m"), "PageNum": page, "PageSize": 300},
                )
                data = body.get("Data") or {}
                items = (data.get("Items") or {}).get("Item") or []
                for index, item in enumerate(items):
                    product_code = str(item.get("ProductCode") or "")
                    if product_code and product_code not in {"sfm", "dashscope", "bailian"}:
                        continue
                    amount = _decimal(item.get("PretaxAmount") or item.get("CashAmount"))
                    external_id = str(item.get("InstanceID") or item.get("SubscriptionType") or index)
                    rows.append(
                        {
                            "external_id": f"{month:%Y-%m}:{external_id}:{item.get('Item') or index}",
                            "provider_model_id": item.get("InstanceSpec") or item.get("ProductName"),
                            "billing_type": str(item.get("BillingItem") or item.get("SubscriptionType") or "inference"),
                            "attribution_key": item.get("InstanceID"),
                            "currency": "CNY",
                            "amount_original": amount,
                            "amount_yuan": amount,
                            "exchange_rate": Decimal("1"),
                            "usage_detail": {"product_code": product_code},
                            "service_start_at": month,
                            "service_end_at": next_month,
                            "source": "alibaba_bss_instance_bill",
                        }
                    )
                total = int(data.get("TotalCount") or len(items))
                if page * 300 >= total:
                    break
                page += 1
            month = next_month
        return rows

    async def fetch_resource_packages(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            body = await self._rpc(
                "QueryResourcePackageInstances",
                {"PageNum": page, "PageSize": 300},
            )
            data = body.get("Data") or {}
            items = (data.get("Instances") or {}).get("Instance") or []
            for item in items:
                products = (item.get("ApplicableProducts") or {}).get("Product") or []
                rows.append(
                    {
                        "external_id": str(item.get("InstanceId") or item.get("PackageType") or uuid.uuid4().hex),
                        "name": str(item.get("Remark") or item.get("PackageType") or "未命名资源包"),
                        "package_type": item.get("PackageType"),
                        "total_amount": _decimal(item.get("TotalAmount")),
                        "remaining_amount": _decimal(item.get("RemainingAmount")),
                        "unit": str(item.get("RemainingAmountUnit") or item.get("TotalAmountUnit") or "unit"),
                        "effective_at": _optional_datetime(item.get("EffectiveTime")),
                        "expires_at": _optional_datetime(item.get("ExpiryTime")),
                        "status": str(item.get("Status") or "unknown").lower(),
                        "source": "alibaba_bss_resource_package",
                        "raw_summary": {
                            "region": item.get("Region"),
                            "commodity_code": item.get("CommodityCode"),
                            "applicable_products": products,
                        },
                    }
                )
            total = int(data.get("TotalCount") or len(items))
            if page * 300 >= total:
                break
            page += 1
        return rows


class AWSCostExplorerAdapter(ProviderFinanceAdapter):
    async def fetch_bills(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        def _fetch() -> dict[str, Any]:
            import boto3

            client = boto3.client(
                "ce",
                aws_access_key_id=self.settings.get("access_key_id"),
                aws_secret_access_key=self.settings.get("secret_access_key"),
                aws_session_token=self.settings.get("session_token"),
                region_name=self.settings.get("region") or "us-east-1",
            )
            return client.get_cost_and_usage(
                TimePeriod={"Start": start.date().isoformat(), "End": end.date().isoformat()},
                Granularity="DAILY",
                Metrics=["UnblendedCost"],
                Filter={"Dimensions": {"Key": "SERVICE", "Values": ["Amazon Bedrock"]}},
            )

        body = await asyncio.to_thread(_fetch)
        rows = []
        for item in body.get("ResultsByTime") or []:
            total = (item.get("Total") or {}).get("UnblendedCost") or {}
            amount = _decimal(total.get("Amount"))
            currency = str(total.get("Unit") or "USD").upper()
            amount_yuan, rate = _cny(amount, currency, self.settings)
            rows.append(
                {
                    "external_id": f"aws-bedrock:{item['TimePeriod']['Start']}",
                    "provider_model_id": None,
                    "billing_type": "bedrock_unblended_cost",
                    "attribution_key": self.settings.get("linked_account"),
                    "currency": currency,
                    "amount_original": amount,
                    "amount_yuan": amount_yuan,
                    "exchange_rate": rate,
                    "usage_detail": {"estimated": bool(item.get("Estimated"))},
                    "service_start_at": datetime.fromisoformat(item["TimePeriod"]["Start"]).replace(tzinfo=UTC),
                    "service_end_at": datetime.fromisoformat(item["TimePeriod"]["End"]).replace(tzinfo=UTC),
                    "source": "aws_cost_explorer",
                }
            )
        return rows


ADAPTERS = {
    "alibaba_bss": AlibabaFinanceAdapter,
    "deepseek": DeepSeekFinanceAdapter,
    "openai_admin": OpenAIFinanceAdapter,
    "anthropic_admin": AnthropicFinanceAdapter,
    "aws_cost_explorer": AWSCostExplorerAdapter,
}


class ModelFinanceService:
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    async def _account(self, account_id: int) -> ModelProviderAccountModel:
        account = await self.db.scalar(select(ModelProviderAccountModel).where(ModelProviderAccountModel.id == account_id, ModelProviderAccountModel.is_deleted == False))
        if not account:
            raise CustomException(msg="供应商账号不存在", status_code=404)
        return account

    async def profile(self, account_id: int) -> ModelProviderFinanceProfileModel | None:
        await self._account(account_id)
        return await self.db.scalar(
            select(ModelProviderFinanceProfileModel).where(
                ModelProviderFinanceProfileModel.provider_account_id == account_id,
                ModelProviderFinanceProfileModel.is_deleted == False,
            )
        )

    async def upsert_profile(self, account_id: int, data: FinanceProfileUpsert) -> FinanceProfileOut:
        await self._account(account_id)
        existing = await self.profile(account_id)
        settings = data.settings
        if existing and not settings:
            settings = decrypt_settings(existing.settings_cipher)
        if data.adapter_type not in {"manual", "google_cloud_billing"} and not settings:
            raise CustomException(msg="请填写财务连接凭据")
        values = {
            "adapter_type": data.adapter_type,
            "settings_cipher": encrypt_settings(settings),
            "masked_summary": _masked(settings),
            "capabilities": FINANCE_CAPABILITIES[data.adapter_type],
            "balance_warning_yuan": data.balance_warning_yuan,
            "status": data.status,
            "connection_status": "untested",
            "last_error": None,
        }
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
            existing.updated_id = self.auth.user.id
            item = existing
        else:
            item = ModelProviderFinanceProfileModel(
                provider_account_id=account_id,
                **values,
                created_id=self.auth.user.id,
                updated_id=self.auth.user.id,
            )
            self.db.add(item)
        await self.db.flush()
        return FinanceProfileOut.model_validate(item)

    async def summary(self, account_id: int) -> FinanceSummaryOut:
        profile = await self.profile(account_id)
        balance = await self.db.scalar(
            select(ModelProviderBalanceSnapshotModel)
            .where(
                ModelProviderBalanceSnapshotModel.provider_account_id == account_id,
                ModelProviderBalanceSnapshotModel.is_deleted == False,
            )
            .order_by(ModelProviderBalanceSnapshotModel.fetched_at.desc())
        )
        now = datetime.now(UTC)
        month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
        month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_bills = list(
            (
                await self.db.scalars(
                    select(ModelProviderBillItemModel).where(
                        ModelProviderBillItemModel.provider_account_id == account_id,
                        ModelProviderBillItemModel.service_end_at > month_start,
                        ModelProviderBillItemModel.service_start_at < month_end,
                        ModelProviderBillItemModel.is_deleted == False,
                    )
                )
            ).all()
        )
        bill_total = sum((bill_cost_in_period(b.amount_yuan, b.service_start_at, b.service_end_at, month_start, month_end) for b in month_bills), Decimal(0))
        request_filters = (
            RequestCostUsage.provider_account_id == account_id,
            RequestCostUsage.completed_at >= month_start,
            RequestCostUsage.completed_at <= now,
            RequestCostUsage.is_deleted == False,
        )
        request_count = int(await self.db.scalar(select(func.count(RequestCostUsage.id)).where(*request_filters)) or 0)
        speech_cost, unknown_calls = (
            await self.db.execute(
                select(
                    func.sum(case((RequestCostUsage.usage_kind == "speech", RequestCostUsage.provider_cost_yuan), else_=0)),
                    func.sum(case((RequestCostUsage.provider_cost_yuan.is_(None), 1), else_=0)),
                ).where(*request_filters)
            )
        ).one()
        request_total = _decimal(
            await self.db.scalar(
                select(func.sum(RequestCostUsage.provider_cost_yuan)).where(
                    *request_filters,
                )
            )
        )
        reconciled = _decimal(
            await self.db.scalar(
                select(func.sum(RequestCostUsage.provider_cost_yuan)).where(
                    *request_filters,
                    RequestCostUsage.reconciliation_status == "reconciled",
                )
            )
        )
        resource_fetched_at = await self.db.scalar(
            select(func.max(ModelProviderResourcePackageSnapshotModel.fetched_at)).where(
                ModelProviderResourcePackageSnapshotModel.provider_account_id == account_id,
                ModelProviderResourcePackageSnapshotModel.is_deleted == False,
            )
        )
        resource_packages = (
            []
            if resource_fetched_at is None
            else list(
                (
                    await self.db.scalars(
                        select(ModelProviderResourcePackageSnapshotModel)
                        .where(
                            ModelProviderResourcePackageSnapshotModel.provider_account_id == account_id,
                            ModelProviderResourcePackageSnapshotModel.fetched_at == resource_fetched_at,
                            ModelProviderResourcePackageSnapshotModel.is_deleted == False,
                        )
                        .order_by(ModelProviderResourcePackageSnapshotModel.expires_at)
                    )
                ).all()
            )
        )
        coverage = float(reconciled * 100 / request_total) if request_total > 0 else 0
        return FinanceSummaryOut(
            profile=FinanceProfileOut.model_validate(profile) if profile else None,
            latest_balance=BalanceSnapshotOut.model_validate(balance) if balance else None,
            month_bill_yuan=float(bill_total),
            last_bill_at=profile.last_bill_at if profile else None,
            request_cost_yuan=float(request_total),
            speech_cost_yuan=float(speech_cost or 0),
            unknown_cost_calls=int(unknown_calls or 0),
            month_request_count=request_count,
            difference_yuan=float(bill_total - request_total),
            reconciliation_coverage_rate=round(min(coverage, 100), 2),
            resource_packages=[ResourcePackageOut.model_validate(item) for item in resource_packages],
        )

    async def sync(self, account_id: int, data: FinanceSyncRequest) -> FinanceSummaryOut:
        profile = await self.profile(account_id)
        if not profile or profile.status != "active":
            raise CustomException(msg="请先启用供应商财务连接")
        adapter_class = ADAPTERS.get(profile.adapter_type)
        if not adapter_class:
            raise CustomException(msg="该供应商没有可自动同步的财务接口，请使用账单导入")
        now = datetime.now(UTC)
        end = data.range_end or now
        start = data.range_start or max(end - timedelta(days=31), datetime(end.year, end.month, 1, tzinfo=UTC))
        if start >= end:
            raise CustomException(msg="账单开始时间必须早于结束时间")
        task = ModelProviderSyncTaskModel(
            provider_account_id=account_id,
            sync_type="finance",
            range_start=start,
            range_end=end,
            status="running",
        )
        self.db.add(task)
        await self.db.flush()
        adapter = adapter_class(decrypt_settings(profile.settings_cipher))
        imported = 0
        try:
            balances = await adapter.fetch_balance() if profile.capabilities.get("balance") else []
            for item in balances:
                self.db.add(
                    ModelProviderBalanceSnapshotModel(
                        provider_account_id=account_id,
                        fetched_at=now,
                        **{key: value for key, value in item.items() if key != "exchange_rate"},
                    )
                )
            packages = await adapter.fetch_resource_packages() if profile.capabilities.get("resource_pack") else []
            for item in packages:
                self.db.add(
                    ModelProviderResourcePackageSnapshotModel(
                        provider_account_id=account_id,
                        fetched_at=now,
                        **item,
                    )
                )
            bills = await adapter.fetch_bills(start, end) if profile.capabilities.get("bill") else []
            for item in bills:
                row = ModelProviderBillItemModel(provider_account_id=account_id, reconciliation_method="proportional", **item)
                try:
                    async with self.db.begin_nested():
                        self.db.add(row)
                        await self.db.flush()
                except IntegrityError:
                    continue
                imported += 1
            if bills:
                await self._reconcile(account_id, start, end)
                profile.last_bill_at = max(item["service_end_at"] for item in bills)
            profile.connection_status = "healthy"
            profile.last_synced_at = now
            profile.last_error = None
            task.status = "succeeded"
            task.imported_count = imported
        except Exception as exc:
            profile.connection_status = "failed"
            profile.last_error = str(exc)[:500]
            task.status = "failed"
            task.error_message = str(exc)[:500]
        finally:
            task.completed_at = datetime.now(UTC)
        await self.db.flush()
        return await self.summary(account_id)

    async def _reconcile(self, account_id: int, start: datetime, end: datetime) -> None:
        usage_rows = (
            await self.db.execute(
                select(
                    RequestCostUsage.app_id,
                    func.sum(RequestCostUsage.provider_cost_yuan),
                    func.count(RequestCostUsage.id),
                )
                .where(
                    RequestCostUsage.provider_account_id == account_id,
                    RequestCostUsage.completed_at >= start,
                    RequestCostUsage.completed_at < end,
                    RequestCostUsage.is_deleted == False,
                )
                .group_by(RequestCostUsage.app_id)
            )
        ).all()
        bills = list(
            (
                await self.db.scalars(
                    select(ModelProviderBillItemModel).where(
                        ModelProviderBillItemModel.provider_account_id == account_id,
                        ModelProviderBillItemModel.service_start_at < end,
                        ModelProviderBillItemModel.service_end_at > start,
                        ModelProviderBillItemModel.is_deleted == False,
                    )
                )
            ).all()
        )
        bill_cost = sum((bill_cost_in_period(b.amount_yuan, b.service_start_at, b.service_end_at, start, end) for b in bills), Decimal(0))
        bill_count = len(bills)
        total_request_cost = sum((_decimal(cost) for _, cost, _ in usage_rows), Decimal("0"))
        supplier_cost = _decimal(bill_cost)
        await self.db.execute(
            delete(ModelCostReconciliationModel).where(
                ModelCostReconciliationModel.provider_account_id == account_id,
                ModelCostReconciliationModel.period_start == start,
                ModelCostReconciliationModel.period_end == end,
            )
        )
        method = "exact" if len(usage_rows) == 1 else "proportional"
        for app_id, request_cost, request_count in usage_rows:
            request_amount = _decimal(request_cost)
            allocated = supplier_cost * request_amount / total_request_cost if total_request_cost > 0 else Decimal("0")
            self.db.add(
                ModelCostReconciliationModel(
                    app_id=app_id,
                    provider_account_id=account_id,
                    provider_model_id="all",
                    billing_type="all",
                    period_start=start,
                    period_end=end,
                    request_cost_yuan=request_amount,
                    supplier_cost_yuan=allocated,
                    difference_yuan=allocated - request_amount,
                    request_count=int(request_count or 0),
                    bill_item_count=int(bill_count or 0),
                    reconciliation_method=method,
                    status="reconciled" if supplier_cost > 0 else "unmatched",
                )
            )
        if supplier_cost > 0:
            await self.db.execute(
                update(ModelUsageModel)
                .where(
                    ModelUsageModel.provider_account_id == account_id,
                    ModelUsageModel.completed_at >= start,
                    ModelUsageModel.completed_at < end,
                    ModelUsageModel.is_deleted == False,
                )
                .values(reconciliation_status="reconciled")
            )

    async def test_connection(self, account_id: int) -> FinanceProfileOut:
        profile = await self.profile(account_id)
        if not profile or profile.status != "active":
            raise CustomException(msg="请先保存并启用供应商财务连接")
        adapter_class = ADAPTERS.get(profile.adapter_type)
        if not adapter_class:
            raise CustomException(msg="该供应商仅支持人工账单导入，暂无可测试的财务接口")
        adapter = adapter_class(decrypt_settings(profile.settings_cipher))
        try:
            if profile.capabilities.get("balance"):
                await adapter.fetch_balance()
            elif profile.capabilities.get("bill"):
                now = datetime.now(UTC)
                await adapter.fetch_bills(now - timedelta(days=1), now)
            else:
                raise CustomException(msg="该财务适配器没有可测试能力")
            profile.connection_status = "healthy"
            profile.last_error = None
        except Exception as exc:
            profile.connection_status = "failed"
            profile.last_error = str(exc)[:500]
        await self.db.flush()
        return FinanceProfileOut.model_validate(profile)

    async def import_bills(self, account_id: int, data: ManualBillImport) -> list[ProviderBillOut]:
        await self._account(account_id)
        rows: list[ModelProviderBillItemModel] = []
        for item in data.items:
            payload = item.model_dump()
            amount = _decimal(payload.pop("amount_original"))
            rate = _decimal(payload.pop("exchange_rate"))
            row = ModelProviderBillItemModel(
                provider_account_id=account_id,
                amount_original=amount,
                amount_yuan=amount * rate,
                exchange_rate=rate,
                source="manual_import",
                reconciliation_method="manual",
                **payload,
            )
            try:
                async with self.db.begin_nested():
                    self.db.add(row)
                    await self.db.flush()
            except IntegrityError:
                continue
            rows.append(row)
        if rows:
            await self._reconcile(
                account_id,
                min(item.service_start_at for item in rows),
                max(item.service_end_at for item in rows),
            )
        return [ProviderBillOut.model_validate(row) for row in rows]

    async def prices(self, account_id: int) -> list[PurchasePriceOut]:
        await self._account(account_id)
        rows = list(
            (
                await self.db.scalars(
                    select(ModelPurchasePriceVersionModel)
                    .where(
                        ModelPurchasePriceVersionModel.provider_account_id == account_id,
                        ModelPurchasePriceVersionModel.is_deleted == False,
                    )
                    .order_by(ModelPurchasePriceVersionModel.effective_from.desc())
                )
            ).all()
        )
        return [PurchasePriceOut.model_validate(row) for row in rows]

    async def create_price(self, account_id: int, data: PurchasePriceCreate) -> PurchasePriceOut:
        await self._account(account_id)
        catalog = await self.db.scalar(
            select(ModelCatalogModel).where(
                ModelCatalogModel.id == data.catalog_model_id,
                ModelCatalogModel.provider_account_id == account_id,
                ModelCatalogModel.is_deleted == False,
            )
        )
        if not catalog:
            raise CustomException(msg="模型不属于当前供应商账号")
        active_segments = list(
            (
                await self.db.scalars(
                    select(ModelPurchasePriceVersionModel).where(
                        ModelPurchasePriceVersionModel.catalog_model_id == catalog.id,
                        ModelPurchasePriceVersionModel.region == data.region,
                        ModelPurchasePriceVersionModel.service_tier == data.service_tier,
                        ModelPurchasePriceVersionModel.billing_mode == data.billing_mode,
                        ModelPurchasePriceVersionModel.status == "active",
                        ModelPurchasePriceVersionModel.effective_until.is_(None),
                        ModelPurchasePriceVersionModel.is_deleted == False,
                    )
                )
            ).all()
        )
        new_max = data.context_max if data.context_max is not None else float("inf")
        for segment in active_segments:
            current_max = segment.context_max if segment.context_max is not None else float("inf")
            exact_segment = segment.context_min == data.context_min and segment.context_max == data.context_max
            overlaps = segment.context_min <= new_max and data.context_min <= current_max
            if overlaps and not exact_segment:
                raise CustomException(msg="上下文区间与现有价格重叠，请按现有区间边界发布价格")
        await self.db.execute(
            update(ModelPurchasePriceVersionModel)
            .where(
                ModelPurchasePriceVersionModel.catalog_model_id == catalog.id,
                ModelPurchasePriceVersionModel.region == data.region,
                ModelPurchasePriceVersionModel.service_tier == data.service_tier,
                ModelPurchasePriceVersionModel.billing_mode == data.billing_mode,
                ModelPurchasePriceVersionModel.context_min == data.context_min,
                ModelPurchasePriceVersionModel.context_max == data.context_max,
                ModelPurchasePriceVersionModel.status == "active",
                ModelPurchasePriceVersionModel.effective_until.is_(None),
                ModelPurchasePriceVersionModel.is_deleted == False,
            )
            .values(effective_until=data.effective_from, status="archived")
        )
        item = ModelPurchasePriceVersionModel(
            provider_account_id=account_id,
            provider_model_id=catalog.provider_model_id,
            **data.model_dump(),
            status="active",
            created_id=self.auth.user.id,
            updated_id=self.auth.user.id,
        )
        self.db.add(item)
        if data.context_min == 0:
            catalog.input_cost_per_million = data.input_cost_per_million * data.exchange_rate_to_cny
            catalog.output_cost_per_million = data.output_cost_per_million * data.exchange_rate_to_cny
            catalog.updated_id = self.auth.user.id
        await self.db.flush()
        return PurchasePriceOut.model_validate(item)


__all__ = ["ModelFinanceService", "FINANCE_CAPABILITIES"]

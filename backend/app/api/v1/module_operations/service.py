from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from math import ceil
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.module_billing.model import AppCatalogPlanModel, CreditAccountModel, SubscriptionModel
from app.api.v1.module_client.user.model import ClientAuthEventModel, ClientUserModel
from app.api.v1.module_model_gateway.cost_usage import RequestCostUsage
from app.api.v1.module_model_gateway.model import (
    AppModelBindingModel,
    AppModelRouteModel,
    ModelCatalogModel,
    ModelProviderBalanceSnapshotModel,
    ModelProviderBillItemModel,
    ModelProviderFinanceProfileModel,
)
from app.api.v1.module_payment.order.model import PaymentOrderModel, PaymentRefundModel
from app.api.v1.module_telemetry.model import TelemetryEventModel
from app.api.v1.module_user_operations.model import (
    ClientMessageDeliveryModel,
    ClientSupportTicketModel,
)
from app.core.base_schema import AuthSchema
from app.core.exceptions import CustomException

from .schema import (
    OperationsOverviewSchema,
    OverviewDailySchema,
    OverviewDataQualitySchema,
    OverviewDistributionSchema,
    OverviewHealthSchema,
    OverviewModelCostSchema,
    OverviewRiskSchema,
    OverviewSummarySchema,
)


def _date_key(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _percentage(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0
    return round(numerator * 100 / denominator, 2)


SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class OverviewRange:
    preset: str
    label: str
    start: datetime
    end: datetime
    previous_start: datetime
    previous_end: datetime
    days: int
    grain: str


def resolve_overview_range(
    *,
    preset: str = "last_30_days",
    start_date: date | None = None,
    end_date: date | None = None,
    grain: str | None = None,
    now: datetime | None = None,
) -> OverviewRange:
    local_now = (now or datetime.now(UTC)).astimezone(SHANGHAI)
    today = local_now.date()
    if preset == "today":
        start_day, end_day, label = today, today, "今天"
    elif preset == "yesterday":
        start_day = end_day = today - timedelta(days=1)
        label = "昨天"
    elif preset in {"last_7_days", "last_30_days", "last_90_days"}:
        count = int(preset.split("_")[1])
        start_day, end_day, label = today - timedelta(days=count - 1), today, f"近 {count} 天"
    elif preset == "this_month":
        start_day, end_day, label = today.replace(day=1), today, "本月"
    elif preset == "last_month":
        current_month = today.replace(day=1)
        end_day = current_month - timedelta(days=1)
        start_day, label = end_day.replace(day=1), "上月"
    elif preset == "this_quarter":
        quarter_month = ((today.month - 1) // 3) * 3 + 1
        start_day, end_day, label = today.replace(month=quarter_month, day=1), today, "本季度"
    elif preset == "this_year":
        start_day, end_day, label = today.replace(month=1, day=1), today, "本年"
    elif preset == "custom":
        if not start_date or not end_date:
            raise CustomException(msg="自定义统计需要开始和结束日期", status_code=422)
        if start_date > end_date:
            raise CustomException(msg="开始日期不能晚于结束日期", status_code=422)
        start_day, end_day = start_date, end_date
        label = f"{start_day:%Y-%m-%d} 至 {end_day:%Y-%m-%d}"
    else:
        raise CustomException(msg="不支持的统计周期", status_code=422)
    days = (end_day - start_day).days + 1
    if days > 731:
        raise CustomException(msg="统计区间最长支持 2 年", status_code=422)
    local_start = datetime.combine(start_day, time.min, tzinfo=SHANGHAI)
    local_end_exclusive = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=SHANGHAI)
    if end_day == today:
        local_end_exclusive = min(local_end_exclusive, local_now)
    start, end = local_start.astimezone(UTC), local_end_exclusive.astimezone(UTC)
    duration = end - start
    selected_grain = grain or ("day" if days <= 45 else "week" if days <= 180 else "month")
    if selected_grain not in {"day", "week", "month"}:
        raise CustomException(msg="统计粒度仅支持日、周或月", status_code=422)
    return OverviewRange(
        preset=preset,
        label=label,
        start=start,
        end=end,
        previous_start=start - duration,
        previous_end=start,
        days=days,
        grain=selected_grain,
    )


class OperationsOverviewService:
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    def _app_id(self) -> int:
        if not self.auth.app_id:
            raise CustomException(msg="请先选择客户端", status_code=409)
        return self.auth.app_id

    async def overview(self, query: OverviewRange) -> OperationsOverviewSchema:
        app_id = self._app_id()
        now = datetime.now(UTC)
        period_start = query.start
        current, daily = await self._period_metrics(app_id, query.start, query.end, query.days, query.grain)
        previous_days = max(1, ceil((query.previous_end - query.previous_start).total_seconds() / 86400))
        previous, _ = await self._period_metrics(app_id, query.previous_start, query.previous_end, previous_days, query.grain)
        total_users = int(
            await self.db.scalar(
                select(func.count(ClientUserModel.id)).where(
                    ClientUserModel.app_id == app_id,
                    ClientUserModel.is_deleted.is_(False),
                )
            )
            or 0
        )
        active_subscriptions = int(
            await self.db.scalar(
                select(func.count(SubscriptionModel.id)).where(
                    SubscriptionModel.app_id == app_id,
                    SubscriptionModel.status == "active",
                    SubscriptionModel.current_period_end > now,
                    SubscriptionModel.is_deleted.is_(False),
                )
            )
            or 0
        )
        current.total_users = total_users
        current.active_subscriptions = active_subscriptions
        previous.total_users = int(
            await self.db.scalar(
                select(func.count(ClientUserModel.id)).where(
                    ClientUserModel.app_id == app_id,
                    ClientUserModel.registered_at < period_start,
                    ClientUserModel.is_deleted.is_(False),
                )
            )
            or 0
        )
        previous.active_subscriptions = int(
            await self.db.scalar(
                select(func.count(SubscriptionModel.id)).where(
                    SubscriptionModel.app_id == app_id,
                    SubscriptionModel.status == "active",
                    SubscriptionModel.current_period_start < period_start,
                    SubscriptionModel.current_period_end > query.previous_start,
                    SubscriptionModel.is_deleted.is_(False),
                )
            )
            or 0
        )

        health = await self._health(app_id, now)
        risks = self._risks(current, health)
        telemetry_count, latest_telemetry = (
            await self.db.execute(
                select(func.count(TelemetryEventModel.id), func.max(TelemetryEventModel.occurred_at)).where(
                    TelemetryEventModel.app_id == app_id,
                    TelemetryEventModel.occurred_at >= period_start,
                    TelemetryEventModel.is_deleted.is_(False),
                )
            )
        ).one()
        latest_usage = await self.db.scalar(
            select(func.max(RequestCostUsage.completed_at)).where(
                RequestCostUsage.app_id == app_id,
                RequestCostUsage.is_deleted.is_(False),
            )
        )
        app_provider_accounts = select(RequestCostUsage.provider_account_id).where(
            RequestCostUsage.app_id == app_id,
            RequestCostUsage.provider_account_id.is_not(None),
            RequestCostUsage.is_deleted.is_(False),
        )
        latest_bill = await self.db.scalar(
            select(func.max(ModelProviderBillItemModel.service_end_at)).where(
                ModelProviderBillItemModel.provider_account_id.in_(app_provider_accounts),
                ModelProviderBillItemModel.is_deleted.is_(False),
            )
        )
        actual_usage_calls, estimated_usage_calls = (
            await self.db.execute(
                select(
                    func.sum(case((RequestCostUsage.cost_precision == "actual_usage", 1), else_=0)),
                    func.sum(case((RequestCostUsage.cost_precision == "estimated_usage", 1), else_=0)),
                ).where(
                    RequestCostUsage.app_id == app_id,
                    RequestCostUsage.completed_at >= query.start,
                    RequestCostUsage.completed_at < query.end,
                    RequestCostUsage.is_deleted.is_(False),
                )
            )
        ).one()

        return OperationsOverviewSchema(
            period_days=query.days,
            period_preset=query.preset,
            period_label=query.label,
            grain=query.grain,
            period_start=period_start,
            period_end=query.end,
            generated_at=now,
            summary=current,
            previous=previous,
            daily=daily,
            user_funnel=self._user_funnel(current),
            level_distribution=await self._level_distribution(app_id),
            subscription_distribution=await self._subscription_distribution(app_id, period_start, query.end),
            model_cost_distribution=await self._model_distribution(app_id, period_start, query.end),
            health=health,
            risks=risks,
            data_quality=OverviewDataQualitySchema(
                telemetry_events=int(telemetry_count or 0),
                latest_telemetry_at=latest_telemetry,
                latest_model_usage_at=latest_usage,
                latest_supplier_bill_at=latest_bill,
                actual_usage_calls=int(actual_usage_calls or 0),
                estimated_usage_calls=int(estimated_usage_calls or 0),
                sources=["支付与退款", "订阅与积分", "模型请求成本账", "语音识别成本账", "供应商账单", "客户端运营事件", "工单与站内消息"],
            ),
        )

    async def _period_metrics(
        self,
        app_id: int,
        start: datetime,
        end: datetime,
        days: int,
        grain: str,
    ) -> tuple[OverviewSummarySchema, list[OverviewDailySchema]]:
        start_day = start.astimezone(SHANGHAI).date()
        day_map: dict[str, dict[str, Any]] = {
            (start_day + timedelta(days=index)).isoformat(): {
                "gross_revenue_yuan": 0.0,
                "refund_yuan": 0.0,
                "provider_cost_yuan": 0.0,
                "speech_cost_yuan": 0.0,
                "speech_calls": 0,
                "unknown_cost_calls": 0,
                "supplier_billed_cost_yuan": 0.0,
                "new_users": 0,
                "active_user_ids": set(),
                "paid_user_ids": set(),
                "model_calls": 0,
                "successful_calls": 0,
                "total_tokens": 0,
                "credits_consumed": 0,
                "reconciled_cost_yuan": 0.0,
                "actual_usage_calls": 0,
                "estimated_usage_calls": 0,
            }
            for index in range(days)
        }
        dialect = self.db.get_bind().dialect.name

        def local_date(column):
            if dialect == "postgresql":
                return func.date(func.timezone("Asia/Shanghai", column))
            if dialect == "sqlite":
                return func.date(column, "+8 hours")
            return func.date(column)

        paid_time = func.coalesce(PaymentOrderModel.paid_at, PaymentOrderModel.created_time)
        paid_day = local_date(paid_time)
        order_rows = (
            await self.db.execute(
                select(
                    paid_day,
                    func.sum(PaymentOrderModel.amount_fen),
                    PaymentOrderModel.user_id,
                )
                .where(
                    PaymentOrderModel.app_id == app_id,
                    PaymentOrderModel.status == "paid",
                    paid_time >= start,
                    paid_time < end,
                    PaymentOrderModel.is_deleted.is_(False),
                )
                .group_by(paid_day, PaymentOrderModel.user_id)
            )
        ).all()
        for day, amount_fen, user_id in order_rows:
            item = day_map.get(_date_key(day))
            if item is not None:
                item["gross_revenue_yuan"] += int(amount_fen or 0) / 100
                item["paid_user_ids"].add(int(user_id))

        refund_day = local_date(PaymentRefundModel.refunded_at)
        refund_rows = (
            await self.db.execute(
                select(refund_day, func.sum(PaymentRefundModel.amount_fen))
                .where(
                    PaymentRefundModel.app_id == app_id,
                    PaymentRefundModel.status == "succeeded",
                    PaymentRefundModel.refunded_at >= start,
                    PaymentRefundModel.refunded_at < end,
                    PaymentRefundModel.is_deleted.is_(False),
                )
                .group_by(refund_day)
            )
        ).all()
        for day, amount_fen in refund_rows:
            item = day_map.get(_date_key(day))
            if item is not None:
                item["refund_yuan"] += int(amount_fen or 0) / 100

        usage_day = local_date(RequestCostUsage.completed_at)
        usage_rows = (
            await self.db.execute(
                select(
                    usage_day,
                    RequestCostUsage.user_id,
                    RequestCostUsage.provider_account_id,
                    func.count(RequestCostUsage.id),
                    func.sum(RequestCostUsage.input_tokens + RequestCostUsage.output_tokens),
                    func.sum(RequestCostUsage.charged_credits),
                    func.sum(RequestCostUsage.provider_cost_yuan),
                    func.sum(case((RequestCostUsage.status == "succeeded", 1), else_=0)),
                    func.sum(
                        case(
                            (RequestCostUsage.reconciliation_status == "reconciled", RequestCostUsage.provider_cost_yuan),
                            else_=0,
                        )
                    ),
                    func.sum(case((RequestCostUsage.cost_precision == "actual_usage", 1), else_=0)),
                    func.sum(case((RequestCostUsage.cost_precision == "estimated_usage", 1), else_=0)),
                    func.sum(case((RequestCostUsage.usage_kind == "speech", RequestCostUsage.provider_cost_yuan), else_=0)),
                    func.sum(case((RequestCostUsage.usage_kind == "speech", 1), else_=0)),
                    func.sum(case((RequestCostUsage.provider_cost_yuan.is_(None), 1), else_=0)),
                )
                .where(
                    RequestCostUsage.app_id == app_id,
                    RequestCostUsage.completed_at >= start,
                    RequestCostUsage.completed_at < end,
                    RequestCostUsage.is_deleted.is_(False),
                )
                .group_by(usage_day, RequestCostUsage.user_id, RequestCostUsage.provider_account_id)
            )
        ).all()
        account_app_cost: dict[tuple[str, int], float] = {}
        for day, user_id, account_id, calls, tokens, credits, cost, succeeded, reconciled, actual, estimated, speech_cost, speech_calls, unknown in usage_rows:
            item = day_map.get(_date_key(day))
            if item is not None:
                item["active_user_ids"].add(int(user_id))
                item["model_calls"] += int(calls or 0)
                item["total_tokens"] += int(tokens or 0)
                item["provider_cost_yuan"] += float(cost or 0)
                item["speech_cost_yuan"] += float(speech_cost or 0)
                item["speech_calls"] += int(speech_calls or 0)
                item["unknown_cost_calls"] += int(unknown or 0)
                item["credits_consumed"] += int(credits or 0)
                item["successful_calls"] += int(succeeded or 0)
                item["reconciled_cost_yuan"] += float(reconciled or 0)
                item["actual_usage_calls"] += int(actual or 0)
                item["estimated_usage_calls"] += int(estimated or 0)
                if account_id is not None:
                    key = (_date_key(day), int(account_id))
                    account_app_cost[key] = account_app_cost.get(key, 0.0) + float(cost or 0)

        # Supplier bills belong to platform accounts. Shared accounts are allocated
        # to each client by that day's request-cost share, and are kept separate from
        # request-level economics to avoid double counting.
        account_ids = {account_id for _, account_id in account_app_cost}
        if account_ids:
            all_usage_rows = (
                await self.db.execute(
                    select(
                        usage_day,
                        RequestCostUsage.provider_account_id,
                        func.sum(RequestCostUsage.provider_cost_yuan),
                    )
                    .where(
                        RequestCostUsage.provider_account_id.in_(account_ids),
                        RequestCostUsage.completed_at >= start,
                        RequestCostUsage.completed_at < end,
                        RequestCostUsage.is_deleted.is_(False),
                    )
                    .group_by(usage_day, RequestCostUsage.provider_account_id)
                )
            ).all()
            all_account_cost = {(_date_key(day), int(account_id)): float(cost or 0) for day, account_id, cost in all_usage_rows if account_id is not None}
            bills = list(
                (
                    await self.db.scalars(
                        select(ModelProviderBillItemModel).where(
                            ModelProviderBillItemModel.provider_account_id.in_(account_ids),
                            ModelProviderBillItemModel.service_start_at < end,
                            ModelProviderBillItemModel.service_end_at > start,
                            ModelProviderBillItemModel.is_deleted.is_(False),
                        )
                    )
                ).all()
            )
            for bill in bills:
                service_start = bill.service_start_at.replace(tzinfo=UTC) if bill.service_start_at.tzinfo is None else bill.service_start_at
                service_end = bill.service_end_at.replace(tzinfo=UTC) if bill.service_end_at.tzinfo is None else bill.service_end_at
                duration = (service_end - service_start).total_seconds()
                if duration <= 0:
                    continue
                bill_start = max(service_start, start).astimezone(SHANGHAI).date()
                bill_end = (min(service_end, end) - timedelta(microseconds=1)).astimezone(SHANGHAI).date()
                covered = max((bill_end - bill_start).days + 1, 1)
                for index in range(covered):
                    day = bill_start + timedelta(days=index)
                    key = day.isoformat()
                    item = day_map.get(key)
                    if item is None:
                        continue
                    day_start = datetime.combine(day, time.min, tzinfo=SHANGHAI)
                    overlap = (min(service_end, end, day_start + timedelta(days=1)) - max(service_start, start, day_start)).total_seconds()
                    daily_amount = float(bill.amount_yuan or 0) * max(overlap, 0) / duration
                    app_cost = account_app_cost.get((key, bill.provider_account_id), 0.0)
                    total_cost = all_account_cost.get((key, bill.provider_account_id), 0.0)
                    share = app_cost / total_cost if total_cost > 0 else 0
                    item["supplier_billed_cost_yuan"] += daily_amount * share

        registered_day = local_date(ClientUserModel.registered_at)
        registration_rows = (
            await self.db.execute(
                select(registered_day, func.count(ClientUserModel.id))
                .where(
                    ClientUserModel.app_id == app_id,
                    ClientUserModel.registered_at >= start,
                    ClientUserModel.registered_at < end,
                    ClientUserModel.is_deleted.is_(False),
                )
                .group_by(registered_day)
            )
        ).all()
        for day, count in registration_rows:
            item = day_map.get(_date_key(day))
            if item is not None:
                item["new_users"] += int(count or 0)

        telemetry_day = local_date(TelemetryEventModel.occurred_at)
        telemetry_rows = (
            await self.db.execute(
                select(telemetry_day, TelemetryEventModel.user_id)
                .where(
                    TelemetryEventModel.app_id == app_id,
                    TelemetryEventModel.occurred_at >= start,
                    TelemetryEventModel.occurred_at < end,
                    TelemetryEventModel.is_deleted.is_(False),
                )
                .group_by(telemetry_day, TelemetryEventModel.user_id)
            )
        ).all()
        login_day = local_date(ClientAuthEventModel.created_time)
        login_rows = (
            await self.db.execute(
                select(login_day, ClientAuthEventModel.user_id)
                .where(
                    ClientAuthEventModel.app_id == app_id,
                    ClientAuthEventModel.user_id.is_not(None),
                    ClientAuthEventModel.success.is_(True),
                    ClientAuthEventModel.created_time >= start,
                    ClientAuthEventModel.created_time < end,
                    ClientAuthEventModel.is_deleted.is_(False),
                )
                .group_by(login_day, ClientAuthEventModel.user_id)
            )
        ).all()
        for day, user_id in [*telemetry_rows, *login_rows]:
            item = day_map.get(_date_key(day))
            if item is not None and user_id is not None:
                item["active_user_ids"].add(int(user_id))

        active_ids = set().union(*(item["active_user_ids"] for item in day_map.values())) if day_map else set()
        paid_ids = set().union(*(item["paid_user_ids"] for item in day_map.values())) if day_map else set()
        grouped: dict[str, dict[str, Any]] = {}
        for day_key, item in day_map.items():
            day = date.fromisoformat(day_key)
            bucket_day = day if grain == "day" else day - timedelta(days=day.weekday()) if grain == "week" else day.replace(day=1)
            bucket = grouped.setdefault(
                bucket_day.isoformat(),
                {
                    "start": day,
                    "end": day,
                    "gross_revenue_yuan": 0.0,
                    "refund_yuan": 0.0,
                    "provider_cost_yuan": 0.0,
                    "speech_cost_yuan": 0.0,
                    "speech_calls": 0,
                    "unknown_cost_calls": 0,
                    "supplier_billed_cost_yuan": 0.0,
                    "new_users": 0,
                    "active_user_ids": set(),
                    "paid_user_ids": set(),
                    "model_calls": 0,
                    "total_tokens": 0,
                },
            )
            bucket["start"] = min(bucket["start"], day)
            bucket["end"] = max(bucket["end"], day)
            for field in (
                "gross_revenue_yuan",
                "refund_yuan",
                "provider_cost_yuan",
                "speech_cost_yuan",
                "speech_calls",
                "unknown_cost_calls",
                "supplier_billed_cost_yuan",
                "new_users",
                "model_calls",
                "total_tokens",
            ):
                bucket[field] += item[field]
            bucket["active_user_ids"].update(item["active_user_ids"])
            bucket["paid_user_ids"].update(item["paid_user_ids"])

        daily: list[OverviewDailySchema] = []
        for bucket_key, item in grouped.items():
            gross = round(item["gross_revenue_yuan"], 2)
            refund = round(item["refund_yuan"], 2)
            net = round(gross - refund, 2)
            cost = round(item["provider_cost_yuan"], 4)
            supplier_cost = round(item["supplier_billed_cost_yuan"], 4)
            label = item["start"].strftime("%m/%d") if grain == "day" else f"{item['start']:%m/%d}–{item['end']:%m/%d}" if grain == "week" else item["start"].strftime("%Y-%m")
            daily.append(
                OverviewDailySchema(
                    date=bucket_key,
                    label=label,
                    period_start=datetime.combine(item["start"], time.min, tzinfo=SHANGHAI).astimezone(UTC),
                    period_end=datetime.combine(item["end"] + timedelta(days=1), time.min, tzinfo=SHANGHAI).astimezone(UTC),
                    gross_revenue_yuan=gross,
                    refund_yuan=refund,
                    net_revenue_yuan=net,
                    revenue_yuan=net,
                    provider_cost_yuan=cost,
                    speech_cost_yuan=round(item["speech_cost_yuan"], 4),
                    speech_calls=item["speech_calls"],
                    unknown_cost_calls=item["unknown_cost_calls"],
                    supplier_billed_cost_yuan=supplier_cost,
                    direct_margin_yuan=round(net - cost, 2),
                    new_users=item["new_users"],
                    active_users=len(item["active_user_ids"]),
                    paid_users=len(item["paid_user_ids"]),
                    model_calls=item["model_calls"],
                    total_tokens=item["total_tokens"],
                )
            )

        gross = round(sum(item.gross_revenue_yuan for item in daily), 2)
        refund = round(sum(item.refund_yuan for item in daily), 2)
        revenue = round(gross - refund, 2)
        cost = round(sum(item.provider_cost_yuan for item in daily), 4)
        supplier_cost = round(sum(item.supplier_billed_cost_yuan for item in daily), 4)
        calls = sum(item.model_calls for item in daily)
        raw_values = list(day_map.values())
        reconciled_cost = sum(item["reconciled_cost_yuan"] for item in raw_values)
        coverage = _percentage(reconciled_cost, cost)
        actual_calls = sum(item["actual_usage_calls"] for item in raw_values)
        estimated_calls = sum(item["estimated_usage_calls"] for item in raw_values)
        unknown_calls = sum(item["unknown_cost_calls"] for item in raw_values)
        speech_calls = sum(item["speech_calls"] for item in raw_values)
        cost_status = (
            "incomplete"
            if unknown_calls
            else "reconciled"
            if calls and coverage >= 99.99 and not speech_calls
            else "partial"
            if coverage > 0
            else "estimated"
            if estimated_calls or speech_calls
            else "actual_usage"
            if actual_calls
            else "no_data"
        )
        return (
            OverviewSummarySchema(
                gross_revenue_yuan=gross,
                refund_yuan=refund,
                net_revenue_yuan=revenue,
                revenue_yuan=revenue,
                provider_cost_yuan=cost,
                speech_cost_yuan=round(sum(item["speech_cost_yuan"] for item in raw_values), 4),
                speech_calls=speech_calls,
                unknown_cost_calls=unknown_calls,
                supplier_billed_cost_yuan=supplier_cost,
                cost_difference_yuan=round(supplier_cost - cost, 4),
                reconciliation_coverage_rate=coverage,
                cost_status=cost_status,
                direct_margin_yuan=round(revenue - cost, 2),
                direct_margin_rate=_percentage(revenue - cost, revenue),
                new_users=sum(item.new_users for item in daily),
                active_users=len(active_ids),
                paid_users=len(paid_ids),
                model_calls=calls,
                total_tokens=sum(item.total_tokens for item in daily),
                credits_consumed=sum(item["credits_consumed"] for item in raw_values),
                model_success_rate=_percentage(sum(item["successful_calls"] for item in raw_values), calls),
            ),
            daily,
        )

    def _user_funnel(self, summary: OverviewSummarySchema) -> list[OverviewDistributionSchema]:
        return [
            OverviewDistributionSchema(code="registered", name="累计注册", count=summary.total_users),
            OverviewDistributionSchema(code="active", name="周期活跃", count=summary.active_users),
            OverviewDistributionSchema(code="subscribed", name="有效订阅", count=summary.active_subscriptions),
            OverviewDistributionSchema(code="paid", name="周期付费", count=summary.paid_users),
        ]

    async def _level_distribution(self, app_id: int) -> list[OverviewDistributionSchema]:
        rows = (
            await self.db.execute(
                select(ClientUserModel.level_code, func.count(ClientUserModel.id)).where(ClientUserModel.app_id == app_id, ClientUserModel.is_deleted.is_(False)).group_by(ClientUserModel.level_code)
            )
        ).all()
        counts = {str(code): int(count or 0) for code, count in rows}
        names = {"LV1": "新锐", "LV2": "活跃", "LV3": "成长", "LV4": "高价值", "LV5": "核心"}
        return [OverviewDistributionSchema(code=code, name=f"{code} · {name}", count=counts.get(code, 0)) for code, name in names.items()]

    async def _subscription_distribution(
        self,
        app_id: int,
        start: datetime,
        end: datetime,
    ) -> list[OverviewDistributionSchema]:
        now = datetime.now(UTC)
        subscriber_rows = (
            await self.db.execute(
                select(
                    AppCatalogPlanModel.id,
                    AppCatalogPlanModel.code,
                    AppCatalogPlanModel.name,
                    func.count(SubscriptionModel.id),
                )
                .join(SubscriptionModel, SubscriptionModel.catalog_plan_id == AppCatalogPlanModel.id)
                .where(
                    SubscriptionModel.app_id == app_id,
                    SubscriptionModel.status == "active",
                    SubscriptionModel.current_period_end > now,
                    SubscriptionModel.is_deleted.is_(False),
                    AppCatalogPlanModel.is_deleted.is_(False),
                )
                .group_by(AppCatalogPlanModel.id, AppCatalogPlanModel.code, AppCatalogPlanModel.name)
            )
        ).all()
        paid_time = func.coalesce(PaymentOrderModel.paid_at, PaymentOrderModel.created_time)
        revenue_rows = (
            await self.db.execute(
                select(PaymentOrderModel.catalog_plan_id, func.sum(PaymentOrderModel.amount_fen))
                .where(
                    PaymentOrderModel.app_id == app_id,
                    PaymentOrderModel.status == "paid",
                    paid_time >= start,
                    paid_time < end,
                    PaymentOrderModel.is_deleted.is_(False),
                )
                .group_by(PaymentOrderModel.catalog_plan_id)
            )
        ).all()
        revenue = {int(plan_id): int(amount or 0) / 100 for plan_id, amount in revenue_rows}
        return [
            OverviewDistributionSchema(
                code=code,
                name=name,
                count=int(count or 0),
                revenue_yuan=round(revenue.get(int(plan_id), 0), 2),
            )
            for plan_id, code, name, count in subscriber_rows
        ]

    async def _model_distribution(
        self,
        app_id: int,
        start: datetime,
        end: datetime,
    ) -> list[OverviewModelCostSchema]:
        rows = (
            await self.db.execute(
                select(
                    RequestCostUsage.provider_model_id,
                    RequestCostUsage.usage_kind,
                    func.count(RequestCostUsage.id),
                    func.sum(RequestCostUsage.input_tokens + RequestCostUsage.output_tokens),
                    func.sum(RequestCostUsage.provider_cost_yuan),
                    func.sum(case((RequestCostUsage.status == "succeeded", 1), else_=0)),
                    func.sum(RequestCostUsage.duration_ms),
                    func.sum(case((RequestCostUsage.provider_cost_yuan.is_(None), 1), else_=0)),
                )
                .where(
                    RequestCostUsage.app_id == app_id,
                    RequestCostUsage.completed_at >= start,
                    RequestCostUsage.completed_at < end,
                    RequestCostUsage.is_deleted.is_(False),
                )
                .group_by(RequestCostUsage.provider_model_id, RequestCostUsage.usage_kind)
                .order_by(func.coalesce(func.sum(RequestCostUsage.provider_cost_yuan), 0).desc())
                .limit(8)
            )
        ).all()
        return [
            OverviewModelCostSchema(
                model=model or "未记录模型",
                usage_kind=kind,
                duration_ms=int(duration or 0),
                unknown_cost_calls=int(unknown or 0),
                calls=int(calls or 0),
                tokens=int(tokens or 0),
                cost_yuan=round(float(cost or 0), 4),
                success_rate=_percentage(int(succeeded or 0), int(calls or 0)),
            )
            for model, kind, calls, tokens, cost, succeeded, duration, unknown in rows
        ]

    async def _health(self, app_id: int, now: datetime) -> OverviewHealthSchema:
        open_statuses = ("pending", "processing", "waiting_user")
        open_tickets, overdue_tickets = (
            await self.db.execute(
                select(
                    func.sum(case((ClientSupportTicketModel.status.in_(open_statuses), 1), else_=0)),
                    func.sum(
                        case(
                            (
                                ClientSupportTicketModel.status.in_(open_statuses) & (ClientSupportTicketModel.sla_due_at < now),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                ).where(
                    ClientSupportTicketModel.app_id == app_id,
                    ClientSupportTicketModel.is_deleted.is_(False),
                )
            )
        ).one()
        expiring = int(
            await self.db.scalar(
                select(func.count(SubscriptionModel.id)).where(
                    SubscriptionModel.app_id == app_id,
                    SubscriptionModel.status == "active",
                    SubscriptionModel.current_period_end > now,
                    SubscriptionModel.current_period_end <= now + timedelta(days=7),
                    SubscriptionModel.is_deleted.is_(False),
                )
            )
            or 0
        )
        low_credit, available, pending = (
            await self.db.execute(
                select(
                    func.sum(case((CreditAccountModel.available < 1000, 1), else_=0)),
                    func.sum(CreditAccountModel.available),
                    func.sum(CreditAccountModel.pending),
                ).where(
                    CreditAccountModel.app_id == app_id,
                    CreditAccountModel.is_deleted.is_(False),
                )
            )
        ).one()
        delivered, read, failed = (
            await self.db.execute(
                select(
                    func.sum(case((ClientMessageDeliveryModel.status.in_(("delivered", "read")), 1), else_=0)),
                    func.sum(case((ClientMessageDeliveryModel.read_at.is_not(None), 1), else_=0)),
                    func.sum(case((ClientMessageDeliveryModel.status == "failed", 1), else_=0)),
                ).where(
                    ClientMessageDeliveryModel.app_id == app_id,
                    ClientMessageDeliveryModel.is_deleted.is_(False),
                )
            )
        ).one()
        delivery_total = int(delivered or 0) + int(failed or 0)
        active_routes = int(
            await self.db.scalar(
                select(func.count(AppModelRouteModel.id)).where(
                    AppModelRouteModel.app_id == app_id,
                    AppModelRouteModel.status == "active",
                    AppModelRouteModel.is_deleted.is_(False),
                )
            )
            or 0
        )
        relevant_accounts = set(
            (
                await self.db.scalars(
                    select(ModelCatalogModel.provider_account_id)
                    .join(AppModelBindingModel, AppModelBindingModel.catalog_model_id == ModelCatalogModel.id)
                    .where(
                        AppModelBindingModel.app_id == app_id,
                        AppModelBindingModel.is_deleted.is_(False),
                        ModelCatalogModel.is_deleted.is_(False),
                    )
                    .distinct()
                )
            ).all()
        )
        finance_profiles = (
            []
            if not relevant_accounts
            else list(
                (
                    await self.db.scalars(
                        select(ModelProviderFinanceProfileModel).where(
                            ModelProviderFinanceProfileModel.provider_account_id.in_(relevant_accounts),
                            ModelProviderFinanceProfileModel.status == "active",
                            ModelProviderFinanceProfileModel.is_deleted.is_(False),
                        )
                    )
                ).all()
            )
        )
        low_balance = 0
        for profile in finance_profiles:
            if profile.balance_warning_yuan is None:
                continue
            latest_balance = await self.db.scalar(
                select(ModelProviderBalanceSnapshotModel)
                .where(
                    ModelProviderBalanceSnapshotModel.provider_account_id == profile.provider_account_id,
                    ModelProviderBalanceSnapshotModel.is_deleted.is_(False),
                )
                .order_by(ModelProviderBalanceSnapshotModel.fetched_at.desc())
            )
            if latest_balance and latest_balance.amount_yuan is not None and latest_balance.amount_yuan < profile.balance_warning_yuan:
                low_balance += 1
        finance_failures = sum(1 for item in finance_profiles if item.connection_status == "failed")
        return OverviewHealthSchema(
            open_tickets=int(open_tickets or 0),
            overdue_tickets=int(overdue_tickets or 0),
            expiring_subscriptions=expiring,
            low_credit_users=int(low_credit or 0),
            available_credits=int(available or 0),
            pending_credits=int(pending or 0),
            message_delivery_rate=_percentage(int(delivered or 0), delivery_total),
            message_read_rate=_percentage(int(read or 0), int(delivered or 0)),
            active_model_routes=active_routes,
            provider_finance_accounts=len(finance_profiles),
            low_balance_accounts=low_balance,
            finance_sync_failures=finance_failures,
        )

    def _risks(
        self,
        summary: OverviewSummarySchema,
        health: OverviewHealthSchema,
    ) -> list[OverviewRiskSchema]:
        risks: list[OverviewRiskSchema] = []
        if health.active_model_routes == 0:
            risks.append(
                OverviewRiskSchema(
                    code="model_route_missing",
                    title="模型服务尚未配置",
                    description="当前客户端没有可执行的业务模型路由，智能体请求会严格失败。",
                    severity="critical",
                    count=1,
                    action_path="/resource-center/model-management",
                )
            )
        if health.low_balance_accounts:
            risks.append(
                OverviewRiskSchema(
                    code="provider_balance_low",
                    title="供应商余额低于告警线",
                    description="余额来自供应商财务接口，请及时充值或调整模型路由。",
                    severity="critical",
                    count=health.low_balance_accounts,
                    action_path="/resource-center/model-management",
                )
            )
        if health.finance_sync_failures:
            risks.append(
                OverviewRiskSchema(
                    code="provider_finance_sync_failed",
                    title="供应商账单同步失败",
                    description="上一次成功结果仍保留，请检查财务凭据权限和接口状态。",
                    severity="warning",
                    count=health.finance_sync_failures,
                    action_path="/resource-center/model-management",
                )
            )
        if summary.model_calls and summary.model_success_rate < 95:
            failed = summary.model_calls - round(summary.model_calls * summary.model_success_rate / 100)
            risks.append(
                OverviewRiskSchema(
                    code="model_failure_rate",
                    title="模型成功率低于 95%",
                    description=f"当前周期模型成功率为 {summary.model_success_rate:.1f}%，需检查供应商或降级路由。",
                    severity="warning" if summary.model_success_rate >= 90 else "critical",
                    count=max(1, failed),
                    action_path="/resource-center/model-management",
                )
            )
        if health.overdue_tickets:
            risks.append(
                OverviewRiskSchema(
                    code="support_sla_overdue",
                    title="存在超时工单",
                    description="工单已超过承诺响应时间，建议优先分派并公开回复。",
                    severity="critical",
                    count=health.overdue_tickets,
                    action_path="/user-operations/support-tickets",
                )
            )
        if health.expiring_subscriptions:
            risks.append(
                OverviewRiskSchema(
                    code="subscription_expiring",
                    title="订阅将在 7 天内到期",
                    description="可创建定向站内触达，减少续费中断。",
                    severity="warning",
                    count=health.expiring_subscriptions,
                    action_path="/user-operations/message-trigger",
                )
            )
        if health.low_credit_users:
            risks.append(
                OverviewRiskSchema(
                    code="low_credit_users",
                    title="用户积分即将耗尽",
                    description="可用积分低于 1,000，可能在模型请求时进入购买流程。",
                    severity="info",
                    count=health.low_credit_users,
                    action_path="/user-operations/users",
                )
            )
        return risks[:6]

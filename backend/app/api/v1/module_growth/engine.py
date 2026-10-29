"""Deterministic calculators, shared by previews and execution."""

from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from zoneinfo import ZoneInfo

from .schema import GradePolicy, RewardAction

BUSINESS_TZ = ZoneInfo("Asia/Shanghai")


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def period_key(policy: GradePolicy, at: datetime) -> str:
    local = utc(at).astimezone(BUSINESS_TZ)
    if policy.cadence == "monthly":
        return local.strftime("%Y-%m")
    if policy.cadence == "weekly":
        year, week, _ = local.isocalendar()
        return f"{year}-W{week:02}"
    return local.strftime("%Y-%m-%d")


def evaluate(policy: GradePolicy, metrics: dict[str, int | float | None]) -> dict:
    score = sum(min(Decimal(str(metrics.get(d.metric) or 0)) / d.cap, Decimal(1)) * d.weight for d in policy.dimensions)
    score = score.quantize(Decimal("0.01"), rounding=ROUND_DOWN) if isinstance(score, Decimal) else Decimal(0)
    matched = "R1" if policy.track == "usage" else "ungraded"
    results = []
    for grade in policy.grades:
        conditions = []
        for condition in grade.conditions:
            raw = metrics.get(condition.metric)
            passed = None if raw is None else (Decimal(str(raw)) >= condition.value if condition.operator == "gte" else Decimal(str(raw)) <= condition.value)
            conditions.append({**condition.model_dump(mode="json"), "actual": raw, "passed": passed})
        passed = score >= grade.min_score and all(c["passed"] is True for c in conditions)
        if passed:
            matched = grade.code
        results.append({"code": grade.code, "name": grade.name, "passed": passed, "conditions": conditions})
    return {"grade": matched, "score": float(score), "metrics": metrics, "grades": results, "insufficient": any(c["passed"] is None for g in results for c in g["conditions"])}


def calculate_reward(action: RewardAction, *, net_paid_fen: int, usage_grade: str, promotion_grade: str) -> int:
    if action.calculation == "fixed":
        amount = Decimal(action.amount)
        bonus = action.grade_percent.get(usage_grade, Decimal(0)) + action.grade_percent.get(promotion_grade, Decimal(0))
        amount *= 1 + bonus / 100
    else:
        rate = action.grade_percent.get(promotion_grade, action.grade_percent.get("ungraded", action.percent))
        amount = Decimal(max(0, net_paid_fen)) * rate / 100
        if action.asset == "credits":
            amount = amount * action.credits_per_yuan / 100
    return min(action.maximum, int(amount.to_integral_value(rounding=ROUND_DOWN)))

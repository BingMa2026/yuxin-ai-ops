"""Public copy generated from executable fields; free text never defines the payout."""

from decimal import Decimal

from .engine import calculate_reward
from .schema import IncentivePolicy


def offer_summary(policy: IncentivePolicy, usage_grade: str, promotion_grade: str) -> str:
    parts = []
    for action in policy.actions:
        who = "受邀好友" if action.recipient == "actor" else "邀请人"
        unit = "积分" if action.asset == "credits" else "元现金"
        if action.calculation == "fixed":
            amount = calculate_reward(
                action, net_paid_fen=0, usage_grade=usage_grade if action.recipient == "inviter" else "R1", promotion_grade=promotion_grade if action.recipient == "inviter" else "ungraded"
            )
            value = str(amount) if action.asset == "credits" else f"{amount / 100:.2f}"
            parts.append(f"{who}可获{value}{unit}" + ("（等级加成以行为发生时为准）" if action.grade_percent else ""))
        else:
            rate = action.grade_percent.get(promotion_grade, action.percent) if action.recipient == "inviter" else action.percent
            suffix = "现金" if action.asset == "cash" else f"积分（每元折算{action.credits_per_yuan}积分）"
            cap = str(action.maximum) if action.asset == "credits" else f"{action.maximum / 100:.2f}"
            parts.append(f"{who}按净支付金额的{Decimal(rate):g}%获得{suffix}，单次上限{cap}{unit}")
    if policy.require_subscription:
        parts.append("需持有有效付费订阅")
    if policy.usage_grades or policy.promotion_grades:
        parts.append("适用指定用户等级，以服务端资格校验为准")
    parts.append(f"每人每日最多{policy.daily_limit}次、每月最多{policy.monthly_limit}次；需通过有效行为及邀请关系核验")
    return "；".join(parts) + "。"

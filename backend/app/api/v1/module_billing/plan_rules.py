"""Shared product validation; duration never means unlimited platform credits."""


def validate_entitlement(kind, plan_type, credits, releases, requires_subscription=False):
    if kind == "duration":
        if plan_type != "subscription" or credits != 0 or releases or requires_subscription:
            raise ValueError("时长套餐必须为订阅套餐、积分为0、释放计划为空，且不要求已有订阅")
    elif kind != "credits" or credits <= 0:
        raise ValueError("积分套餐的总积分必须大于0")


def entitlement_for(platform_model_enabled: bool) -> str:
    return "credits" if platform_model_enabled else "duration"

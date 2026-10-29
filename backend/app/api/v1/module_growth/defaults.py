from .schema import GradePolicy, IncentivePolicy, RightsPolicy, RuleDraftIn


def default_drafts() -> list[RuleDraftIn]:
    usage = GradePolicy.model_validate(
        {
            "track": "usage",
            "dimensions": [
                {"metric": "net_paid_fen", "weight": 30, "cap": 300000},
                {"metric": "active_days", "weight": 30, "cap": 30},
                {"metric": "artifacts", "weight": 25, "cap": 10},
                {"metric": "feedback", "weight": 15, "cap": 5},
            ],
            "grades": [
                {"code": "R1", "name": "初步使用", "min_score": 0},
                {"code": "R2", "name": "稳定使用", "min_score": 40, "conditions": [{"metric": "active_days", "value": 5}, {"metric": "artifacts", "value": 1}]},
                {"code": "R3", "name": "核心用户", "min_score": 70, "conditions": [{"metric": "active_days", "value": 15}, {"metric": "artifacts", "value": 3}]},
            ],
        }
    )
    grades = []
    for n, name, regs, users, payers, conversion, retention, refund in [
        (1, "初级推广", 5, 3, 1, 20, None, 15),
        (2, "成长推广", 20, 12, 6, 30, 50, 10),
        (3, "核心推广", 60, 40, 24, 40, 65, 5),
    ]:
        conditions = [
            {"metric": key, "value": value} for key, value in [("registrations", regs), ("first_users", users), ("first_payers", payers), ("conversion_rate", conversion), ("compliance_rate", 98)]
        ]
        conditions.append({"metric": "refund_rate", "operator": "lte", "value": refund})
        if retention is not None:
            conditions.append({"metric": "retention_rate", "value": retention})
        grades.append({"code": f"A{n}", "name": name, "conditions": conditions})
    result = [
        RuleDraftIn(kind="usage", key="usage", name="用户等级", config=usage),
        RuleDraftIn(kind="promotion", key="promotion", name="推广等级", config=GradePolicy(track="promotion", grades=grades)),
        RuleDraftIn(kind="rights", key="rights", name="权益与使用政策", config=RightsPolicy()),
    ]
    policies = [
        ("first_task", {"event": "first_task", "name": "首次有效任务双向奖励", "actions": [{"recipient": r, "asset": "credits", "amount": 2000} for r in ["actor", "inviter"]]}),
        (
            "first_subscription",
            {
                "event": "first_subscription",
                "name": "套餐首次购买推广奖",
                "observe_days": 7,
                "actions": [{"recipient": "inviter", "asset": "cash", "calculation": "paid_percent", "percent": 3, "grade_percent": {"A1": 5, "A2": 8, "A3": 10}}],
            },
        ),
        (
            "first_traffic",
            {
                "event": "first_traffic",
                "name": "流量包首次购买推广奖",
                "observe_days": 7,
                "actions": [{"recipient": "inviter", "asset": "cash", "calculation": "paid_percent", "percent": 1, "grade_percent": {"A1": 2, "A2": 3, "A3": 5}}],
            },
        ),
        (
            "daily_login",
            {
                "event": "daily_login",
                "name": "每日登录奖励",
                "mode": "auto",
                "daily_limit": 1,
                "monthly_limit": 31,
                "require_subscription": True,
                "actions": [{"recipient": "actor", "asset": "credits", "amount": 100}],
            },
        ),
        ("artifact", {"event": "artifact", "name": "有效成果奖励", "actions": [{"recipient": "actor", "asset": "credits", "amount": 1000}]}),
        ("cocreate", {"event": "cocreate", "name": "共创验收奖励", "actions": [{"recipient": "actor", "asset": "credits", "amount": 2000}]}),
    ]
    for grade, amount in [("S", 2000), ("A", 800), ("B", 400), ("C", 150)]:
        policies.append(
            (f"feedback_{grade.lower()}", {"event": "feedback", "name": f"{grade}级反馈采纳奖", "feedback_grade": grade, "actions": [{"recipient": "actor", "asset": "credits", "amount": amount}]})
        )
    for key, values in policies:
        config = IncentivePolicy.model_validate(values)
        result.append(RuleDraftIn(kind="incentive", key=key, name=config.name, config=config))
    return result

"""Shared SQL grade selectors for user lists, segments and pricing audiences."""

from sqlalchemy import func, or_, select

from app.api.v1.module_client.user.model import ClientUserModel

from .model import GrowthProfileModel


def grade_value(app_id: int, track: str):
    column = GrowthProfileModel.usage_grade if track == "usage" else GrowthProfileModel.promotion_grade
    return func.coalesce(
        select(column).where(GrowthProfileModel.app_id == app_id, GrowthProfileModel.user_id == ClientUserModel.id).correlate(ClientUserModel).scalar_subquery(),
        "R1" if track == "usage" else "ungraded",
    )


def grade_codes(app_id: int, codes: list[str]):
    return or_(
        ClientUserModel.level_code.in_([c for c in codes if c.startswith("LV")]),
        grade_value(app_id, "usage").in_([c for c in codes if c.startswith("R")]),
        grade_value(app_id, "promotion").in_([c for c in codes if c.startswith("A") or c == "ungraded"]),
    )


def segment_conditions(app_id: int, filters: dict):
    conditions = []
    for key, column in [
        ("level_code", ClientUserModel.level_code),
        ("status", ClientUserModel.status),
        ("usage_grade", grade_value(app_id, "usage")),
        ("promotion_grade", grade_value(app_id, "promotion")),
    ]:
        if filters.get(key):
            conditions.append(column == filters[key])
    return conditions

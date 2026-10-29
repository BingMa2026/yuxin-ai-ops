from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.base_schema import BaseQueryParam, BaseSchema

WorkspaceModuleStatus = Literal["active", "coming_soon", "disabled"]


class WorkspaceModuleCreateSchema(BaseModel):
    code: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$", description="模块编码")
    name: str = Field(..., min_length=1, max_length=64, description="模块名称")
    icon: str | None = Field(default=None, max_length=64, description="模块图标")
    description: str | None = Field(default=None, max_length=255, description="模块描述")
    accent: str = Field(default="blue", min_length=1, max_length=20, description="主题色预设")
    order: int = Field(default=999, ge=0, description="排序")
    status: WorkspaceModuleStatus = Field(default="active", description="模块状态")

    @model_validator(mode="before")
    @classmethod
    def _strip_strings(cls, values):
        if isinstance(values, dict):
            for key in ("code", "name", "icon", "description", "accent", "status"):
                value = values.get(key)
                if isinstance(value, str):
                    value = value.strip()
                    values[key] = value or None
        return values


class WorkspaceModuleUpdateSchema(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$", description="模块编码")
    name: str | None = Field(default=None, min_length=1, max_length=64, description="模块名称")
    icon: str | None = Field(default=None, max_length=64, description="模块图标")
    description: str | None = Field(default=None, max_length=255, description="模块描述")
    accent: str | None = Field(default=None, min_length=1, max_length=20, description="主题色预设")
    order: int | None = Field(default=None, ge=0, description="排序")
    status: WorkspaceModuleStatus | None = Field(default=None, description="模块状态")

    @field_validator("code", "name", "icon", "description", "accent", "status", mode="before")
    @classmethod
    def _strip_strings(cls, value):
        return value.strip() or None if isinstance(value, str) else value


class WorkspaceModuleMenuItem(BaseModel):
    name: str
    icon: str | None = None
    route_path: str | None = None


class WorkspaceModuleOutSchema(WorkspaceModuleCreateSchema, BaseSchema):
    model_config = ConfigDict(from_attributes=True)

    menu_count: int = 0
    menu_items: list[WorkspaceModuleMenuItem] = Field(default_factory=list)


class WorkspaceModuleQueryParam(BaseQueryParam):
    code: str | None = Field(default=None, description="模块编码", json_schema_extra={"q": "like"})
    name: str | None = Field(default=None, description="模块名称", json_schema_extra={"q": "like"})
    status: WorkspaceModuleStatus | None = Field(default=None, description="模块状态", json_schema_extra={"q": "eq"})

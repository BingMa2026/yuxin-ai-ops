from typing import TYPE_CHECKING

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import ModelMixin

if TYPE_CHECKING:
    from app.api.v1.module_system.menu.model import MenuModel


class WorkspaceModuleModel(ModelMixin):
    """工作台模块定义。

    模块只负责菜单分组和入口展示；用户权限始终由 ``sys_menu`` 与角色菜单关系决定。
    """

    __tablename__: str = "sys_module"
    __table_args__: dict[str, str] = {"comment": "运营平台工作台模块表"}

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True, comment="模块编码")
    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="模块名称")
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="模块图标")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="模块描述")
    accent: Mapped[str] = mapped_column(String(20), nullable=False, default="blue", server_default="blue", comment="主题色预设")
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=999, index=True, comment="排序")
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
        index=True,
        comment="状态(active/coming_soon/disabled)",
    )

    menus: Mapped[list["MenuModel"]] = relationship(back_populates="workspace_module")

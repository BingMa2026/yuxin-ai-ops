"""Client agreements, immutable versions, scene bindings and acceptance records."""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "20260911_agreements"
down_revision = "20260910_finance_center"
branch_labels = None
depends_on = None


def _base():
    return [
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uuid", sa.String(64), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_time", sa.DateTime(timezone=True)),
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("client_app.id", ondelete="RESTRICT"), nullable=False),
    ]


def upgrade():
    _create_table(
        "client_agreement",
        *_base(),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("change_summary", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("has_draft", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL")),
        sa.UniqueConstraint("app_id", "code", name="uq_agreement_code"),
    )
    _create_table(
        "client_agreement_version",
        *_base(),
        sa.Column("agreement_id", sa.Integer(), sa.ForeignKey("client_agreement.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("change_summary", sa.String(1000), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_by", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL")),
        sa.UniqueConstraint("app_id", "agreement_id", "version", name="uq_agreement_version"),
    )
    _create_table(
        "client_agreement_scene",
        *_base(),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("agreement_ids", sa.JSON(), nullable=False),
        sa.Column("require_acceptance", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("sys_user.id", ondelete="SET NULL")),
        sa.UniqueConstraint("app_id", "code", name="uq_agreement_scene_code"),
    )
    _create_table(
        "client_agreement_acceptance",
        *_base(),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("client_user.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("scene_code", sa.String(64), nullable=False),
        sa.Column("scene_revision", sa.Integer(), nullable=False),
        sa.Column("version_ids", sa.JSON(), nullable=False),
        sa.Column("business_ref", sa.String(128), nullable=False),
    )
    for table in ("client_agreement", "client_agreement_version", "client_agreement_scene", "client_agreement_acceptance"):
        for field in ("id", "uuid", "is_deleted", "created_time"):
            _create_index(f"ix_{table}_{field}", table, [field], unique=field == "uuid")
    _create_index("ix_agreement_scope", "client_agreement", ["app_id", "status", "is_deleted"])
    _create_index("ix_agreement_acceptance_user", "client_agreement_acceptance", ["app_id", "user_id", "created_time"])
    _menus()


def _create_table(name, *elements):
    if op.get_context().as_sql or not sa.inspect(op.get_bind()).has_table(name):
        return op.create_table(name, *elements)
    # Some installations created ORM tables before applying their Alembic revision.
    # Adopt only an equivalent schema; never drop data or silently stamp schema drift.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    expected = sa.Table(name, sa.MetaData(), *elements)
    columns = {column["name"]: column for column in inspector.get_columns(name)}
    compile_type = bind.dialect.type_compiler.process
    if set(columns) != set(expected.columns.keys()):
        raise RuntimeError(f"Existing {name} has incompatible columns")
    for column in expected.columns:
        actual = columns[column.name]
        if compile_type(column.type) != compile_type(actual["type"]) or column.nullable != actual["nullable"]:
            raise RuntimeError(f"Existing {name}.{column.name} has incompatible type or nullability")
    if set(inspector.get_pk_constraint(name)["constrained_columns"]) != {column.name for column in expected.primary_key}:
        raise RuntimeError(f"Existing {name} has an incompatible primary key")
    uniques = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(name)}
    for constraint in expected.constraints:
        if isinstance(constraint, sa.UniqueConstraint) and tuple(column.name for column in constraint.columns) not in uniques:
            raise RuntimeError(f"Existing {name} is missing unique constraint {constraint.name}")
    foreign_keys = {(tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"]), item.get("options", {}).get("ondelete")) for item in inspector.get_foreign_keys(name)}
    for constraint in expected.foreign_key_constraints:
        targets = [element.target_fullname.split(".") for element in constraint.elements]
        key = (tuple(column.name for column in constraint.columns), targets[0][-2], tuple(target[-1] for target in targets), constraint.ondelete)
        if key not in foreign_keys:
            raise RuntimeError(f"Existing {name} has an incompatible foreign key")


def _create_index(name, table, columns, unique=False):
    if not op.get_context().as_sql:
        existing = next((item for item in sa.inspect(op.get_bind()).get_indexes(table) if item["name"] == name), None)
        if existing:
            if existing["column_names"] != columns or bool(existing["unique"]) != unique:
                raise RuntimeError(f"Existing index {name} is incompatible")
            return
    op.create_index(name, table, columns, unique=unique)


def _menus():
    if op.get_context().as_sql:
        return
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("sys_menu"):
        return
    menu = sa.Table("sys_menu", sa.MetaData(), autoload_with=bind)
    existing = bind.execute(sa.select(menu).where(menu.c.route_name == "AgreementManagement")).mappings().first()
    if existing and existing["is_deleted"]:
        return
    parent = bind.execute(sa.select(menu).where(menu.c.route_name == "UserOperations", menu.c.is_deleted == False)).mappings().first()
    if not parent:
        return
    values = dict(parent)
    values.pop("id")
    values.update(
        uuid=str(uuid4()),
        name="协议与政策",
        title="协议与政策",
        parent_id=parent["id"],
        module_id=None,
        type=2,
        redirect=None,
        hidden=False,
        always_show=False,
        affix=False,
        params=None,
        link=None,
        is_iframe=False,
        is_hide_tab=False,
        active_path=None,
        show_badge=False,
        show_text_badge=None,
        status=0,
        route_name="AgreementManagement",
        route_path="agreements",
        component_path="module_agreement/index",
        permission="workspace:user:agreement:list",
        icon="ri:file-text-line",
        order=4,
        description="按当前客户端维护协议、版本和使用场景",
        created_time=datetime.now(UTC),
        updated_time=datetime.now(UTC),
    )
    page_id = existing["id"] if existing else bind.execute(menu.insert().values(**values).returning(menu.c.id)).scalar_one()
    for order, (name, action) in enumerate((("新增与编辑协议", "update"), ("发布与归档协议", "publish"), ("删除草稿与场景", "delete"), ("配置使用场景", "scene")), 1):
        if bind.scalar(sa.select(menu.c.id).where(menu.c.permission == f"workspace:user:agreement:{action}")):
            continue
        values.update(
            uuid=str(uuid4()),
            parent_id=page_id,
            type=3,
            name=name,
            title=name,
            order=order,
            route_name=None,
            route_path=None,
            component_path=None,
            permission=f"workspace:user:agreement:{action}",
            icon=None,
        )
        bind.execute(menu.insert().values(**values))
    # Existing roles are not silently granted new publication privileges.


def downgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table("sys_menu"):
        metadata = sa.MetaData()
        menu = sa.Table("sys_menu", metadata, autoload_with=bind)
        ids = list(bind.execute(sa.select(menu.c.id).where(menu.c.permission.like("workspace:user:agreement:%"))).scalars())
        if ids:
            if sa.inspect(bind).has_table("sys_role_menus"):
                grants = sa.Table("sys_role_menus", metadata, autoload_with=bind)
                bind.execute(grants.delete().where(grants.c.menu_id.in_(ids)))
            bind.execute(menu.delete().where(menu.c.id.in_(ids), menu.c.type == 3))
            bind.execute(menu.delete().where(menu.c.id.in_(ids)))
    for table in ("client_agreement_acceptance", "client_agreement_scene", "client_agreement_version", "client_agreement"):
        op.drop_table(table)

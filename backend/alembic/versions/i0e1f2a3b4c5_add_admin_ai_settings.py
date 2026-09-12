"""add admin ai settings

Revision ID: i0e1f2a3b4c5
Revises: h9d0e1f2a3b4
Create Date: 2026-05-30 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "i0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "h9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_AI_SETTING_PERMISSIONS = [
    ("ai_setting:read", "ai_setting", "read", "ai_setting", "查看 AI 解析设置"),
    ("ai_setting:write", "ai_setting", "write", "ai_setting", "修改 AI 解析设置"),
]


def upgrade() -> None:
    op.create_table(
        "admin_ai_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ai_parse_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("monthly_call_limit", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("admin_users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "admin_ai_usage_monthly",
        sa.Column("year_month", sa.String(length=7), primary_key=True),
        sa.Column("call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("limit_snapshot", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    connection = op.get_bind()
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("resource", sa.String()),
        sa.column("action", sa.String()),
        sa.column("category", sa.String()),
        sa.column("description", sa.String()),
    )
    roles = sa.table("roles", sa.column("id", sa.Integer()), sa.column("name", sa.String()))
    role_permissions = sa.table("role_permissions", sa.column("role_id", sa.Integer()), sa.column("permission_id", sa.Integer()))

    for name, resource, action, category, description in _AI_SETTING_PERMISSIONS:
        exists = connection.execute(sa.select(permissions.c.id).where(permissions.c.name == name)).scalar_one_or_none()
        if exists is None:
            connection.execute(
                permissions.insert().values(
                    name=name,
                    resource=resource,
                    action=action,
                    category=category,
                    description=description,
                )
            )

    super_admin_id = connection.execute(sa.select(roles.c.id).where(roles.c.name == "super_admin")).scalar_one_or_none()
    if super_admin_id is None:
        return

    for name, *_ in _AI_SETTING_PERMISSIONS:
        permission_id = connection.execute(sa.select(permissions.c.id).where(permissions.c.name == name)).scalar_one()
        exists = connection.execute(
            sa.select(role_permissions.c.role_id).where(
                role_permissions.c.role_id == super_admin_id,
                role_permissions.c.permission_id == permission_id,
            )
        ).scalar_one_or_none()
        if exists is None:
            connection.execute(role_permissions.insert().values(role_id=super_admin_id, permission_id=permission_id))


def downgrade() -> None:
    connection = op.get_bind()
    permissions = sa.table("permissions", sa.column("id", sa.Integer()), sa.column("name", sa.String()))
    role_permissions = sa.table("role_permissions", sa.column("permission_id", sa.Integer()))
    names = [item[0] for item in _AI_SETTING_PERMISSIONS]
    permission_ids = [
        row[0]
        for row in connection.execute(sa.select(permissions.c.id).where(permissions.c.name.in_(names))).all()
    ]
    if permission_ids:
        connection.execute(role_permissions.delete().where(role_permissions.c.permission_id.in_(permission_ids)))
    connection.execute(permissions.delete().where(permissions.c.name.in_(names)))
    op.drop_table("admin_ai_usage_monthly")
    op.drop_table("admin_ai_settings")

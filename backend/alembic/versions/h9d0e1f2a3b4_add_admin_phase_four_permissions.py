"""add admin phase four permissions

Revision ID: h9d0e1f2a3b4
Revises: h8c9d0e1f2g3
Create Date: 2026-05-29 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "h9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "h8c9d0e1f2g3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PHASE_FOUR_PERMISSIONS = [
    ("subject:read", "subject", "read", "content", "读取科目"),
    ("subject:write", "subject", "write", "content", "创建和编辑科目"),
    ("subject:delete", "subject", "delete", "content", "删除科目"),
    ("import:read", "import", "read", "content", "读取导入批次"),
    ("import:write", "import", "write", "content", "创建导入 AI 任务"),
]


def upgrade() -> None:
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

    for name, resource, action, category, description in _PHASE_FOUR_PERMISSIONS:
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

    for name, *_ in _PHASE_FOUR_PERMISSIONS:
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
    names = [item[0] for item in _PHASE_FOUR_PERMISSIONS]
    permission_ids = [
        row[0]
        for row in connection.execute(sa.select(permissions.c.id).where(permissions.c.name.in_(names))).all()
    ]
    if permission_ids:
        connection.execute(role_permissions.delete().where(role_permissions.c.permission_id.in_(permission_ids)))
    connection.execute(permissions.delete().where(permissions.c.name.in_(names)))

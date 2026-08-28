"""add system RBAC permissions

Revision ID: b6c7d8e9f0a1
Revises: qvkp20260827
Create Date: 2026-08-28 20:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6c7d8e9f0a1"
down_revision: Union[str, Sequence[str], None] = "qvkp20260827"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SYSTEM_PERMISSIONS = (
    (
        "system:read",
        "system",
        "read",
        "system",
        "查看系统任务、队列与运行状态",
    ),
    (
        "system:write",
        "system",
        "write",
        "system",
        "执行系统维护任务及管理任务队列",
    ),
    (
        "system:backup",
        "system",
        "backup",
        "system",
        "查看和执行数据库备份",
    ),
)


def _tables():
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("resource", sa.String()),
        sa.column("action", sa.String()),
        sa.column("category", sa.String()),
        sa.column("description", sa.String()),
    )
    roles = sa.table(
        "roles",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Integer()),
        sa.column("permission_id", sa.Integer()),
        sa.column("granted_by", sa.Integer()),
    )
    return permissions, roles, role_permissions


def _grant_if_missing(connection, role_permissions, role_id: int | None, permission_id: int) -> None:
    if role_id is None:
        return
    exists = connection.execute(
        sa.select(role_permissions.c.role_id).where(
            role_permissions.c.role_id == role_id,
            role_permissions.c.permission_id == permission_id,
        )
    ).scalar_one_or_none()
    if exists is None:
        connection.execute(
            role_permissions.insert().values(
                role_id=role_id,
                permission_id=permission_id,
                granted_by=None,
            )
        )


def upgrade() -> None:
    connection = op.get_bind()
    permissions, roles, role_permissions = _tables()

    permission_ids: dict[str, int] = {}
    for name, resource, action, category, description in _SYSTEM_PERMISSIONS:
        permission_id = connection.execute(
            sa.select(permissions.c.id).where(permissions.c.name == name)
        ).scalar_one_or_none()
        if permission_id is None:
            connection.execute(
                permissions.insert().values(
                    name=name,
                    resource=resource,
                    action=action,
                    category=category,
                    description=description,
                )
            )
            permission_id = connection.execute(
                sa.select(permissions.c.id).where(permissions.c.name == name)
            ).scalar_one()
        else:
            # Make the migration safe after a short-lived runtime seed from an
            # earlier deployment and normalize metadata to the canonical values.
            connection.execute(
                permissions.update()
                .where(permissions.c.id == permission_id)
                .values(
                    resource=resource,
                    action=action,
                    category=category,
                    description=description,
                )
            )
        permission_ids[name] = permission_id

    super_admin_id = connection.execute(
        sa.select(roles.c.id).where(roles.c.name == "super_admin")
    ).scalar_one_or_none()
    admin_id = connection.execute(
        sa.select(roles.c.id).where(roles.c.name == "admin")
    ).scalar_one_or_none()

    # Super administrators own all system operations.
    for permission_id in permission_ids.values():
        _grant_if_missing(connection, role_permissions, super_admin_id, permission_id)

    # Normal administrators may observe system state but cannot mutate queues or
    # execute/read database backups unless explicitly granted later through RBAC.
    _grant_if_missing(
        connection,
        role_permissions,
        admin_id,
        permission_ids["system:read"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    permissions, roles, role_permissions = _tables()

    names = [item[0] for item in _SYSTEM_PERMISSIONS]
    permission_rows = connection.execute(
        sa.select(permissions.c.id, permissions.c.name).where(permissions.c.name.in_(names))
    ).all()
    if not permission_rows:
        return

    role_ids = [
        row[0]
        for row in connection.execute(
            sa.select(roles.c.id).where(roles.c.name.in_(["super_admin", "admin"]))
        ).all()
    ]
    permission_ids = [row[0] for row in permission_rows]

    if role_ids:
        connection.execute(
            role_permissions.delete().where(
                role_permissions.c.role_id.in_(role_ids),
                role_permissions.c.permission_id.in_(permission_ids),
            )
        )

    # Preserve a permission if a custom role still references it. This makes
    # downgrade safe even when operators granted system:* to additional roles.
    for permission_id in permission_ids:
        still_used = connection.execute(
            sa.select(role_permissions.c.role_id)
            .where(role_permissions.c.permission_id == permission_id)
            .limit(1)
        ).scalar_one_or_none()
        if still_used is None:
            connection.execute(
                permissions.delete().where(permissions.c.id == permission_id)
            )

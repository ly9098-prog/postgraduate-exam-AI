from app.core.admin_security import hash_admin_password
from app.models.admin import AdminUser, AuditLog, Permission, Role, RolePermission
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

DEV_ADMIN_USERNAME = "admin"
DEV_ADMIN_PASSWORD = "Admin@123456"
SUPER_ADMIN_ROLE_NAME = "super_admin"
ADMIN_ROLE_NAME = "admin"
LOCAL_APP_ENVS = {"development", "local", "test"}

ADMIN_ROLE_PERMISSION_NAMES = {
    "dashboard:read",
    "app-user:read",
    "app-user:write",
    "app-user:ban",
    "admin-user:read",
    "admin-user:create",
    "admin-user:update",
    "admin-user:delete",
    "admin-user:force-logout",
    "admin-user:reset-password",
    "question:read",
    "question:write",
    "question:review",
    "question:batch_review",
    "subject:read",
    "subject:write",
    "role:read",
    "import:read",
    "import:write",
    "ai_setting:read",
    "audit:read",
}

ADMIN_PERMISSION_DEFINITIONS: tuple[dict[str, str], ...] = (
    {"name": "dashboard:read", "resource": "dashboard", "action": "read", "category": "dashboard", "description": "查看统计概览"},
    {"name": "app-user:read", "resource": "app-user", "action": "read", "category": "app_user", "description": "查看小程序用户"},
    {"name": "app-user:write", "resource": "app-user", "action": "write", "category": "app_user", "description": "编辑小程序用户"},
    {"name": "app-user:ban", "resource": "app-user", "action": "ban", "category": "app_user", "description": "封禁或解封小程序用户"},
    {"name": "admin-user:read", "resource": "admin-user", "action": "read", "category": "admin_user", "description": "查看后台管理员"},
    {"name": "admin-user:create", "resource": "admin-user", "action": "create", "category": "admin_user", "description": "创建后台管理员"},
    {"name": "admin-user:update", "resource": "admin-user", "action": "update", "category": "admin_user", "description": "更新后台管理员"},
    {"name": "admin-user:delete", "resource": "admin-user", "action": "delete", "category": "admin_user", "description": "删除后台管理员"},
    {"name": "admin-user:force-logout", "resource": "admin-user", "action": "force-logout", "category": "admin_user", "description": "强制后台管理员下线"},
    {"name": "admin-user:reset-password", "resource": "admin-user", "action": "reset-password", "category": "admin_user", "description": "重置后台管理员密码"},
    {"name": "question:read", "resource": "question", "action": "read", "category": "question", "description": "查看题目"},
    {"name": "question:write", "resource": "question", "action": "write", "category": "question", "description": "创建和编辑题目"},
    {"name": "question:delete", "resource": "question", "action": "delete", "category": "question", "description": "删除题目"},
    {"name": "question:review", "resource": "question", "action": "review", "category": "question", "description": "审核题目"},
    {"name": "question:batch_review", "resource": "question", "action": "batch_review", "category": "question", "description": "批量审核题目"},
    {"name": "subject:read", "resource": "subject", "action": "read", "category": "subject", "description": "查看科目"},
    {"name": "subject:write", "resource": "subject", "action": "write", "category": "subject", "description": "创建和编辑科目"},
    {"name": "subject:delete", "resource": "subject", "action": "delete", "category": "subject", "description": "删除科目"},
    {"name": "role:read", "resource": "role", "action": "read", "category": "rbac", "description": "查看角色"},
    {"name": "role:write", "resource": "role", "action": "write", "category": "rbac", "description": "编辑角色权限"},
    {"name": "role:delete", "resource": "role", "action": "delete", "category": "rbac", "description": "删除非系统角色"},
    {"name": "permission:read", "resource": "permission", "action": "read", "category": "rbac", "description": "查看权限"},
    {"name": "import:read", "resource": "import", "action": "read", "category": "import", "description": "查看导入任务"},
    {"name": "import:write", "resource": "import", "action": "write", "category": "import", "description": "管理导入任务"},
    {"name": "ai_setting:read", "resource": "ai_setting", "action": "read", "category": "ai_setting", "description": "查看 AI 解析设置"},
    {"name": "ai_setting:write", "resource": "ai_setting", "action": "write", "category": "ai_setting", "description": "修改 AI 解析设置"},
    {"name": "audit:read", "resource": "audit", "action": "read", "category": "audit", "description": "查看审计日志"},
    {"name": "sync:write", "resource": "sync", "action": "write", "category": "sync", "description": "执行本地→云端数据同步"},
)


async def ensure_dev_super_admin(db: AsyncSession, app_env: str) -> bool:
    if app_env.lower() not in LOCAL_APP_ENVS:
        return False

    role = await _ensure_super_admin_role(db)
    admin_role = await _ensure_admin_role(db)
    permissions = await _ensure_permissions(db)
    permission_map = {permission.name: permission.id for permission in permissions}
    await _ensure_role_permissions(db, role.id, [permission.id for permission in permissions])
    await _ensure_role_permissions(db, admin_role.id, [permission_map[name] for name in ADMIN_ROLE_PERMISSION_NAMES])
    created_admin = await _ensure_admin_user(db, role.id)

    if created_admin:
        audit_log_id = await _next_audit_log_id(db)
        db.add(
            AuditLog(
                id=audit_log_id,
                operator_id=None,
                operator_name=None,
                action="system.init_super_admin",
                resource_type="admin_user",
                resource_id=str(created_admin.id),
                severity="critical",
                detail={"username": created_admin.username, "role": SUPER_ADMIN_ROLE_NAME, "env": app_env},
                ip="<bootstrap>",
                status="success",
            )
        )
    return created_admin is not None


async def _next_audit_log_id(db: AsyncSession) -> int:
    result = await db.execute(select(func.max(AuditLog.id)))
    return int(result.scalar_one() or 0) + 1


async def _ensure_super_admin_role(db: AsyncSession) -> Role:
    result = await db.execute(select(Role).where(Role.name == SUPER_ADMIN_ROLE_NAME))
    role = result.scalar_one_or_none()
    if role:
        return role
    role = Role(
        name=SUPER_ADMIN_ROLE_NAME,
        display_name="超级管理员",
        description="系统超级管理员",
        is_system=True,
    )
    db.add(role)
    await db.flush()
    return role


async def _ensure_admin_role(db: AsyncSession) -> Role:
    result = await db.execute(select(Role).where(Role.name == ADMIN_ROLE_NAME))
    role = result.scalar_one_or_none()
    if role:
        return role
    role = Role(
        name=ADMIN_ROLE_NAME,
        display_name="普通管理员",
        description="默认运营管理员",
        is_system=True,
    )
    db.add(role)
    await db.flush()
    return role


async def _ensure_permissions(db: AsyncSession) -> list[Permission]:
    names = [item["name"] for item in ADMIN_PERMISSION_DEFINITIONS]
    result = await db.execute(select(Permission).where(Permission.name.in_(names)))
    existing = {permission.name: permission for permission in result.scalars().all()}

    for item in ADMIN_PERMISSION_DEFINITIONS:
        if item["name"] in existing:
            continue
        permission = Permission(**item)
        db.add(permission)
        existing[item["name"]] = permission

    await db.flush()
    return [existing[name] for name in names]


async def _ensure_role_permissions(db: AsyncSession, role_id: int, permission_ids: list[int]) -> None:
    result = await db.execute(select(RolePermission.permission_id).where(RolePermission.role_id == role_id))
    existing_ids = set(result.scalars().all())
    for permission_id in permission_ids:
        if permission_id not in existing_ids:
            db.add(RolePermission(role_id=role_id, permission_id=permission_id, granted_by=None))
    await db.flush()


async def _ensure_admin_user(db: AsyncSession, role_id: int) -> AdminUser | None:
    result = await db.execute(select(AdminUser).where(AdminUser.username == DEV_ADMIN_USERNAME))
    admin_user = result.scalar_one_or_none()
    if admin_user:
        return None

    admin_user = AdminUser(
        username=DEV_ADMIN_USERNAME,
        password_hash=hash_admin_password(DEV_ADMIN_PASSWORD),
        display_name="开发超管",
        email=None,
        is_active=True,
        role_id=role_id,
    )
    db.add(admin_user)
    await db.flush()
    return admin_user

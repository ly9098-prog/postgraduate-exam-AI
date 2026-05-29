from app.api.v1.admin_audit_logs import router as admin_audit_logs_router
from app.api.v1.admin_auth import router as admin_auth_router
from app.api.v1.admin_dashboard import router as admin_dashboard_router
from app.api.v1.admin_health import router as admin_health_router
from app.api.v1.admin_rbac import router as admin_rbac_router

__all__ = [
    "admin_audit_logs_router",
    "admin_auth_router",
    "admin_dashboard_router",
    "admin_health_router",
    "admin_rbac_router",
]

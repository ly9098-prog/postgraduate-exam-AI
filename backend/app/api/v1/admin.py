from app.api.v1.admin_auth import router as admin_auth_router
from app.api.v1.admin_health import router as admin_health_router
from app.api.v1.admin_rbac import router as admin_rbac_router

__all__ = ["admin_auth_router", "admin_health_router", "admin_rbac_router"]

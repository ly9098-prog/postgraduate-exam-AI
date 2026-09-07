"""Admin API router aggregation — all /api/admin/v1/... routes."""

from fastapi import APIRouter

from app.api.v1.admin_ai_config import router as admin_ai_config_router
from app.api.v1.admin_ai_settings import router as admin_ai_settings_router
from app.api.v1.admin_app_users import router as admin_app_users_router
from app.api.v1.admin_audit_logs import router as admin_audit_logs_router
from app.api.v1.admin_auth import router as admin_auth_router
from app.api.v1.admin_dashboard import router as admin_dashboard_router
from app.api.v1.admin_exams import router as admin_exams_router
from app.api.v1.admin_formulas import router as admin_formulas_router
from app.api.v1.admin_health import router as admin_health_router
from app.api.v1.admin_imports import router as admin_imports_router
from app.api.v1.admin_knowledge import router as admin_knowledge_router
from app.api.v1.admin_metadata import router as admin_metadata_router
from app.api.v1.admin_questions import router as admin_questions_router
from app.api.v1.admin_rbac import router as admin_rbac_router
from app.api.v1.admin_recommendation import router as admin_recommendation_router
from app.api.v1.admin_subjects import router as admin_subjects_router
from app.api.v1.admin_syllabus import router as admin_syllabus_router
from app.api.v1.admin_system_health import router as admin_system_health_router
from app.api.v1.admin_tasks import router as admin_tasks_router
from app.api.v1.admin_users import router as admin_users_router
from app.api.v1.admin_vector_config import router as admin_vector_config_router
from app.api.v1.admin_watermark_rules import router as admin_watermark_rules_router

admin_api_router = APIRouter()

admin_api_router.include_router(admin_auth_router)
admin_api_router.include_router(admin_ai_settings_router)
admin_api_router.include_router(admin_app_users_router)
admin_api_router.include_router(admin_audit_logs_router)
admin_api_router.include_router(admin_dashboard_router)
admin_api_router.include_router(admin_exams_router)
admin_api_router.include_router(admin_health_router)
admin_api_router.include_router(admin_imports_router)
admin_api_router.include_router(admin_questions_router)
admin_api_router.include_router(admin_rbac_router)
admin_api_router.include_router(admin_subjects_router)
admin_api_router.include_router(admin_syllabus_router)
admin_api_router.include_router(admin_users_router)
admin_api_router.include_router(admin_watermark_rules_router)
admin_api_router.include_router(admin_ai_config_router)
admin_api_router.include_router(admin_system_health_router)
admin_api_router.include_router(admin_tasks_router)
admin_api_router.include_router(admin_knowledge_router)
admin_api_router.include_router(admin_recommendation_router)
admin_api_router.include_router(admin_formulas_router)
admin_api_router.include_router(admin_metadata_router)
admin_api_router.include_router(admin_vector_config_router)

__all__ = ["admin_api_router"]

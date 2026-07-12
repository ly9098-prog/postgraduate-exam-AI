"""Public API router aggregation — all /api/v1/... routes."""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.questions import router as questions_router
from app.api.v1.practice import router as practice_router
from app.api.v1.wrong_questions import router as wrong_questions_router
from app.api.v1.ai import router as ai_router
from app.api.v1.rag import router as rag_router
from app.api.v1.imports import router as imports_router
from app.api.v1.behavior import router as behavior_router
from app.api.v1.review import router as review_router
from app.api.v1.stats import router as stats_router
from app.api.v1.knowledge_points import router as knowledge_points_router
from app.api.v1.ai_import import router as ai_import_router
from app.api.v1.cache import router as cache_router
from app.api.v1.health import router as health_router
from app.api.v1.pomodoro import router as pomodoro_router
from app.api.v1.sync import router as sync_router
from app.api.v1.knowledge_mastery import router as knowledge_mastery_router
from app.api.v1.knowledge_path import router as knowledge_path_router
from app.api.v1.study_report import router as study_report_router
from app.api.v1.adaptive_learning import router as adaptive_learning_router
from app.api.v1.formulas import router as formulas_router

public_api_router = APIRouter()

public_api_router.include_router(auth_router)
public_api_router.include_router(questions_router)
public_api_router.include_router(practice_router)
public_api_router.include_router(wrong_questions_router)
public_api_router.include_router(ai_router)
public_api_router.include_router(rag_router)
public_api_router.include_router(imports_router)
public_api_router.include_router(behavior_router)
public_api_router.include_router(review_router)
public_api_router.include_router(stats_router)
public_api_router.include_router(knowledge_points_router)
public_api_router.include_router(ai_import_router)
public_api_router.include_router(cache_router)
public_api_router.include_router(health_router)
public_api_router.include_router(pomodoro_router)
public_api_router.include_router(sync_router)
public_api_router.include_router(knowledge_mastery_router)
public_api_router.include_router(knowledge_path_router)
public_api_router.include_router(study_report_router)
public_api_router.include_router(adaptive_learning_router)
public_api_router.include_router(formulas_router)

__all__ = ["public_api_router"]

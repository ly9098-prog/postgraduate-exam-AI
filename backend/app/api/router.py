"""Top-level API router — aggregates public, admin, and internal routers."""

from fastapi import APIRouter

from app.api.v1.router import public_api_router
from app.api.admin.router import admin_api_router
from app.api.internal.ocr_worker import router as ocr_worker_router

api_router = APIRouter()

api_router.include_router(public_api_router)
api_router.include_router(admin_api_router)
api_router.include_router(ocr_worker_router)

__all__ = ["api_router"]

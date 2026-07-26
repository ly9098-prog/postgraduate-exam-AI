"""Public/Admin pipeline equivalence — both endpoints expose the same import pipeline concept."""

from __future__ import annotations

import pytest


class TestPublicAdminImportModules:
    """Verify both import API modules are importable and structurally equivalent."""

    def test_public_imports_module_exists(self):
        """app.api.v1.imports is importable."""
        try:
            import app.api.v1.imports  # noqa: F401
        except ImportError as e:
            pytest.fail(f"app.api.v1.imports not importable: {e}")

    def test_admin_imports_module_exists(self):
        """app.api.v1.admin_imports is importable."""
        try:
            import app.api.v1.admin_imports  # noqa: F401
        except ImportError as e:
            pytest.fail(f"app.api.v1.admin_imports not importable: {e}")

    def test_both_import_start_import_pipeline(self):
        """Both public and admin import modules expose start_import_pipeline concept."""
        import app.api.v1.admin_imports as admin_imports
        import app.api.v1.imports as public_imports

        # The public imports module imports start_import_pipeline from the service
        assert hasattr(public_imports, "svc_start_import_pipeline")
        # The admin imports module also imports start_import_pipeline from the service
        assert hasattr(admin_imports, "svc_start_import_pipeline")

    def test_both_modules_have_router(self):
        """Both modules define an APIRouter for their endpoints."""
        import app.api.v1.admin_imports as admin_imports
        import app.api.v1.imports as public_imports

        assert hasattr(public_imports, "router"), "public imports missing router"
        assert hasattr(admin_imports, "router"), "admin imports missing router"

        from fastapi import APIRouter
        assert isinstance(public_imports.router, APIRouter)
        assert isinstance(admin_imports.router, APIRouter)

    def test_import_service_same_source(self):
        """Both modules import start_import_pipeline from the same service."""
        import app.api.v1.admin_imports as ai
        import app.api.v1.imports as pi

        # Verify both reference the same import source
        assert pi.svc_start_import_pipeline is not None
        assert ai.svc_start_import_pipeline is not None

        # They should be the same function object from import_pipeline_service
        from app.services.import_pipeline_service import (
            start_import_pipeline as svc_fn,
        )
        assert pi.svc_start_import_pipeline is svc_fn
        assert ai.svc_start_import_pipeline is svc_fn

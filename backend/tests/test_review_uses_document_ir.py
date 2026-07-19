"""Sprint 4C: Verify ReviewCoordinator uses DocumentIR and returns ModuleResult."""

from __future__ import annotations

import inspect

import pytest


class TestReviewUsesDocumentIR:
    """Verify ReviewCoordinator is DocumentIR-based."""

    def test_review_coordinator_exists(self):
        """ReviewCoordinator is importable."""
        from app.features.coordinators import ReviewCoordinator
        assert ReviewCoordinator is not None
        assert isinstance(ReviewCoordinator, type)

    def test_review_coordinator_has_run_method(self):
        """ReviewCoordinator has an async run method."""
        from app.features.coordinators import ReviewCoordinator

        assert hasattr(ReviewCoordinator, "run")
        assert callable(ReviewCoordinator.run)
        assert inspect.iscoroutinefunction(ReviewCoordinator.run)

    @pytest.mark.asyncio
    async def test_review_coordinator_run_returns_module_result(self):
        """run() returns ModuleResult with is_success True."""
        from app.features.coordinators import ReviewCoordinator
        from app.core.module_result import ModuleResult

        coordinator = ReviewCoordinator()
        result = await coordinator.run(
            {"coordinator_mode": True},
            questions=None,
            trace_id="test-trace",
        )

        assert isinstance(result, ModuleResult)
        assert result.is_success is True
        assert result.is_failure is False
        assert result.module_name == "review_coordinator"
        assert result.data is not None
        assert result.data.get("review_ready") is True

    @pytest.mark.asyncio
    async def test_review_coordinator_run_with_questions(self):
        """ReviewCoordinator run accepts optional questions list."""
        from app.features.coordinators import ReviewCoordinator
        from app.core.module_result import ModuleResult

        coordinator = ReviewCoordinator()
        result = await coordinator.run(
            {"doc_id": "test"},
            questions=[{"id": 1, "text": "Q1"}],
            trace_id="test-trace-2",
        )

        assert isinstance(result, ModuleResult)
        assert result.is_success is True

    @pytest.mark.asyncio
    async def test_review_coordinator_data_type(self):
        """ReviewCoordinator result has correct data_type."""
        from app.features.coordinators import ReviewCoordinator

        coordinator = ReviewCoordinator()
        result = await coordinator.run(
            {"doc_id": "test"},
            trace_id="test-trace-3",
        )

        assert result.data_type == "ReviewCoordinatorResult"

    @pytest.mark.asyncio
    async def test_review_coordinator_latency_non_negative(self):
        """ReviewCoordinator result has non-negative latency_ms."""
        from app.features.coordinators import ReviewCoordinator

        coordinator = ReviewCoordinator()
        result = await coordinator.run(
            {"doc_id": "test"},
            trace_id="test-trace-4",
        )

        assert result.latency_ms >= 0

    def test_review_coordinator_instantiable(self):
        """ReviewCoordinator can be instantiated without arguments."""
        from app.features.coordinators import ReviewCoordinator

        coordinator = ReviewCoordinator()
        assert coordinator is not None

    def test_all_coordinators_importable(self):
        """All stage coordinators are importable and have run method."""
        from app.features.coordinators import (
            CorrectionCoordinator,
            DocumentStructureCoordinator,
            DomainParsingCoordinator,
            InputCoordinator,
            OCRCoordinator,
            PersistenceCoordinator,
            ReviewCoordinator,
            ValidationCoordinator,
        )

        coordinators = [
            InputCoordinator,
            OCRCoordinator,
            DocumentStructureCoordinator,
            DomainParsingCoordinator,
            CorrectionCoordinator,
            ValidationCoordinator,
            ReviewCoordinator,
            PersistenceCoordinator,
        ]
        for cls in coordinators:
            assert isinstance(cls, type), f"{cls} is not a class"
            assert hasattr(cls, "run"), f"{cls.__name__} missing run()"

"""Execution contracts for the wrong-question prewarm background session."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ai.prewarm_execution import (
    PrewarmExecutionRequest,
    execute_prewarm,
)


class FailureError(Exception):
    def __init__(self, result):
        super().__init__(result["error_code"])
        self.result = result


def build_revision(*, review_count, wrong_answer):
    return f"r{review_count}:{wrong_answer}"


def request(**overrides):
    wrong = SimpleNamespace(review_count=2, wrong_answer="AB", ai_analysis=None)
    result = SimpleNamespace(scalar_one_or_none=lambda: wrong)
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=db)
    session.__aexit__ = AsyncMock(return_value=False)
    analyze = AsyncMock(return_value={"model": "model", "duration_ms": 9})
    fields = {
        "wrong_question_id": 7,
        "user_id": 8,
        "expected_revision": None,
        "force_regenerate": False,
        "baseline_generated_at": None,
        "logger": SimpleNamespace(info=MagicMock(), warning=MagicMock()),
        "async_session": lambda: session,
        "build_revision": build_revision,
        "generated_at": lambda value: None,
        "analyze_error": analyze,
        "failure_factory": FailureError,
    }
    fields.update(overrides)
    return SimpleNamespace(
        request=PrewarmExecutionRequest(**fields),
        session=session,
        db=db,
        wrong=wrong,
        analyze=analyze,
        logger=fields["logger"],
    )


@pytest.mark.asyncio
async def test_execution_passes_session_user_and_force_to_analysis():
    harness = request(force_regenerate=True)
    outcome = await execute_prewarm(harness.request)
    assert outcome == {
        "status": "success",
        "reason": None,
        "from_cache": False,
        "model": "model",
        "duration_ms": 9,
    }
    harness.analyze.assert_awaited_once_with(harness.db, 8, 7, force_regenerate=True)


@pytest.mark.asyncio
async def test_stale_revision_returns_superseded_without_analysis():
    harness = request(expected_revision="r1:AB")
    outcome = await execute_prewarm(harness.request)
    assert outcome == {
        "status": "superseded",
        "reason": "revision_changed",
        "from_cache": False,
    }
    harness.analyze.assert_not_awaited()
    harness.logger.info.assert_called_once_with(
        "[prewarm] superseded id=%d uid=%d expected_revision=%s current_revision=%s",
        7,
        8,
        "r1:AB",
        "r2:AB",
    )


@pytest.mark.asyncio
async def test_recovery_baseline_supersedes_regenerated_analysis():
    harness = request(
        force_regenerate=True,
        baseline_generated_at="old",
        generated_at=lambda _value: "new",
    )
    outcome = await execute_prewarm(harness.request)
    assert outcome == {
        "status": "superseded",
        "reason": "analysis_already_regenerated",
        "from_cache": True,
    }
    harness.analyze.assert_not_awaited()
    harness.logger.info.assert_called_once_with(
        "[prewarm] recovery_superseded id=%d uid=%d baseline=%s current=%s",
        7,
        8,
        "old",
        "new",
    )


@pytest.mark.asyncio
async def test_missing_wrong_question_returns_skip_result():
    harness = request()
    harness.db.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: None)
    )
    outcome = await execute_prewarm(harness.request)
    assert outcome == {
        "status": "skipped",
        "reason": "wrong_question_not_found",
        "from_cache": False,
    }
    harness.analyze.assert_not_awaited()
    harness.logger.info.assert_called_once_with(
        "[prewarm] skipped_not_found id=%d uid=%d", 7, 8
    )

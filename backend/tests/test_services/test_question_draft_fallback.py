"""The real draft generator must log fallback without publishing any question."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import app.models  # noqa: F401
from app.features import question_pipeline
from app.features.question_draft_generator import generate_drafts
from app.models.ai_generation_log import AiGenerationLog


@pytest.mark.asyncio
async def test_generation_fallback_only_adds_failure_audit_and_commits(monkeypatch):
    db = SimpleNamespace(add=Mock(), commit=AsyncMock())
    fallback_value = {"questions": []}
    call = AsyncMock(return_value=(
        {"fallback_value": fallback_value, "model": "fallback", "error": "unavailable"},
        None, None,
    ))
    monkeypatch.setattr(question_pipeline, "_call_or_fallback", call)

    result = await generate_drafts(
        db, 17, subject_code="data_structure", knowledge_points=["stack"], count=2,
    )

    assert result["generated"] == 0
    assert result["from_fallback"] is True
    assert result["batch_id"].startswith("AIGEN_")
    call.assert_awaited_once()
    assert call.call_args.args[2] is db
    db.add.assert_called_once()
    log = db.add.call_args.args[0]
    assert isinstance(log, AiGenerationLog)
    assert (log.user_id, log.action, log.success) == (17, "generate", 0)
    assert log.parsed_result == fallback_value
    assert log.error_message == "unavailable"
    db.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_generation_invalid_subject_does_not_call_ai_or_write(monkeypatch):
    db = SimpleNamespace(add=Mock(), commit=AsyncMock())
    call = AsyncMock()
    monkeypatch.setattr(question_pipeline, "_call_or_fallback", call)

    with pytest.raises(ValueError, match="canonical subject code"):
        await generate_drafts(
            db, 17, subject_code="unsupported-subject", knowledge_points=["stack"],
        )

    call.assert_not_awaited()
    db.add.assert_not_called()
    db.commit.assert_not_awaited()

"""Post-commit health probes must preserve the Admin save contract."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.v1 import admin_ai_config
from app.schemas.admin_ai_config import AdminAiModelConfigPatchRequest
from app.services.ai import analysis_admin_health


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch,should_probe",
    [
        ({"api_key": "synthetic-key"}, True),
        ({"name": "synthetic-model"}, True),
        ({"api_base_url": "https://model.invalid/v1"}, True),
        ({"features": ["analysis"]}, True),
        ({"is_enabled": False}, True),
        ({"display_name": "New label"}, False),
        ({}, False),
    ],
)
async def test_model_update_probes_relevant_changes_after_commit(
    monkeypatch, patch, should_probe
):
    events = []
    saved = object()
    db = SimpleNamespace(
        commit=AsyncMock(side_effect=lambda: events.append("commit")),
        rollback=AsyncMock(),
    )
    data = AdminAiModelConfigPatchRequest(**patch)
    admin = object()
    patch_model = AsyncMock(return_value=saved)
    probe = AsyncMock(side_effect=lambda *_: events.append("probe"))
    monkeypatch.setattr(admin_ai_config, "patch_model", patch_model)
    monkeypatch.setattr(admin_ai_config, "probe_saved_model", probe)

    result = await admin_ai_config.update_model(11, data, None, admin, db)

    assert result is saved
    patch_model.assert_awaited_once_with(db, 11, data, admin)
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()
    assert events == (["commit", "probe"] if should_probe else ["commit"])
    if should_probe:
        probe.assert_awaited_once_with(db, 11)
    else:
        probe.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_commit_probe_failure_does_not_fail_model_update(
    monkeypatch, caplog
):
    saved = object()
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    monkeypatch.setattr(admin_ai_config, "patch_model", AsyncMock(return_value=saved))
    monkeypatch.setattr(
        analysis_admin_health,
        "saved_runtime",
        AsyncMock(side_effect=RuntimeError("synthetic lookup failure")),
    )

    result = await admin_ai_config.update_model(
        11, AdminAiModelConfigPatchRequest(is_default=True), None, object(), db
    )

    assert result is saved
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()
    assert "ai.analysis.admin_probe_failed model_config_id=11" in caplog.text

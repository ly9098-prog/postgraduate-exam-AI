from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1 import wrong_questions as api


@pytest.mark.asyncio
async def test_wrong_question_update_invalidates_user_statistics(monkeypatch):
    wrong_question = SimpleNamespace(id=11)
    monkeypatch.setattr(
        api.svc,
        "update_wrong",
        AsyncMock(return_value=wrong_question),
    )
    monkeypatch.setattr(
        api,
        "_load_current_question_view",
        AsyncMock(return_value=(None, [])),
    )
    monkeypatch.setattr(
        api,
        "_enrich_single_wq_extra",
        AsyncMock(return_value={"extra": True}),
    )
    monkeypatch.setattr(
        api,
        "enrich_wq",
        MagicMock(return_value={"id": 11}),
    )
    delete = AsyncMock()
    monkeypatch.setattr(api.cache, "delete", delete)

    result = await api.update_wrong(
        11,
        SimpleNamespace(error_type="concept"),
        object(),
        SimpleNamespace(id=7),
    )

    assert result == {"id": 11}
    assert [call.args[0] for call in delete.await_args_list] == [
        "wrong_questions:*:7*",
        "stats:*:7*",
    ]


@pytest.mark.asyncio
async def test_missing_wrong_question_does_not_invalidate_cache(monkeypatch):
    monkeypatch.setattr(api.svc, "update_wrong", AsyncMock(return_value=None))
    delete = AsyncMock()
    monkeypatch.setattr(api.cache, "delete", delete)

    with pytest.raises(HTTPException) as exc_info:
        await api.update_wrong(
            999,
            SimpleNamespace(error_type="concept"),
            object(),
            SimpleNamespace(id=7),
        )

    assert exc_info.value.status_code == 404
    delete.assert_not_awaited()

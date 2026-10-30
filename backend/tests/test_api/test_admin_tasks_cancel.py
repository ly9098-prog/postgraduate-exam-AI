"""Admin cancel_task must always return its pooled Redis client."""

import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.v1 import admin_tasks
from app.core.error_codes import ApiError, ErrorCode
from app.services import task_queue_service


def _client(hgetall):
    client = AsyncMock()
    client.hgetall = hgetall
    return client


@pytest.fixture
def patch_client(monkeypatch):
    def _apply(client):
        monkeypatch.setattr(
            admin_tasks, "_get_redis_client", AsyncMock(return_value=client)
        )
        return client

    return _apply


@pytest.mark.asyncio
async def test_cancel_closes_client_when_hgetall_raises(patch_client):
    client = patch_client(_client(AsyncMock(side_effect=RuntimeError("redis down"))))

    with pytest.raises(RuntimeError):
        await admin_tasks.cancel_task("t1", None)

    assert client.aclose.await_count == 1


@pytest.fixture
def cancel_v2(monkeypatch):
    mock = AsyncMock(return_value=1)
    monkeypatch.setattr(task_queue_service.task_queue, "cancel_v2", mock)
    return mock


def _task_hash(task_type):
    return {"data": json.dumps({"task_type": task_type})}


@pytest.mark.asyncio
async def test_cancel_closes_client_once_on_missing_task(patch_client, cancel_v2):
    client = patch_client(_client(AsyncMock(return_value={})))

    with pytest.raises(ApiError) as exc:
        await admin_tasks.cancel_task("t1", None)

    assert exc.value.code == ErrorCode.TASK_NOT_FOUND
    assert client.aclose.await_count == 1
    cancel_v2.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_rejects_hash_without_task_type(patch_client, cancel_v2):
    client = patch_client(_client(AsyncMock(return_value=_task_hash(""))))

    with pytest.raises(HTTPException) as exc:
        await admin_tasks.cancel_task("t1", None)

    assert exc.value.status_code == 400
    assert client.aclose.await_count == 1
    cancel_v2.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "outcome"), [(2, True), (0, 400), (99, 500)])
async def test_cancel_result_codes_unchanged(patch_client, cancel_v2, code, outcome):
    patch_client(_client(AsyncMock(return_value=_task_hash("import_pipeline"))))
    cancel_v2.return_value = code

    if outcome is True:
        result = await admin_tasks.cancel_task("t1", None)
        assert result.success is True
        return
    with pytest.raises(HTTPException) as exc:
        await admin_tasks.cancel_task("t1", None)
    assert exc.value.status_code == outcome


@pytest.mark.asyncio
async def test_cancel_closes_client_before_cancel_v2(patch_client, monkeypatch):
    client = patch_client(
        _client(
            AsyncMock(
                return_value={"data": json.dumps({"task_type": "import_pipeline"})}
            )
        )
    )
    order = []
    client.aclose.side_effect = lambda: order.append("aclose")

    async def fake_cancel(task_id, task_type, reason):
        order.append(("cancel_v2", task_id, task_type))
        return 1

    monkeypatch.setattr(task_queue_service.task_queue, "cancel_v2", fake_cancel)

    result = await admin_tasks.cancel_task("t1", None)

    assert result.success is True
    assert order == ["aclose", ("cancel_v2", "t1", "import_pipeline")]

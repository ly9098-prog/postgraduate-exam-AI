"""Compatibility baseline for v1 failure Redis execution."""

from __future__ import annotations

import pytest

from app.services.task_queue_contract import Task
from app.services.task_queue_v1_fail_redis_contract import (
    execute_v1_fail_dead,
    execute_v1_fail_retry,
)


class FakeClient:
    def __init__(self, result):
        self.result = result
        self.closed = False

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_retry_execution_closes_client_and_reports_rejection():
    client = FakeClient(result=0)
    metrics = {"owner_fencing_rejected": 0}
    task = Task(
        task_id="task-1",
        task_type="demo",
        payload={},
        owner_token="owner",
        retry_count=1,
    )

    async def get_client():
        return client

    async def load_scripts(_client):
        return None

    async def evalsha(_client, *_args, **_kwargs):
        return client.result

    accepted = await execute_v1_fail_retry(
        get_client,
        load_scripts,
        evalsha,
        task,
        "task-1",
        "demo",
        "owner",
        10,
        "temporary",
        metrics,
    )

    assert accepted is False
    assert metrics["owner_fencing_rejected"] == 1
    assert client.closed is True


@pytest.mark.asyncio
async def test_dead_execution_closes_client_on_success():
    client = FakeClient(result=1)
    metrics = {"owner_fencing_rejected": 0}

    async def get_client():
        return client

    async def load_scripts(_client):
        return None

    async def evalsha(_client, *_args, **_kwargs):
        return client.result

    accepted = await execute_v1_fail_dead(
        get_client,
        load_scripts,
        evalsha,
        "task-1",
        "task-1",
        "demo",
        "owner",
        "fatal",
        metrics,
    )

    assert accepted is True
    assert metrics["owner_fencing_rejected"] == 0
    assert client.closed is True


@pytest.mark.asyncio
async def test_failure_execution_requires_a_client():
    async def get_client():
        return None

    assert await execute_v1_fail_retry(
        get_client, lambda _client: None, lambda *_args: None, Task(
            task_id="task-1", task_type="demo", payload={}
        ), "task-1", "demo", None, 10, "temporary", {}
    ) is False
    assert await execute_v1_fail_dead(
        get_client, lambda _client: None, lambda *_args: None, "task-1",
        "task-1", "demo", None, "fatal", {},
    ) is False

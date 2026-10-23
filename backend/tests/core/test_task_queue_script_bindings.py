from __future__ import annotations

import pytest
from redis.exceptions import NoScriptError

from app.services import task_queue_script_bindings as bindings
from app.services.task_queue_service import DurableTaskQueue


class _FakeScriptClient:
    def __init__(self) -> None:
        self.loaded: list[str] = []
        self.eval_calls: list[tuple[str, int, tuple[object, ...]]] = []
        self.fail_first_eval = False

    async def script_load(self, script: str) -> str:
        self.loaded.append(script)
        return f"sha-{len(self.loaded)}"

    async def evalsha(self, sha: str, num_keys: int, *args) -> str:
        self.eval_calls.append((sha, num_keys, args))
        if self.fail_first_eval:
            self.fail_first_eval = False
            raise NoScriptError("synthetic flush")
        return "ok"


@pytest.mark.asyncio
async def test_load_scripts_preserves_manifest_order_and_is_idempotent():
    client = _FakeScriptClient()
    queue = DurableTaskQueue(redis_url="redis://unused")

    await queue._load_scripts(client)
    first_loaded = list(client.loaded)
    await queue._load_scripts(client)

    assert first_loaded == [script for _, script in bindings.SCRIPT_BINDINGS]
    assert client.loaded == first_loaded
    assert [
        getattr(queue, attribute) for attribute, _ in bindings.SCRIPT_BINDINGS
    ] == [f"sha-{index}" for index in range(1, len(bindings.SCRIPT_BINDINGS) + 1)]


@pytest.mark.asyncio
async def test_noscript_reloads_every_binding_before_retry():
    client = _FakeScriptClient()
    queue = DurableTaskQueue(redis_url="redis://unused")
    await queue._load_scripts(client)
    client.fail_first_eval = True

    result = await queue._evalsha_or_reload(
        client,
        "_lua_enqueue",
        1,
        "taskq:queue:test",
        "payload",
    )

    assert result == "ok"
    assert len(client.loaded) == len(bindings.SCRIPT_BINDINGS) * 2
    assert [call[0] for call in client.eval_calls] == ["sha-1", "sha-21"]

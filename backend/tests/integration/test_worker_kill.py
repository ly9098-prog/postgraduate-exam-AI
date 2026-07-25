"""Worker kill integration test — fencing + recovery verification.

Connects to production Redis + PostgreSQL.
Uses an isolated queue suffix to avoid production interference.

Run:  REDIS_URL=redis://... DATABASE_URL=postgresql+asyncpg://... \\
      python -m pytest tests/integration/test_worker_kill.py -x -v --run-integration
"""
from __future__ import annotations

import asyncio
import os
import time

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("REDIS_URL"),
        reason="Requires REDIS_URL",
    ),
]


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL")
    if not url:
        pytest.skip("REDIS_URL not set")
    return url


@pytest.fixture
def test_suffix() -> str:
    return f"killtest_{time.time_ns()}"


@pytest.mark.asyncio
async def test_claim_and_fencing(test_suffix: str):
    """Worker A claims → heartbeat lost → Worker B reclaims → fencing enforced."""
    import redis.asyncio as redis_async

    url = _redis_url()
    redis = redis_async.from_url(url, decode_responses=True)
    sid = test_suffix

    queue_key = f"taskq:queue:{sid}"
    processing_key = f"taskq:processing:{sid}"
    heartbeat_key = f"taskq:heartbeat:{sid}:test_task"
    task_hash_key = f"taskq:task:{sid}:test_task"
    lease_sec = 5

    try:
        # 1. Enqueue test task
        import json
        await redis.hset(task_hash_key, mapping={
            "payload": json.dumps({"test": True}),
            "status": "pending",
            "task_type": "test_kill",
        })
        await redis.lpush(queue_key, "test_task")
        print("[setup] task enqueued")

        # 2. Worker A claims: RPOP from queue → ZADD processing → SETEX heartbeat
        claimed = await redis.rpop(queue_key)
        assert claimed == "test_task", "Worker A should claim the task"
        await redis.zadd(processing_key, {"test_task": time.time() + lease_sec})
        await redis.setex(heartbeat_key, lease_sec, "worker_a_token")
        assert await redis.get(heartbeat_key) == "worker_a_token"
        print("[worker_a] claimed + heartbeat set")

        # 3. Simulate SIGKILL: delete heartbeat key
        await redis.delete(heartbeat_key)
        print("[kill] worker_a heartbeat deleted (SIGKILL)")

        # 4. Wait for lease to expire
        await asyncio.sleep(lease_sec + 0.5)

        # Verify task is expired in processing set
        score = await redis.zscore(processing_key, "test_task")
        assert score is not None, "Task still in processing set"
        assert score < time.time(), "Lease expired"
        print("[expiry] lease expired, task available for reclaim")

        # 5. Worker B recovers: remove from processing → re-enqueue → claim
        await redis.zrem(processing_key, "test_task")
        await redis.lpush(queue_key, "test_task")
        claimed2 = await redis.rpop(queue_key)
        assert claimed2 == "test_task", "Worker B should reclaim"
        await redis.setex(heartbeat_key, lease_sec, "worker_b_token")
        assert await redis.get(heartbeat_key) == "worker_b_token"
        print("[worker_b] reclaimed + heartbeat set")

        # 6. Fencing test: Worker A's operations should be rejected
        # Load the fencing check Lua script
        fencing_lua = """
        local task_id = KEYS[1]
        local caller_token = ARGV[1]
        local stored = redis.call('GET', 'taskq:heartbeat:' .. task_id)
        if stored ~= caller_token then
            return 0  -- fenced
        end
        return 1  -- accepted
        """
        lua_hash = await redis.script_load(fencing_lua)

        # Worker A tries to complete → rejected
        complete_a = await redis.evalsha(lua_hash, 1, f"{sid}:test_task", "worker_a_token")
        assert complete_a == 0, "Worker A's write should be fenced"
        print("[fencing] worker_a write REJECTED (expected)")

        # Worker B completes → accepted
        complete_b = await redis.evalsha(lua_hash, 1, f"{sid}:test_task", "worker_b_token")
        assert complete_b == 1, "Worker B's write should be accepted"
        print("[fencing] worker_b write ACCEPTED (expected)")

        print("\n=== PASS: worker kill + fencing verification ===\n")

    finally:
        # Cleanup: remove all test keys
        cursor = 0
        pattern = f"taskq:*:{sid}*"
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=200)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break
        await redis.aclose()

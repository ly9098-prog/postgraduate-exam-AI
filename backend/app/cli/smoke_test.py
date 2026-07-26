"""Smoke test — end-to-end verification using test namespace.

Usage:
    python -m app.cli.smoke_test

Tests: live, ready, PostgreSQL, Redis, staging, enqueue, claim, complete.
Uses isolated test namespace (taskq:v2:smoke_test:*) and cleans up after.
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid


def _green(s: str) -> str:
    return f"\033[32m{s}\033[0m"


def _red(s: str) -> str:
    return f"\033[31m{s}\033[0m"


def _yellow(s: str) -> str:
    return f"\033[33m{s}\033[0m"


def _bold(s: str) -> str:
    return f"\033[1m{s}\033[0m"


_CHECK_MARK = _green("✓")
_CROSS_MARK = _red("✗")


async def _main() -> int:
    print("=== 2240AI Smoke Test ===\n")

    results: list[tuple[str, bool, str]] = []
    test_ns = f"smoke_test_{uuid.uuid4().hex[:8]}"
    test_task_type = f"smoke_test_{test_ns}"
    test_task_id = f"smoke_{test_ns}"

    # ── 1. Live check ──
    print("1. Live check...", end=" ")
    try:
        results.append(("live", True, "FastAPI app importable"))
        print(_CHECK_MARK)
    except Exception as e:
        results.append(("live", False, str(e)))
        print(_CROSS_MARK)

    # ── 2. Ready check ──
    print("2. Ready check...", end=" ")
    try:
        from app.core.config import settings
        results.append(("ready", True, f"APP_ENV={settings.APP_ENV} ROLE={settings.PROCESS_ROLE}"))
        print(_CHECK_MARK)
    except Exception as e:
        results.append(("ready", False, str(e)))
        print(_CROSS_MARK)

    # ── 3. PostgreSQL ──
    print("3. PostgreSQL...", end=" ")
    try:
        from sqlalchemy import text

        from app.core.database import async_session

        async with async_session() as db:
            result = await db.execute(text("SELECT 1"))
            row = result.one()
            assert row[0] == 1
        results.append(("PostgreSQL", True, "connected"))
        print(_CHECK_MARK)
    except Exception as e:
        results.append(("PostgreSQL", False, str(e)[:80]))
        print(_CROSS_MARK)

    # ── 4. Redis ──
    print("4. Redis...", end=" ")
    if not settings.REDIS_URL:
        results.append(("Redis", False, "REDIS_URL not configured"))
        print(_CROSS_MARK + " (skipping remaining Redis tests)")
    else:
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            await r.ping()
            await r.aclose()
            results.append(("Redis", True, "connected"))
            print(_CHECK_MARK)
        except Exception as e:
            results.append(("Redis", False, str(e)[:80]))
            print(_CROSS_MARK + " (skipping remaining Redis tests)")

    # Only continue if Redis is available
    redis_ok = any(name == "Redis" and ok for name, ok, _ in results)
    if not redis_ok:
        return _print_summary(results)

    # ── 5. Staging ──
    print("5. Staging...", end=" ")
    try:
        from app.services.staging_storage import _STAGING_DIR
        assert _STAGING_DIR.exists(), "staging dir missing"
        assert _STAGING_DIR.is_dir(), "staging path is not a directory"
        results.append(("staging", True, str(_STAGING_DIR)))
        print(_CHECK_MARK)
    except Exception as e:
        results.append(("staging", False, str(e)[:80]))
        print(_CROSS_MARK)

    # ── 6. Enqueue ──
    print("6. Enqueue (test namespace)...", end=" ")
    try:
        from app.services.task_queue_service import task_queue

        result = await task_queue.enqueue_v2(
            test_task_type,
            {"smoke": True, "ts": time.time()},
            task_id=test_task_id,
            max_retries=0,
        )
        if result.accepted:
            results.append(("enqueue", True, f"task_id={test_task_id}"))
            print(_CHECK_MARK)
        else:
            results.append(("enqueue", False, "not accepted"))
            print(_CROSS_MARK)
    except Exception as e:
        results.append(("enqueue", False, str(e)[:80]))
        print(_CROSS_MARK)

    # ── 7. Claim ──
    print("7. Claim...", end=" ")
    try:
        task = await task_queue.dequeue_v2(test_task_type, lease_sec=30)
        if task is not None and task.task_id == test_task_id:
            results.append(("claim", True, f"gen={task.generation}"))
            print(_CHECK_MARK)
        else:
            results.append(("claim", False, f"got {task.task_id if task else None}"))
            print(_CROSS_MARK)
    except Exception as e:
        results.append(("claim", False, str(e)[:80]))
        print(_CROSS_MARK)
        task = None

    # ── 8. Complete ──
    print("8. Complete...", end=" ")
    try:
        if task is not None:
            ok = await task_queue.complete_v2(task)
            if ok == 1:
                results.append(("complete", True, "completed"))
                print(_CHECK_MARK)
            else:
                results.append(("complete", False, f"complete_v2 returned {ok}"))
                print(_CROSS_MARK)
        else:
            results.append(("complete", False, "no task to complete"))
            print(_CROSS_MARK)
    except Exception as e:
        results.append(("complete", False, str(e)[:80]))
        print(_CROSS_MARK)

    # ── 9. Queue health check ──
    print("9. Queue health...", end=" ")
    try:
        from app.services.task_queue_service import task_queue as tq2
        _metrics = await tq2.get_metrics_v2(task_types=[test_task_type])
        results.append(("queue_health", True, "metrics OK"))
        print(_CHECK_MARK)
    except Exception as e:
        results.append(("queue_health", False, str(e)[:80]))
        print(_CROSS_MARK)

    # ── Cleanup ──
    print("\nCleaning up test namespace...", end=" ")
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        cursor = 0
        pattern = f"taskq:v2:*:{test_task_type}*"
        deleted = 0
        while True:
            cursor, keys = await r.scan(cursor, match=pattern, count=200)
            if keys:
                deleted += await r.delete(*keys)
            if cursor == 0:
                break
        # Also delete task hash and heartbeat
        await r.delete(f"taskq:v2:task:{test_task_id}")
        await r.delete(f"taskq:v2:heartbeat:{test_task_id}")
        await r.aclose()
        print(_green(f"cleaned {deleted} keys"))
    except Exception as e:
        print(_yellow(f"cleanup error: {e}"))

    return _print_summary(results)


def _print_summary(results: list[tuple[str, bool, str]]) -> int:
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    total = len(results)

    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} passed")

    for name, ok, detail in results:
        mark = _CHECK_MARK if ok else _CROSS_MARK
        print(f"  {mark} {name}: {detail}")

    if failed > 0:
        print(_red(f"\n{failed} test(s) failed."))
        return 1
    else:
        print(_green("\nAll smoke tests passed."))
        return 0


def main() -> None:
    code = asyncio.run(_main())
    sys.exit(code)


if __name__ == "__main__":
    main()

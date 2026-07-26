"""Task queue status and inspection CLI.

Usage:
    python -m app.cli.task_queue status
    python -m app.cli.task_queue inspect TASK_ID
"""

from __future__ import annotations

import asyncio
import json
import sys

TASK_TYPES = [
    "import_pipeline",
    "image_pipeline",
    "excel_pipeline",
    "resume_pipeline",
    "admin_resume",
    "batch_image",
    "formula_batch",
    "prewarm_analysis",
    "export_mistakes",
]


def _green(s: str) -> str:
    return f"\033[32m{s}\033[0m"


def _red(s: str) -> str:
    return f"\033[31m{s}\033[0m"


def _yellow(s: str) -> str:
    return f"\033[33m{s}\033[0m"


def _bold(s: str) -> str:
    return f"\033[1m{s}\033[0m"


async def _cmd_status() -> int:
    """Show queue status for all task types."""
    from app.services.task_queue_service import task_queue

    print("=== Task Queue Status ===\n")

    totals = {"ready": 0, "processing": 0, "retry": 0, "dead": 0, "corrupt": 0}
    oldest_ready: dict[str, float] = {}

    print(f"{'Task Type':<24} {'Ready':>6} {'Proc':>6} {'Retry':>6} {'Dead':>6} {'Corrupt':>6}")
    print("-" * 60)

    for tt in TASK_TYPES:
        try:
            ready = await task_queue.queue_length_v2(tt)
            proc = await task_queue.processing_length_v2(tt)
            retry = await task_queue.retry_length_v2(tt)
            dead = await task_queue.dead_length_v2(tt)
            corrupt = await task_queue.corrupt_length_v2(tt)

            totals["ready"] += ready
            totals["processing"] += proc
            totals["retry"] += retry
            totals["dead"] += dead
            totals["corrupt"] += corrupt

            line = f"  {tt:<22} {ready:>6} {proc:>6} {retry:>6} {dead:>6} {corrupt:>6}"
            if ready + proc + retry + dead + corrupt > 0:
                print(_bold(line))
            else:
                print(line)

            # Collect oldest ages
            if ready > 0:
                age = await task_queue.oldest_ready_age(tt)
                if age is not None and age > 0:
                    oldest_ready[tt] = age
            if proc > 0:
                # Use queue_length_v2 compatible approach
                pass
        except Exception as e:
            print(f"  {tt:<22} {_red('ERROR'):>6} {'':>6} {'':>6} {'':>6} {'':>6}  {e}")

    print("-" * 60)
    print(f"  {_bold('TOTAL'):<22} {totals['ready']:>6} {totals['processing']:>6} "
          f"{totals['retry']:>6} {totals['dead']:>6} {totals['corrupt']:>6}")

    # Oldest ages
    if oldest_ready:
        print("\nOldest ready tasks:")
        for tt, age in sorted(oldest_ready.items(), key=lambda x: -x[1]):
            print(f"  {tt}: {age:.0f}s")

    # Show processing with oldest age
    print("\nProcessing details:")
    for tt in TASK_TYPES:
        try:
            plen = await task_queue.processing_length_v2(tt)
            if plen > 0:
                print(f"  {tt}: {plen} task(s) in processing")
        except Exception:
            pass

    return 0


async def _cmd_inspect(task_id: str) -> int:
    """Show safe summary of a specific task."""
    import redis.asyncio as aioredis

    from app.core.config import settings
    from app.services.task_queue_service import _v2_task_hash_key

    if not settings.REDIS_URL:
        print(_red("Error: REDIS_URL not configured"))
        return 1

    print(f"=== Task Inspect: {task_id} ===\n")

    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    try:
        hash_key = _v2_task_hash_key(task_id)
        data = await r.hgetall(hash_key)

        if not data:
            print(_red("Task not found."))
            return 1

        # Safe display — don't print full payload/tokens
        print(f"  {_bold('Task Type:')}    {data.get('task_type', 'unknown')}")
        print(f"  {_bold('Status:')}       {data.get('status', 'unknown')}")
        print(f"  {_bold('Generation:')}   {data.get('generation', '0')}")
        print(f"  {_bold('Retries:')}      {data.get('retry_count', '0')}/{data.get('max_retries', '0')}")
        print(f"  {_bold('Error Count:')}  {data.get('error_count', '0')}")

        owner = data.get("owner_token", "")
        if owner:
            print(f"  {_bold('Owner:')}       {owner[:16]}... (truncated)")

        last_error = data.get("last_error", "")
        if last_error:
            print(f"  {_bold('Last Error:')}  {last_error[:200]}")

        # Payload summary (don't print full payload)
        payload_raw = data.get("payload", "")
        if payload_raw:
            try:
                payload = json.loads(payload_raw)
                safe_payload = {k: v for k, v in payload.items()
                                if k not in ("file_content", "token", "secret")}
                payload_str = json.dumps(safe_payload, ensure_ascii=False)
                if len(payload_str) > 300:
                    payload_str = payload_str[:300] + "..."
                print(f"  {_bold('Payload:')}     {payload_str}")
            except json.JSONDecodeError:
                print(f"  {_bold('Payload:')}     (non-JSON, {len(payload_raw)} bytes)")

        # Check where this task is in the queue
        task_type = data.get("task_type", "")
        if task_type:
            print(f"\n  {_bold('Queue Status:')}")
            from app.services.task_queue_service import (
                _v2_corrupt_key,
                _v2_dead_key,
                _v2_heartbeat_key,
                _v2_p_key,
                _v2_q_key,
                _v2_retry_key,
            )

            in_ready = await r.lpos(_v2_q_key(task_type), task_id) is not None if task_type else False
            in_proc = await r.zscore(_v2_p_key(task_type), task_id) is not None if task_type else False
            in_retry = await r.zscore(_v2_retry_key(task_type), task_id) is not None if task_type else False
            in_dead = await r.lpos(_v2_dead_key(task_type), task_id) is not None if task_type else False
            in_corrupt = await r.zscore(_v2_corrupt_key(task_type), task_id) is not None if task_type else False

            hb = await r.get(_v2_heartbeat_key(task_id))

            print(f"    ready:      {_green('yes') if in_ready else 'no'}")
            print(f"    processing: {_green('yes') if in_proc else 'no'}")
            print(f"    retry:      {_yellow('yes') if in_retry else 'no'}")
            print(f"    dead:       {_red('yes') if in_dead else 'no'}")
            print(f"    corrupt:    {_red('yes') if in_corrupt else 'no'}")
            print(f"    heartbeat:  {'active' if hb else 'none'}")

    finally:
        await r.aclose()

    return 0


async def _cmd_retry(task_id: str) -> int:
    """Retry a failed/dead task from dead-letter queue."""
    import redis.asyncio as aioredis

    from app.core.config import settings
    from app.services.task_queue_service import (
        _v2_task_hash_key,
        task_queue,
    )

    if not settings.REDIS_URL:
        print(_red("Error: REDIS_URL not configured"))
        return 1

    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    try:
        hash_key = _v2_task_hash_key(task_id)
        data = await r.hgetall(hash_key)
        if not data:
            print(_red(f"Task not found: {task_id}"))
            return 1

        task_type = data.get("task_type", "")
        status = data.get("status", "")
        if status not in ("failed", "dead", "review_required"):
            print(_yellow(f"Task status is '{status}', not in a retryable state"))
            return 1

        # Try retry_from_dead_v2
        ok = await task_queue.retry_from_dead_v2(task_type, task_id)
        if ok:
            print(_green(f"Task {task_id} re-queued from dead-letter."))
            return 0
        else:
            print(_red(f"Failed to re-queue task {task_id}."))
            return 1
    finally:
        await r.aclose()


async def _cmd_cancel(task_id: str) -> int:
    """Cancel a pending/retry task."""
    import redis.asyncio as aioredis

    from app.core.config import settings
    from app.services.task_queue_service import (
        _v2_q_key,
        _v2_retry_key,
        _v2_task_hash_key,
        task_queue,
    )

    if not settings.REDIS_URL:
        print(_red("Error: REDIS_URL not configured"))
        return 1

    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    try:
        hash_key = _v2_task_hash_key(task_id)
        data = await r.hgetall(hash_key)
        if not data:
            print(_red(f"Task not found: {task_id}"))
            return 1

        task_type = data.get("task_type", "")
        status = data.get("status", "")

        if status in ("pending", "retry"):
            # Atomically cancel: remove from ready/retry, mark corrupt
            if status == "pending":
                await r.lrem(_v2_q_key(task_type), 1, task_id)
            elif status == "retry":
                await r.zrem(_v2_retry_key(task_type), task_id)
            await task_queue.mark_corrupt_v2(task_id, task_type, "cancelled by admin")
            print(_green(f"Task {task_id} cancelled."))
            return 0
        elif status == "processing":
            # Set cancellation requested flag
            await r.hset(hash_key, "cancel_requested", "1")
            print(_yellow(f"Task {task_id} is processing — cancellation requested. "
                          f"Worker will check at next safe point."))
            return 0
        else:
            print(_yellow(f"Task {task_id} has status '{status}', cannot cancel."))
            return 1
    finally:
        await r.aclose()


def _usage() -> None:
    print("Usage:")
    print("  python -m app.cli.task_queue status")
    print("  python -m app.cli.task_queue inspect TASK_ID")
    print("  python -m app.cli.task_queue retry TASK_ID")
    print("  python -m app.cli.task_queue cancel TASK_ID")
    sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        _usage()

    cmd = sys.argv[1]

    if cmd == "status":
        code = asyncio.run(_cmd_status())
    elif cmd == "inspect":
        if len(sys.argv) < 3:
            print("Error: TASK_ID required")
            _usage()
        code = asyncio.run(_cmd_inspect(sys.argv[2]))
    elif cmd == "retry":
        if len(sys.argv) < 3:
            print("Error: TASK_ID required")
            _usage()
        code = asyncio.run(_cmd_retry(sys.argv[2]))
    elif cmd == "cancel":
        if len(sys.argv) < 3:
            print("Error: TASK_ID required")
            _usage()
        code = asyncio.run(_cmd_cancel(sys.argv[2]))
    else:
        _usage()

    sys.exit(code)


if __name__ == "__main__":
    main()

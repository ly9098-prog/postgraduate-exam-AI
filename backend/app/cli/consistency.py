"""Consistency check CLI — read-only validation of queue and data integrity.

Usage:
    python -m app.cli.consistency check
"""

from __future__ import annotations

import asyncio
import sys
import time


def _green(s: str) -> str:
    return f"\033[32m{s}\033[0m"


def _red(s: str) -> str:
    return f"\033[31m{s}\033[0m"


def _yellow(s: str) -> str:
    return f"\033[33m{s}\033[0m"


def _bold(s: str) -> str:
    return f"\033[1m{s}\033[0m"


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


async def _cmd_check() -> int:
    """Run all consistency checks, report findings."""
    import redis.asyncio as aioredis

    from app.core.config import settings
    from app.services.task_queue_service import (
        _v2_corrupt_key,
        _v2_dead_key,
        _v2_heartbeat_key,
        _v2_p_key,
        _v2_q_key,
        _v2_retry_key,
        _v2_task_hash_key,
    )

    print("=== Consistency Check ===\n")

    issues = 0
    warnings = 0

    if not settings.REDIS_URL:
        print(_red("REDIS_URL not configured — cannot check Redis consistency."))
        return 1

    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    try:
        # ═══ 1. Processing Hash/ZSET inconsistency ═══
        print("─ Processing ZSET vs Hash consistency")
        for tt in TASK_TYPES:
            p_key = _v2_p_key(tt)
            try:
                members = await r.zrange(p_key, 0, -1)
                for task_id in members:
                    # Check task hash exists
                    hash_key = _v2_task_hash_key(task_id)
                    exists = await r.exists(hash_key)
                    if not exists:
                        print(f"  {_red('ISSUE')}: {tt} — {task_id} in processing ZSET but hash missing")
                        issues += 1

                    # Check heartbeat
                    hb_key = _v2_heartbeat_key(task_id)
                    hb = await r.get(hb_key)
                    if not hb:
                        score = await r.zscore(p_key, task_id)
                        if score is not None and score < time.time():
                            print(f"  {_yellow('WARN')}: {tt} — {task_id} expired lease, no heartbeat (stale)")
                            warnings += 1

                    # Verify not also in ready queue
                    q_key = _v2_q_key(tt)
                    pos = await r.lpos(q_key, task_id)
                    if pos is not None:
                        print(f"  {_red('ISSUE')}: {tt} — {task_id} in BOTH processing AND ready")
                        issues += 1

                    # Verify not also in retry
                    retry_key = _v2_retry_key(tt)
                    in_retry = await r.zscore(retry_key, task_id)
                    if in_retry is not None:
                        print(f"  {_red('ISSUE')}: {tt} — {task_id} in BOTH processing AND retry")
                        issues += 1
            except Exception as e:
                print(f"  {_yellow('WARN')}: {tt} — error scanning processing: {e}")
                warnings += 1

        # ═══ 2. Terminal status still in processing ═══
        print("\n─ Terminal status in processing")
        for tt in TASK_TYPES:
            p_key = _v2_p_key(tt)
            try:
                members = await r.zrange(p_key, 0, -1)
                for task_id in members:
                    hash_key = _v2_task_hash_key(task_id)
                    status = await r.hget(hash_key, "status")
                    if status in ("completed", "dead", "failed"):
                        print(f"  {_red('ISSUE')}: {tt} — {task_id} status={status} but still in processing ZSET")
                        issues += 1
            except Exception:
                pass  # Already reported above

        # ═══ 3. Retry state inconsistency ═══
        print("\n─ Retry state consistency")
        for tt in TASK_TYPES:
            retry_key = _v2_retry_key(tt)
            try:
                members = await r.zrange(retry_key, 0, -1)
                for task_id in members:
                    hash_key = _v2_task_hash_key(task_id)
                    status = await r.hget(hash_key, "status")
                    if status not in ("retry", "failed"):
                        print(f"  {_red('ISSUE')}: {tt} — {task_id} in retry ZSET but status={status}")
                        issues += 1
            except Exception:
                pass

        # ═══ 4. Dead letter consistency ═══
        print("\n─ Dead letter consistency")
        for tt in TASK_TYPES:
            dead_key = _v2_dead_key(tt)
            try:
                members = await r.lrange(dead_key, 0, -1)
                for task_id in members:
                    hash_key = _v2_task_hash_key(task_id)
                    exists = await r.exists(hash_key)
                    if not exists:
                        print(f"  {_yellow('WARN')}: {tt} — {task_id} in dead list but hash missing")
                        warnings += 1
            except Exception:
                pass

        # ═══ 5. Corrupt consistency ═══
        print("\n─ Corrupt queue consistency")
        for tt in TASK_TYPES:
            cor_key = _v2_corrupt_key(tt)
            try:
                members = await r.zrange(cor_key, 0, -1)
                if len(members) > 0:
                    print(f"  {_yellow('INFO')}: {tt} — {len(members)} corrupt entries")
                    for task_id in members:
                        hash_key = _v2_task_hash_key(task_id)
                        reason = await r.hget(hash_key, "last_error")
                        print(f"    {task_id}: {reason[:80] if reason else 'no reason'}")
            except Exception:
                pass

        # ═══ 6. Negative refcount ═══
        print("\n─ Staging refcount")
        try:
            cursor = 0
            neg_count = 0
            while True:
                cursor, keys = await r.scan(cursor=cursor, match="staging:ref:*", count=200)
                for key in keys:
                    val = await r.get(key)
                    if val is not None:
                        v = int(val)
                        if v < 0:
                            neg_count += 1
                            if neg_count <= 5:
                                obj_id = key.replace("staging:ref:", "")
                                print(f"  {_red('ISSUE')}: negative refcount ({v}) for {obj_id}")
                if cursor == 0:
                    break
            if neg_count > 5:
                print(f"  ... and {neg_count - 5} more negative refcounts")
            if neg_count == 0:
                print(f"  {_green('OK')}: no negative refcounts")
            else:
                issues += neg_count
        except Exception as e:
            print(f"  {_yellow('WARN')}: refcount scan error: {e}")
            warnings += 1

        # ═══ 7. Orphan heartbeats ═══
        print("\n─ Orphan heartbeats")
        try:
            cursor = 0
            orphan_hb = 0
            while True:
                cursor, keys = await r.scan(cursor=cursor, match="taskq:v2:heartbeat:*", count=200)
                for key in keys:
                    task_id = key.replace("taskq:v2:heartbeat:", "")
                    hash_key = _v2_task_hash_key(task_id)
                    exists = await r.exists(hash_key)
                    if not exists:
                        orphan_hb += 1
                if cursor == 0:
                    break
            if orphan_hb > 0:
                print(f"  {_yellow('WARN')}: {orphan_hb} orphan heartbeat keys (no task hash)")
                warnings += orphan_hb
            else:
                print(f"  {_green('OK')}: no orphan heartbeats")
        except Exception as e:
            print(f"  {_yellow('WARN')}: heartbeat scan error: {e}")
            warnings += 1

    finally:
        await r.aclose()

    # ═══ 8. DB: stale processing pipelines ═══
    print("\n─ Database: stale processing pipelines")
    try:
        from sqlalchemy import select

        from app.core.database import async_session
        from app.models.import_pipeline import ImportPipeline

        async with async_session() as db:
            result = await db.execute(
                select(ImportPipeline.pipeline_id, ImportPipeline.status,
                       ImportPipeline.execution_generation, ImportPipeline.current_task_id)
                .where(ImportPipeline.status == "processing")
            )
            stale = result.all()
            if len(stale) > 0:
                print(f"  {_yellow('WARN')}: {len(stale)} pipelines stuck in 'processing' status:")
                for row in stale[:10]:
                    print(f"    {row.pipeline_id} gen={row.execution_generation} task={row.current_task_id}")
                if len(stale) > 10:
                    print(f"    ... and {len(stale) - 10} more")
                warnings += len(stale)
            else:
                print(f"  {_green('OK')}: no stale processing pipelines")
    except Exception as e:
        print(f"  {_yellow('WARN')}: DB check error: {e}")
        warnings += 1

    # ═══ Summary ═══
    print(f"\n{'='*40}")
    print(f"Issues:   {issues if issues > 0 else _green('0')}")
    print(f"Warnings: {warnings if warnings > 0 else _green('0')}")

    if issues > 0:
        print(_red(f"\n{issues} consistency issue(s) found."))
        return 1
    elif warnings > 0:
        print(_yellow(f"\n{warnings} warning(s) — review recommended."))
        return 0
    else:
        print(_green("\nAll consistency checks passed."))
        return 0


def _usage() -> None:
    print("Usage:")
    print("  python -m app.cli.consistency check")
    sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] != "check":
        _usage()

    code = asyncio.run(_cmd_check())
    sys.exit(code)


if __name__ == "__main__":
    main()

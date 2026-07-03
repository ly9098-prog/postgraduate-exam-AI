"""Redis-backed reliable task queue for prewarming AI error analysis.

Tasks survive process restarts (stored in Redis). On startup the worker drains
any leftover tasks and processes them. Failed tasks are retried with delay via
a Redis Sorted Set.

Usage:
    enqueue_prewarm(wq_id=123, user_id=456)  # push to queue
    # Worker loop in lifespan runs automatically
"""

import asyncio
import json
import logging
import time

from app.core.config import settings

PREWARM_QUEUE_KEY = "ai:prewarm:queue"
PREWARM_RETRY_KEY = "ai:prewarm:retry"
MAX_RETRIES = 3
RETRY_DELAY_SEC = 30

logger = logging.getLogger(__name__)

_redis_client = None
_redis_lock: asyncio.Lock = asyncio.Lock()
_worker_task: asyncio.Task | None = None
_running = False


def _build_redis_url() -> str | None:
    url = settings.REDIS_URL
    return url if url else None


async def get_redis_client():
    """Get the shared Redis client singleton. Returns None if Redis unavailable."""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.ping()
            return _redis_client
        except Exception:
            logger.debug("[prewarm] Redis ping failed, reconnecting")
            _redis_client = None

    redis_url = _build_redis_url()
    if not redis_url:
        return None

    async with _redis_lock:
        if _redis_client is not None:
            return _redis_client
        try:
            import redis.asyncio as redis
            r = redis.from_url(
                redis_url,
                socket_connect_timeout=2,
                socket_timeout=5,
                decode_responses=True,
            )
            await r.ping()
            _redis_client = r
            logger.info("[prewarm] Redis client initialized")
            return _redis_client
        except Exception:
            logger.warning("[prewarm] Redis unavailable")
            return None


async def close_redis_client() -> None:
    """Close the shared Redis client. Call during shutdown."""
    global _redis_client
    async with _redis_lock:
        if _redis_client is None:
            return
        try:
            await _redis_client.aclose()
        except Exception:
            pass
        _redis_client = None
        logger.info("[prewarm] Redis client closed")


async def enqueue_prewarm(
    wq_id: int, user_id: int, retries: int = 0, delay_seconds: int = 0,
) -> bool:
    """Push a prewarm task to the Redis queue. Returns True if queued."""
    r = await get_redis_client()
    if r is None:
        return False
    try:
        task = json.dumps({"wq_id": wq_id, "user_id": user_id, "retries": retries})
        if delay_seconds > 0:
            score = time.time() + delay_seconds
            await r.zadd(PREWARM_RETRY_KEY, {task: score})
            logger.info(
                "[prewarm] queued (delayed %ds) wq_id=%d uid=%d retry=%d",
                delay_seconds, wq_id, user_id, retries,
            )
        else:
            await r.rpush(PREWARM_QUEUE_KEY, task)
            logger.info("[prewarm] queued wq_id=%d uid=%d retry=%d", wq_id, user_id, retries)
        return True
    except Exception:
        logger.exception("[prewarm] enqueue failed wq_id=%d uid=%d", wq_id, user_id)
        return False


async def _move_due_retry_tasks(r) -> int:
    """Move due tasks from retry Sorted Set to the main queue. Returns count moved."""
    now = time.time()
    try:
        due = await r.zrangebyscore(PREWARM_RETRY_KEY, 0, now)
        if not due:
            return 0
        for task_bytes in due:
            task_str = task_bytes if isinstance(task_bytes, str) else task_bytes.decode()
            await r.rpush(PREWARM_QUEUE_KEY, task_str)
        await r.zremrangebyscore(PREWARM_RETRY_KEY, 0, now)
        count = len(due)
        if count:
            logger.info("[prewarm] moved %d due retry tasks to queue", count)
        return count
    except Exception:
        logger.exception("[prewarm] move_due_retry_tasks failed")
        return 0


async def _process_task(wq_id: int, user_id: int, retries: int) -> None:
    """Process a single prewarm task."""
    from app.services.ai_service import prewarm_wrong_question_analysis
    try:
        await prewarm_wrong_question_analysis(wq_id, user_id)
        logger.info("[prewarm] processed wq_id=%d uid=%d", wq_id, user_id)
    except Exception:
        logger.exception("[prewarm] process failed wq_id=%d uid=%d retries=%d", wq_id, user_id, retries)
        if retries < MAX_RETRIES:
            logger.info("[prewarm] requeue wq_id=%d uid=%d retry=%d", wq_id, user_id, retries + 1)
            await enqueue_prewarm(wq_id, user_id, retries=retries + 1, delay_seconds=RETRY_DELAY_SEC)
        else:
            logger.error(
                "[prewarm] drop wq_id=%d uid=%d reached max_retries=%d",
                wq_id, user_id, MAX_RETRIES,
            )


async def _worker_loop():
    """Background worker loop: move due retries, then BLPOP and process."""
    global _running
    _running = True
    logger.info("[prewarm] worker started")

    while _running:
        r = await get_redis_client()
        if r is None:
            await asyncio.sleep(30)
            continue
        try:
            await _move_due_retry_tasks(r)
            result = await r.blpop(PREWARM_QUEUE_KEY, timeout=10)
            if result is None:
                continue
            _, data = result
            task = json.loads(data)
            wq_id = task.get("wq_id")
            user_id = task.get("user_id")
            retries = task.get("retries", 0)
            if wq_id and user_id:
                await _process_task(wq_id, user_id, retries)
        except json.JSONDecodeError:
            logger.warning("[prewarm] invalid task data, skipping")
        except Exception:
            logger.exception("[prewarm] worker loop error")

    logger.info("[prewarm] worker stopped")


async def start_worker():
    """Start the background worker task. Call in FastAPI lifespan startup."""
    global _worker_task
    if _worker_task is not None:
        return
    _worker_task = asyncio.create_task(_worker_loop(), name="ai-prewarm-worker")


async def stop_worker():
    """Stop the background worker task. Call in FastAPI lifespan shutdown."""
    global _worker_task, _running
    _running = False
    if _worker_task is None:
        return
    _worker_task.cancel()
    try:
        await _worker_task
    except asyncio.CancelledError:
        pass
    _worker_task = None
    await close_redis_client()
    logger.info("[prewarm] worker terminated")

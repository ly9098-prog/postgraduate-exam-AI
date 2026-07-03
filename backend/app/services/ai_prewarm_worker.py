"""Redis-backed reliable task queue for prewarming AI error analysis.

Tasks survive process restarts (stored in Redis). On startup the worker drains
any leftover tasks and processes them.

Usage:
    enqueue_prewarm(wq_id=123, user_id=456)  # push to queue
    # Worker loop in lifespan runs automatically
"""

import asyncio
import json
import logging

from app.core.config import settings

PREWARM_QUEUE_KEY = "ai:prewarm:queue"
MAX_RETRIES = 3
RETRY_DELAY_SEC = 30

logger = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None
_running = False


def _build_redis_url() -> str | None:
    url = settings.REDIS_URL
    return url if url else None


async def _get_redis():
    if not _build_redis_url():
        return None
    try:
        import redis.asyncio as redis
        r = redis.from_url(
            _build_redis_url(),
            socket_connect_timeout=2,
            socket_timeout=5,
            decode_responses=True,
        )
        await r.ping()
        return r
    except Exception:
        logger.debug("Redis unavailable for prewarm worker")
        return None


async def enqueue_prewarm(wq_id: int, user_id: int, retries: int = 0) -> bool:
    """Push a prewarm task to the Redis queue. Returns True if queued."""
    r = await _get_redis()
    if r is None:
        return False
    try:
        task = json.dumps({"wq_id": wq_id, "user_id": user_id, "retries": retries})
        await r.rpush(PREWARM_QUEUE_KEY, task)
        await r.aclose()
        logger.info("[prewarm] queued wq_id=%d uid=%d", wq_id, user_id)
        return True
    except Exception:
        logger.debug("[prewarm] enqueue failed wq_id=%d uid=%d", wq_id, user_id)
        try:
            await r.aclose()
        except Exception:
            pass
        return False


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
            await enqueue_prewarm(wq_id, user_id, retries=retries + 1)


async def _worker_loop():
    """Background worker loop: BLPOP from Redis queue and process."""
    global _running
    _running = True
    logger.info("[prewarm] worker started")

    while _running:
        r = await _get_redis()
        if r is None:
            # Redis unavailable — sleep and retry
            await asyncio.sleep(30)
            continue
        try:
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
        finally:
            try:
                await r.aclose()
            except Exception:
                pass

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
    logger.info("[prewarm] worker terminated")

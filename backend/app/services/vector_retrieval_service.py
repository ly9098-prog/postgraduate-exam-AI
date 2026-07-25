"""向量召回服务：向量检索、相似题推荐、智能刷题召回。"""

import hashlib
import json as _json
import logging
import math
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache
from app.core.config import settings
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.services import embedding_service
from app.services.admin_subject_service import resolve_subject_ids

logger = logging.getLogger("postgraduate-ai.vector_retrieval")

# 模块级缓存：避免每次请求都查询 pgvector 可用性（TTL 60 秒）
_vector_enabled_cache: dict[str, Any] = {"value": None, "checked": False, "checked_at": 0.0}

_VECTOR_CACHE_TTL = 60  # 秒


# ---------------------------------------------------------------------------
# DB-first 配置访问器（同步 + TTL 缓存）
# 所有 settings.VECTOR_* / settings.EMBEDDING_* 引用通过此访问器间接获取，
# 优先从 DB 读取，环境变量仅作为兜底。
# ---------------------------------------------------------------------------


class _VectorSettings:
    """从 DB 缓存或环境变量获取向量相关配置。"""

    _cached: Any = None
    _cached_at: float = 0
    _TTL = 30  # seconds

    async def refresh_async(self, db: AsyncSession) -> None:
        """异步刷新配置缓存。应在 vector 相关 async 入口调用。"""
        now = time.monotonic()
        if self._cached and (now - self._cached_at) < self._TTL:
            return
        # Skip refresh for mock sessions (test context)
        if hasattr(db, "_mock_name") or hasattr(db, "assert_called"):
            return
        try:
            from app.services.vector_config_service import (
                EmbeddingConfig,
                VectorSearchConfig,
                _seed_if_empty,
                decrypt_api_key,
            )
            row = await _seed_if_empty(db)

            api_key = ""
            if row.embedding_api_key_encrypted:
                api_key = decrypt_api_key(row.embedding_api_key_encrypted)
            if not api_key and settings.EMBEDDING_API_KEY:
                api_key = settings.EMBEDDING_API_KEY

            emb = EmbeddingConfig(
                api_key=api_key,
                base_url=row.embedding_base_url or settings.EMBEDDING_BASE_URL,
                model=row.embedding_model or settings.EMBEDDING_MODEL,
                dim=row.embedding_dim or settings.EMBEDDING_DIM,
                timeout=row.embedding_timeout or settings.EMBEDDING_TIMEOUT,
                batch_size=row.embedding_batch_size or settings.EMBEDDING_BATCH_SIZE,
                provider=row.embedding_provider or settings.EMBEDDING_PROVIDER,
            )
            vec = VectorSearchConfig(
                enabled=row.vector_enabled,
                mode=row.vector_mode,
                allowlist=row.vector_allowlist,
                cache_ttl_sec=row.vector_cache_ttl_sec,
                top_k=row.vector_top_k,
                similarity_threshold=row.vector_similarity_threshold,
            )
            self._cached = {"emb": emb, "vec": vec}
            self._cached_at = now
        except BaseException:
            logger.debug("DB 向量配置读取失败，使用环境变量", exc_info=True)

    @property
    def emb(self):
        if self._cached and "emb" in self._cached:
            return self._cached["emb"]
        # Fallback: use local settings (patchable in tests)
        from app.services.vector_config_service import EmbeddingConfig
        return EmbeddingConfig(
            api_key=settings.EMBEDDING_API_KEY,
            base_url=settings.EMBEDDING_BASE_URL,
            model=settings.EMBEDDING_MODEL,
            dim=settings.EMBEDDING_DIM,
            timeout=settings.EMBEDDING_TIMEOUT,
            batch_size=settings.EMBEDDING_BATCH_SIZE,
            provider=settings.EMBEDDING_PROVIDER,
        )

    @property
    def vec(self):
        if self._cached and "vec" in self._cached:
            return self._cached["vec"]
        # Fallback: use local settings (patchable in tests)
        from app.services.vector_config_service import VectorSearchConfig
        return VectorSearchConfig(
            enabled=settings.VECTOR_ENABLED,
            mode=settings.VECTOR_MODE,
            allowlist=settings.VECTOR_ALLOWLIST,
            cache_ttl_sec=settings.VECTOR_CACHE_TTL_SEC,
            top_k=settings.VECTOR_TOP_K,
            similarity_threshold=settings.VECTOR_SIMILARITY_THRESHOLD,
        )


_vs = _VectorSettings()


def _reset_vector_enabled_cache():
    """重置向量可用性缓存（用于测试或配置变更后）。"""
    _vector_enabled_cache["value"] = None
    _vector_enabled_cache["checked"] = False
    _vector_enabled_cache["checked_at"] = 0.0
    # 同步清理 DB-first 配置缓存
    _vs._cached = None
    _vs._cached_at = 0


# ── embedding 校验 ──


def validate_embedding(value: object, expected_dimension: int) -> list[float]:
    """校验 embedding 向量，返回合法的 list[float]。

    校验规则：
    - 必须是 list 或 tuple
    - 长度等于 expected_dimension
    - 每项必须是 int 或 float
    - 转为 float 后必须是有限值（拒绝 NaN / Infinity / -Infinity）
    - 拒绝字符串、None、嵌套数组、空数组

    失败时抛出 ValueError。
    """
    if value is None:
        raise ValueError("embedding is None")
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"embedding must be list/tuple, got {type(value).__name__}")
    if len(value) == 0:
        raise ValueError("embedding is empty")
    if len(value) != expected_dimension:
        raise ValueError(
            f"embedding dimension mismatch: expected {expected_dimension}, got {len(value)}"
        )
    result: list[float] = []
    for i, item in enumerate(value):
        if isinstance(item, (list, tuple)):
            raise ValueError(f"embedding[{i}] is nested array")
        if not isinstance(item, (int, float)):
            raise ValueError(f"embedding[{i}] is not numeric: {type(item).__name__}")
        f = float(item)
        if not math.isfinite(f):
            raise ValueError(f"embedding[{i}] is not finite: {item}")
        result.append(f)
    return result


# ── VectorDecision 统一决策层 ──


@dataclass(frozen=True)
class VectorDecision:
    """向量访问统一决策结果。

    Attributes:
        enabled: 向量基础设施是否可用（表/扩展/API 配置）。
        execute: 是否应执行向量查询。
        use_result: 是否可将向量结果返回给用户。
        mode: 当前解析后的 VECTOR_MODE。
        reason: 决策原因（用于日志/可观测性）。
    """
    enabled: bool
    execute: bool
    use_result: bool
    mode: str
    reason: str


def decide_vector_access(
    user_id: int | None = None,
    subject: str | None = None,
    *,
    infra_available: bool = True,
) -> VectorDecision:
    """统一向量访问决策。

    所有向量入口（相似题推荐、smart 推荐、smart path、知识路径、AI learning、
    文本向量召回）必须调用此函数，不得自行判断。

    语义：
    - off: execute=False, use_result=False
    - shadow: execute=True, use_result=False
    - allowlist 命中: execute=True, use_result=True
    - allowlist 未命中: execute=False, use_result=False
    - all: execute=True, use_result=True

    安全约束：
    - allowlist 模式且白名单为空 → 全部拒绝。
    - 基础设施不可用 → 全部拒绝。
    """
    mode = resolve_vector_mode()

    if not infra_available:
        return VectorDecision(
            enabled=False, execute=False, use_result=False,
            mode=mode, reason="infra_unavailable",
        )

    if mode == "off":
        return VectorDecision(
            enabled=True, execute=False, use_result=False,
            mode=mode, reason="mode_off",
        )

    if mode == "shadow":
        return VectorDecision(
            enabled=True, execute=True, use_result=False,
            mode=mode, reason="shadow_mode",
        )

    if mode == "all":
        return VectorDecision(
            enabled=True, execute=True, use_result=True,
            mode=mode, reason="mode_all",
        )

    # mode == "allowlist"
    if _is_allowlist_empty():
        return VectorDecision(
            enabled=True, execute=False, use_result=False,
            mode=mode, reason="allowlist_empty_deny",
        )

    if _allowlist_matches(user_id=user_id, subject=subject):
        return VectorDecision(
            enabled=True, execute=True, use_result=True,
            mode=mode, reason="allowlist_hit",
        )

    return VectorDecision(
        enabled=True, execute=False, use_result=False,
        mode=mode, reason="allowlist_miss",
    )


# ── is_vector_enabled (基础设施检测，保留向后兼容) ──


async def is_vector_enabled(db: AsyncSession) -> bool:
    """判断向量基础设施是否可用。

    条件：
    - vector_enabled == True（DB 或环境变量）
    - 数据库 dialect 是 postgresql
    - embedding api_key、base_url、model 已配置
    - question_embeddings 表存在
    - pgvector 扩展可用
    """
    await _vs.refresh_async(db)

    if not _vs.vec.enabled:
        return False

    if not (
        _vs.emb.api_key
        and _vs.emb.base_url
        and _vs.emb.model
    ):
        return False

    # 使用缓存避免重复查询（TTL 60 秒）
    if _vector_enabled_cache["checked"]:
        elapsed = time.monotonic() - _vector_enabled_cache["checked_at"]
        if elapsed < _VECTOR_CACHE_TTL:
            return bool(_vector_enabled_cache["value"])

    try:
        dialect_name = db.bind.dialect.name if db.bind else "unknown"
        if dialect_name != "postgresql":
            _vector_enabled_cache["value"] = False
            _vector_enabled_cache["checked"] = True
            _vector_enabled_cache["checked_at"] = time.monotonic()
            return False

        result = await db.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        )
        if result.scalar() is None:
            _vector_enabled_cache["value"] = False
            _vector_enabled_cache["checked"] = True
            _vector_enabled_cache["checked_at"] = time.monotonic()
            return False

        result = await db.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'question_embeddings'"
            )
        )
        if result.scalar() is None:
            _vector_enabled_cache["value"] = False
            _vector_enabled_cache["checked"] = True
            _vector_enabled_cache["checked_at"] = time.monotonic()
            return False

        _vector_enabled_cache["value"] = True
        _vector_enabled_cache["checked"] = True
        _vector_enabled_cache["checked_at"] = time.monotonic()
        return True

    except Exception:
        logger.warning("检查向量功能可用性时出错", exc_info=True)
        _vector_enabled_cache["value"] = False
        _vector_enabled_cache["checked"] = True
        _vector_enabled_cache["checked_at"] = time.monotonic()
        return False


# ── upsert ──


async def upsert_question_embedding(
    db: AsyncSession, question: Question, force: bool = False
) -> dict:
    """为单个题目生成并存储 embedding。

    返回:
        {"question_id": int, "status": "created"|"updated"|"skipped"|"failed", "reason": str}
    """
    qid = question.id
    model = _vs.emb.model

    try:
        content_text = embedding_service.build_question_embedding_text(question)
        content_hash = embedding_service.compute_content_hash(content_text)

        result = await db.execute(
            text(
                "SELECT id, content_hash FROM question_embeddings "
                "WHERE question_id = :qid AND embedding_model = :model"
            ),
            {"qid": qid, "model": model},
        )
        existing = result.first()

        if existing and existing[1] == content_hash and not force:
            return {"question_id": qid, "status": "skipped", "reason": "content unchanged"}

        embedding = await embedding_service.get_embedding(content_text)
        if embedding is None:
            return {"question_id": qid, "status": "failed", "reason": "embedding api failed"}

        # 校验 embedding
        try:
            validated = validate_embedding(embedding, _vs.emb.dim)
        except ValueError as ve:
            logger.warning("embedding 校验失败 question_id=%d: %s", qid, ve)
            return {"question_id": qid, "status": "failed", "reason": f"invalid_embedding: {ve}"}

        pg_literal = embedding_service.vector_to_pg_literal(validated)
        dim = _vs.emb.dim

        if existing:
            await db.execute(
                text(
                    "UPDATE question_embeddings SET "
                    "content_hash = :hash, content_text = :text, "
                    "embedding = CAST(:emb AS vector), embedding_dim = :dim, "
                    "subject = :subject, question_type = :qtype, "
                    "updated_at = NOW(), embedded_at = NOW() "
                    "WHERE question_id = :qid AND embedding_model = :model"
                ),
                {
                    "hash": content_hash,
                    "text": content_text,
                    "emb": pg_literal,
                    "dim": dim,
                    "subject": question.subject_ref.code if question.subject_ref else "",
                    "qtype": question.question_type,
                    "qid": qid,
                    "model": model,
                },
            )
            await db.flush()
            return {"question_id": qid, "status": "updated", "reason": ""}
        else:
            await db.execute(
                text(
                    "INSERT INTO question_embeddings "
                    "(question_id, subject, question_type, embedding_model, embedding_dim, "
                    "content_hash, content_text, embedding) "
                    "VALUES (:qid, :subject, :qtype, :model, :dim, :hash, :text, CAST(:emb AS vector))"
                ),
                {
                    "qid": qid,
                    "subject": question.subject_ref.code if question.subject_ref else "",
                    "qtype": question.question_type,
                    "model": model,
                    "dim": dim,
                    "hash": content_hash,
                    "text": content_text,
                    "emb": pg_literal,
                },
            )
            await db.flush()
            return {"question_id": qid, "status": "created", "reason": ""}

    except Exception as exc:
        logger.warning("upsert embedding failed for question_id=%d: %s", qid, exc, exc_info=True)
        return {"question_id": qid, "status": "failed", "reason": str(exc)[:200]}


# ── 回填（游标分页 + savepoint） ──


async def backfill_question_embeddings(
    db: AsyncSession,
    subject: str | None = None,
    limit: int = 100,
    force: bool = False,
    after_id: int = 0,
) -> dict:
    """批量为题目生成 embedding（游标分页）。

    使用 Question.id 作为稳定排序和游标，支持多次运行覆盖全部题目。
    每条题目使用 savepoint，单条失败不污染整个批次。

    返回:
        processed, created, updated, skipped, failed, next_cursor, has_more, errors
    """
    if not await is_vector_enabled(db):
        return {
            "total": 0, "created": 0, "updated": 0, "skipped": 0,
            "failed": 0, "enabled": False, "errors": [],
            "next_cursor": None, "has_more": False,
        }

    limit = min(max(1, limit), 1000)

    # 构建查询条件
    conditions: list = [
        Question.is_active,
        Question.review_status == "approved",
        Question.id > after_id,
    ]

    if subject:
        ids = await resolve_subject_ids(db, subject)
        conditions.append(Question.subject_id.in_(ids))

    if not force:
        # 优先查询当前 model 下不存在 embedding 的题目
        conditions.append(
            ~Question.id.in_(
                select(text("question_id")).select_from(text("question_embeddings")).where(
                    text("embedding_model = :model")
                )
            )
        )

    query = (
        select(Question)
        .where(and_(*conditions))
        .order_by(Question.id.asc())
        .limit(limit)
    )

    result = await db.execute(query)
    questions = list(result.scalars().all())

    stats = {
        "total": len(questions), "created": 0, "updated": 0,
        "skipped": 0, "failed": 0,
    }
    errors: list[dict] = []

    for q in questions:
        # 每条题目使用 savepoint，单条失败不污染整个批次
        try:
            async with db.begin_nested():
                res = await upsert_question_embedding(db, q, force=force)
                status = res["status"]
                if status in stats:
                    stats[status] += 1
                if status == "failed" and res.get("reason"):
                    errors.append({
                        "question_id": q.id,
                        "reason": res["reason"][:200],
                    })
        except Exception as exc:
            stats["failed"] += 1
            errors.append({
                "question_id": q.id,
                "reason": str(exc)[:200],
            })
            logger.warning("backfill savepoint 回滚 question_id=%d", q.id, exc_info=True)

    # 计算游标
    last_qid = questions[-1].id if questions else after_id
    has_more = len(questions) >= limit

    return {
        **stats,
        "enabled": True,
        "errors": errors,
        "next_cursor": last_qid if has_more else None,
        "has_more": has_more,
    }


async def _ensure_source_embedding(
    db: AsyncSession, question: Question
) -> list[float] | None:
    """确保源题有 embedding，如果没有则尝试现场生成。"""
    model = _vs.emb.model

    result = await db.execute(
        text(
            "SELECT embedding::text FROM question_embeddings "
            "WHERE question_id = :qid AND embedding_model = :model"
        ),
        {"qid": question.id, "model": model},
    )
    row = result.first()
    if row:
        raw = row[0]
        try:
            if isinstance(raw, str):
                raw = raw.strip("[]")
                return [float(x) for x in raw.split(",")]
            return list(raw)
        except (ValueError, AttributeError):
            logger.warning("解析 pgvector 向量文本失败 question_id=%d", question.id)
            return None

    # 不存在，尝试生成
    res = await upsert_question_embedding(db, question)
    if res["status"] in ("created", "updated"):
        result = await db.execute(
            text(
                "SELECT embedding::text FROM question_embeddings "
                "WHERE question_id = :qid AND embedding_model = :model"
            ),
            {"qid": question.id, "model": model},
        )
        row = result.first()
        if row:
            raw = row[0]
            try:
                if isinstance(raw, str):
                    raw = raw.strip("[]")
                    return [float(x) for x in raw.split(",")]
                return list(raw)
            except (ValueError, AttributeError):
                logger.warning("解析 pgvector 向量文本失败 question_id=%d", question.id)
                return None

    return None


# ── 缓存辅助 ──


async def _get_user_answer_version(db: AsyncSession, user_id: int) -> int:
    """获取用户答题数量作为缓存版本号。

    用户每答一题，版本号 +1，缓存 key 随之变化。
    查询失败时返回 0（不影响核心功能）。
    """
    try:
        result = await db.execute(
            select(func.count(PracticeRecord.id)).where(
                PracticeRecord.user_id == user_id
            )
        )
        return result.scalar() or 0
    except Exception:
        return 0


async def invalidate_vector_cache(user_id: int) -> None:
    """清理指定用户的向量推荐缓存。

    使用 Redis SCAN（通过 cache 客户端）避免 KEYS 阻塞。
    当前实现：由于 cache 客户端可能不支持 scan，采用 TTL 自然过期 +
    版本号 key 策略。此函数记录用户答题版本到 Redis，
    下次缓存读取时版本号不匹配则自动失效。
    """
    try:
        version_key = f"vector:answer_ver:{user_id}"
        current = await cache.get(version_key)
        new_ver = (int(current) + 1) if current else 1
        await cache.set(version_key, new_ver, ttl=86400)
    except Exception:
        logger.debug("invalidate_vector_cache failed uid=%d", user_id, exc_info=True)


# ── 相似题检索 ──


async def search_similar_questions(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    count: int = 5,
    exclude_answered: bool = True,
    no_repeat_days: int | None = None,
) -> dict:
    """向量相似题检索 + 二次排序。

    通过 decide_vector_access() 统一决策：
    - off / allowlist 未命中：不执行，返回 fallback
    - shadow：执行但不使用结果，返回与 off 一致
    - allowlist 命中 / all：执行并使用结果

    向量检索 SQL 直接 JOIN questions 提前过滤无效题目。
    """
    t0 = time.monotonic()

    # 基础设施检测
    infra_ok = await is_vector_enabled(db)
    decision = decide_vector_access(
        user_id=user_id,
        subject=None,  # subject 在获取源题后再判断
        infra_available=infra_ok,
    )

    base_result = {
        "enabled": infra_ok,
        "source_question_id": question_id,
        "strategy": "fallback",
        "recommendations": [],
    }

    if not decision.execute:
        logger.info(
            "[VectorDecision] search_similar mode=%s reason=%s uid=%s qid=%d → skip",
            decision.mode, decision.reason, user_id, question_id,
        )
        return base_result

    # 获取源题
    source = await db.execute(
        select(Question).where(Question.id == question_id, Question.is_active)
    )
    source_q = source.scalar_one_or_none()
    if not source_q:
        return base_result

    subject_code = source_q.subject_ref.code if source_q.subject_ref else ""

    # 二次决策：基于 subject 判断 allowlist
    if decision.mode == "allowlist":
        decision = decide_vector_access(
            user_id=user_id,
            subject=subject_code,
            infra_available=infra_ok,
        )
        if not decision.execute:
            logger.info(
                "[VectorDecision] search_similar allowlist miss uid=%s subject=%s",
                user_id, subject_code,
            )
            return base_result

    # 确保源题有 embedding
    source_embedding = await _ensure_source_embedding(db, source_q)
    if source_embedding is None:
        return base_result

    # 缓存检查（仅 use_result=True 时读写缓存）
    model = _vs.emb.model
    answer_ver = await _get_user_answer_version(db, user_id)
    cache_key = f"vector:similar:{user_id}:{question_id}:{count}:{exclude_answered}:{no_repeat_days}:{answer_ver}:{model}"

    if decision.use_result:
        cached = await cache.get(cache_key)
        if cached is not None:
            return {
                "enabled": True,
                "source_question_id": question_id,
                "strategy": "vector_plus_rule",
                "recommendations": cached,
            }

    # 向量检索 — SQL 直接 JOIN questions 提前过滤无效题目
    top_k = max(count * 5, _vs.vec.top_k)
    pg_literal = embedding_service.vector_to_pg_literal(source_embedding)

    try:
        # V1: 构建排除子查询，支持 no_repeat_days 时间窗口
        exclude_answered_active = exclude_answered or no_repeat_days
        if exclude_answered_active:
            if no_repeat_days:
                from datetime import timedelta

                from app.core.time_utils import utcnow
                cutoff = utcnow() - timedelta(days=no_repeat_days)
                sql = text("""
                    SELECT qe.question_id, qe.subject, qe.question_type, qe.content_hash,
                           1 - (qe.embedding <=> CAST(:emb AS vector)) AS similarity
                    FROM question_embeddings qe
                    JOIN questions q ON q.id = qe.question_id
                    WHERE qe.question_id != :qid
                      AND q.is_active = true
                      AND q.review_status = 'approved'
                      AND qe.subject = :subject
                      AND qe.embedding_model = :model
                      AND qe.question_id NOT IN (
                          SELECT pr.question_id FROM practice_records pr
                          WHERE pr.user_id = :uid AND pr.answered_at >= :cutoff
                      )
                    ORDER BY qe.embedding <=> CAST(:emb AS vector)
                    LIMIT :top_k
                """)
                result = await db.execute(
                    sql,
                    {
                        "emb": pg_literal,
                        "qid": question_id,
                        "subject": subject_code,
                        "model": model,
                        "uid": user_id,
                        "cutoff": cutoff,
                        "top_k": top_k,
                    },
                )
            else:
                sql = text("""
                    SELECT qe.question_id, qe.subject, qe.question_type, qe.content_hash,
                           1 - (qe.embedding <=> CAST(:emb AS vector)) AS similarity
                    FROM question_embeddings qe
                    JOIN questions q ON q.id = qe.question_id
                    WHERE qe.question_id != :qid
                      AND q.is_active = true
                      AND q.review_status = 'approved'
                      AND qe.subject = :subject
                      AND qe.embedding_model = :model
                      AND qe.question_id NOT IN (
                          SELECT pr.question_id FROM practice_records pr WHERE pr.user_id = :uid
                      )
                    ORDER BY qe.embedding <=> CAST(:emb AS vector)
                    LIMIT :top_k
                """)
                result = await db.execute(
                    sql,
                    {
                        "emb": pg_literal,
                        "qid": question_id,
                        "subject": subject_code,
                        "model": model,
                        "uid": user_id,
                        "top_k": top_k,
                    },
                )
        else:
            sql = text("""
                SELECT qe.question_id, qe.subject, qe.question_type, qe.content_hash,
                       1 - (qe.embedding <=> CAST(:emb AS vector)) AS similarity
                FROM question_embeddings qe
                JOIN questions q ON q.id = qe.question_id
                WHERE qe.question_id != :qid
                  AND q.is_active = true
                  AND q.review_status = 'approved'
                  AND qe.subject = :subject
                  AND qe.embedding_model = :model
                ORDER BY qe.embedding <=> CAST(:emb AS vector)
                LIMIT :top_k
            """)
            result = await db.execute(
                sql,
                {
                    "emb": pg_literal,
                    "qid": question_id,
                    "subject": subject_code,
                    "model": model,
                    "top_k": top_k,
                },
            )
        candidates = result.fetchall()
    except Exception:
        logger.warning("向量检索失败", exc_info=True)
        return base_result

    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
    logger.info(
        "[VectorRecall] search_similar mode=%s use_result=%s candidates=%d elapsed=%.1fms",
        decision.mode, decision.use_result, len(candidates), elapsed_ms,
    )

    # shadow 模式：执行了查询但不使用结果
    if not decision.use_result:
        return base_result

    if not candidates:
        return {
            "enabled": True,
            "source_question_id": question_id,
            "strategy": "vector_plus_rule",
            "recommendations": [],
        }

    # 加载候选题目详情（已通过 SQL JOIN 过滤无效题，这里仅获取详情）
    candidate_ids = [row[0] for row in candidates]
    questions_result = await db.execute(
        select(Question).where(Question.id.in_(candidate_ids))
    )
    questions_map = {q.id: q for q in questions_result.scalars().all()}

    source_kps = set(source_q.knowledge_points or [])

    # 二次排序
    scored = []
    for row in candidates:
        cid, c_subject, c_type, _c_hash, similarity = row[0], row[1], row[2], row[3], row[4]
        q = questions_map.get(cid)
        if not q:
            continue

        if similarity < _vs.vec.similarity_threshold:
            continue

        c_kps = set(q.knowledge_points or [])
        kp_overlap = 1.0 if (source_kps & c_kps) else 0.0
        diff_match = 1.0 if q.difficulty == source_q.difficulty else (0.5 if abs(q.difficulty - source_q.difficulty) == 1 else 0.0)
        type_match = 1.0 if q.question_type == source_q.question_type else 0.0

        recommend_score = (
            similarity * 0.70
            + kp_overlap * 0.15
            + diff_match * 0.10
            + type_match * 0.05
        )

        reasons = []
        if similarity >= 0.5:
            reasons.append("语义相似")
        if source_kps & c_kps:
            reasons.append("同知识点")
        if q.difficulty == source_q.difficulty:
            reasons.append("同难度")
        if q.question_type == source_q.question_type:
            reasons.append("同题型")
        if not reasons:
            reasons.append("向量召回")

        stem = ""
        if isinstance(q.content, dict):
            stem = q.content.get("text", "") or q.content.get("stem", "") or ""

        scored.append({
            "question_id": cid,
            "subject": c_subject,
            "question_type": c_type,
            "stem": stem[:200],
            "knowledge_points": q.knowledge_points or [],
            "difficulty": q.difficulty,
            "similarity": round(float(similarity), 4),
            "recommend_score": round(float(recommend_score), 4),
            "match_reason": " + ".join(reasons),
        })

    scored.sort(key=lambda x: x["recommend_score"], reverse=True)
    recommendations = scored[:count]

    # 写缓存
    await cache.set(cache_key, recommendations, ttl=_vs.vec.cache_ttl_sec)

    return {
        "enabled": True,
        "source_question_id": question_id,
        "strategy": "vector_plus_rule",
        "recommendations": recommendations,
    }


# ── 文本向量召回 ──


async def vector_recall_by_text(
    db: AsyncSession,
    user_id: int,
    subject: str,
    query_text: str,
    count: int = 20,
    exclude_answered: bool = False,
    no_repeat_days: int | None = None,
) -> list[dict]:
    """基于文本的向量召回，用于 smart 模式。

    通过 decide_vector_access() 统一决策。
    SQL 直接 JOIN questions 提前过滤无效题目。
    """
    t0 = time.monotonic()

    infra_ok = await is_vector_enabled(db)
    decision = decide_vector_access(
        user_id=user_id,
        subject=subject,
        infra_available=infra_ok,
    )

    if not decision.execute:
        logger.info(
            "[VectorDecision] vector_recall_by_text mode=%s reason=%s uid=%s subject=%s → skip",
            decision.mode, decision.reason, user_id, subject,
        )
        return []

    query_embedding = await embedding_service.get_embedding(query_text)
    if query_embedding is None:
        logger.warning("smart 模式 query embedding 生成失败")
        return []

    # 缓存检查（仅 use_result=True 时）
    model = _vs.emb.model
    weak_hash = hashlib.sha256(query_text.encode()).hexdigest()[:12]
    answer_ver = await _get_user_answer_version(db, user_id)
    cache_key = f"vector:smart:{user_id}:{subject}:{count}:{exclude_answered}:{no_repeat_days}:{answer_ver}:{weak_hash}:{model}"

    if decision.use_result:
        cached = await cache.get(cache_key)
        if cached is not None:
            return cached

    pg_literal = embedding_service.vector_to_pg_literal(query_embedding)
    top_k = max(count * 3, 50)

    try:
        # V1: 构建排除子查询，支持 no_repeat_days 时间窗口
        exclude_answered_active = exclude_answered or no_repeat_days
        if exclude_answered_active:
            if no_repeat_days:
                from datetime import timedelta

                from app.core.time_utils import utcnow
                cutoff = utcnow() - timedelta(days=no_repeat_days)
                sql = text("""
                    SELECT qe.question_id, qe.subject, qe.question_type,
                           1 - (qe.embedding <=> CAST(:emb AS vector)) AS similarity
                    FROM question_embeddings qe
                    JOIN questions q ON q.id = qe.question_id
                    WHERE q.is_active = true
                      AND q.review_status = 'approved'
                      AND (qe.subject = :subject OR qe.subject LIKE :subject_prefix)
                      AND qe.embedding_model = :model
                      AND qe.question_id NOT IN (
                          SELECT pr.question_id FROM practice_records pr
                          WHERE pr.user_id = :uid AND pr.answered_at >= :cutoff
                      )
                    ORDER BY qe.embedding <=> CAST(:emb AS vector)
                    LIMIT :top_k
                """)
                result = await db.execute(
                    sql,
                    {
                        "emb": pg_literal,
                        "subject": subject,
                        "subject_prefix": f"{subject}-%",
                        "model": model,
                        "uid": user_id,
                        "cutoff": cutoff,
                        "top_k": top_k,
                    },
                )
            else:
                sql = text("""
                    SELECT qe.question_id, qe.subject, qe.question_type,
                           1 - (qe.embedding <=> CAST(:emb AS vector)) AS similarity
                    FROM question_embeddings qe
                    JOIN questions q ON q.id = qe.question_id
                    WHERE q.is_active = true
                      AND q.review_status = 'approved'
                      AND (qe.subject = :subject OR qe.subject LIKE :subject_prefix)
                      AND qe.embedding_model = :model
                      AND qe.question_id NOT IN (
                          SELECT pr.question_id FROM practice_records pr WHERE pr.user_id = :uid
                      )
                    ORDER BY qe.embedding <=> CAST(:emb AS vector)
                    LIMIT :top_k
                """)
                result = await db.execute(
                    sql,
                    {
                        "emb": pg_literal,
                        "subject": subject,
                        "subject_prefix": f"{subject}-%",
                        "model": model,
                        "uid": user_id,
                        "top_k": top_k,
                    },
                )
        else:
            sql = text("""
                SELECT qe.question_id, qe.subject, qe.question_type,
                       1 - (qe.embedding <=> CAST(:emb AS vector)) AS similarity
                FROM question_embeddings qe
                JOIN questions q ON q.id = qe.question_id
                WHERE q.is_active = true
                  AND q.review_status = 'approved'
                  AND (qe.subject = :subject OR qe.subject LIKE :subject_prefix)
                  AND qe.embedding_model = :model
                ORDER BY qe.embedding <=> CAST(:emb AS vector)
                LIMIT :top_k
            """)
            result = await db.execute(
                sql,
                {
                    "emb": pg_literal,
                    "subject": subject,
                    "subject_prefix": f"{subject}-%",
                    "model": model,
                    "top_k": top_k,
                },
            )
        candidates = result.fetchall()
    except Exception:
        logger.warning("smart 向量召回失败", exc_info=True)
        return []

    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
    logger.info(
        "[VectorRecall] vector_recall_by_text mode=%s use_result=%s candidates=%d elapsed=%.1fms",
        decision.mode, decision.use_result, len(candidates), elapsed_ms,
    )

    # shadow 模式：执行了查询但不使用结果
    if not decision.use_result:
        return []

    results = []
    for row in candidates:
        cid, c_subject, c_type, similarity = row[0], row[1], row[2], row[3]
        if similarity < _vs.vec.similarity_threshold:
            continue

        results.append({
            "question_id": cid,
            "subject": c_subject,
            "question_type": c_type,
            "similarity": round(float(similarity), 4),
            "recommend_score": round(float(similarity), 4),
            "match_reason": "智能推荐",
        })

    results = results[:count]

    # 写缓存
    await cache.set(cache_key, results, ttl=_vs.vec.cache_ttl_sec)

    return results


# ── 状态接口 ──


async def get_embedding_status(db: AsyncSession) -> dict:
    """获取向量功能详细状态。

    实际查询 PostgreSQL catalog 检查 extension、表、列类型、维度、索引。
    不发起 embedding 请求。不返回 API key 等敏感信息。
    """
    dialect_name = db.bind.dialect.name if db.bind else "unknown"
    mode = resolve_vector_mode()
    decide_vector_access(infra_available=False)  # 仅获取 mode 信息

    info: dict[str, Any] = {
        "configured": _vs.vec.enabled,
        "mode": mode,
        "execute_enabled": False,
        "result_enabled": False,
        "database": dialect_name,
        "extension_installed": False,
        "table_exists": False,
        "index_exists": False,
        "configured_dimension": _vs.emb.dim,
        "database_dimension": None,
        "dimension_matches": None,
        "embedding_model": _vs.emb.model,
        "embedding_api_configured": bool(
            _vs.emb.api_key and _vs.emb.base_url and _vs.emb.model
        ),
        "allowlist_configured": bool(_vs.vec.allowlist and _vs.vec.allowlist.strip()),
        "healthy": False,
        "issues": [],
        "total_embeddings": 0,
        "total_questions": 0,
    }

    issues: list[str] = []

    if dialect_name != "postgresql":
        issues.append(f"database dialect is {dialect_name}, not postgresql")
        info["issues"] = issues
        return info

    try:
        # 检查 vector extension
        result = await db.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        )
        if result.scalar() is not None:
            info["extension_installed"] = True
        else:
            issues.append("pgvector extension not installed")

        # 检查表
        result = await db.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'question_embeddings'"
            )
        )
        if result.scalar() is not None:
            info["table_exists"] = True

            # 检查实际维度
            try:
                await db.execute(text(
                    "SELECT character_maximum_length "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'question_embeddings' AND column_name = 'embedding'"
                ))
                # pgvector 维度不能从 character_maximum_length 获取
                # 尝试从数据推断
                count_result = await db.execute(
                    text("SELECT COUNT(*) FROM question_embeddings")
                )
                info["total_embeddings"] = count_result.scalar() or 0

                # 尝试获取第一条记录的维度
                sample_result = await db.execute(
                    text(
                        "SELECT embedding_dim FROM question_embeddings LIMIT 1"
                    )
                )
                sample_dim = sample_result.scalar()
                if sample_dim is not None:
                    info["database_dimension"] = sample_dim
                    info["dimension_matches"] = (sample_dim == _vs.emb.dim)
                    if not info["dimension_matches"]:
                        issues.append(
                            f"dimension mismatch: configured={_vs.emb.dim}, "
                            f"database={sample_dim}"
                        )
            except Exception:
                pass

            # 检查 HNSW 索引
            try:
                idx_result = await db.execute(text(
                    "SELECT 1 FROM pg_indexes "
                    "WHERE tablename = 'question_embeddings' "
                    "AND indexname LIKE '%hnsw%'"
                ))
                if idx_result.scalar() is not None:
                    info["index_exists"] = True
                else:
                    issues.append("HNSW index not found")
            except Exception:
                issues.append("could not check index status")
        else:
            issues.append("question_embeddings table does not exist")

    except Exception:
        issues.append("failed to query database status")
        logger.warning("获取向量状态失败", exc_info=True)

    # 总题数
    try:
        result = await db.execute(
            select(func.count(Question.id)).where(
                Question.is_active,
                Question.review_status == "approved",
            )
        )
        info["total_questions"] = result.scalar() or 0
    except Exception:
        pass

    # 综合判断
    decision_full = decide_vector_access(infra_available=await is_vector_enabled(db))
    info["execute_enabled"] = decision_full.execute
    info["result_enabled"] = decision_full.use_result
    info["healthy"] = (
        info["configured"]
        and info["extension_installed"]
        and info["table_exists"]
        and info["embedding_api_configured"]
        and (info["dimension_matches"] is not False)
    )
    info["issues"] = issues

    return info


# ── VECTOR_MODE 解析 ──

_VALID_MODES = {"off", "shadow", "allowlist", "all"}


def resolve_vector_mode() -> str:
    """解析当前 VECTOR_MODE。

    优先级：
    1. VECTOR_MODE 显式设置（非默认 "off"）→ 使用 VECTOR_MODE
    2. VECTOR_ENABLED=True 且 VECTOR_MODE="off" → 兼容为 "all"
    3. 否则 → "off"
    """
    mode = (_vs.vec.mode or "off").strip().lower()
    if mode not in _VALID_MODES:
        logger.warning("VECTOR_MODE=%s 无效，回退为 off", mode)
        mode = "off"

    if _vs.vec.enabled and mode == "off":
        return "all"

    return mode


def is_shadow_mode() -> bool:
    """判断当前是否为 shadow 模式。"""
    return resolve_vector_mode() == "shadow"


# ── allowlist 解析 ──


def _parse_allowlist() -> dict:
    """解析 VECTOR_ALLOWLIST JSON 配置。

    返回:
        {"user_ids": list[int], "subjects": list[str]}
    """
    raw = (_vs.vec.allowlist or "").strip()
    if not raw:
        return {"user_ids": [], "subjects": []}

    try:
        parsed = _json.loads(raw)
        if not isinstance(parsed, list):
            return {"user_ids": [], "subjects": []}

        user_ids: list[int] = []
        subjects: list[str] = []
        for item in parsed:
            if isinstance(item, int):
                user_ids.append(item)
            elif isinstance(item, str):
                stripped = item.strip()
                if stripped:
                    subjects.append(stripped.lower())
        return {"user_ids": user_ids, "subjects": subjects}
    except (_json.JSONDecodeError, ValueError):
        logger.warning("VECTOR_ALLOWLIST 解析失败: %s", raw)
        return {"user_ids": [], "subjects": []}


def _is_allowlist_empty() -> bool:
    """检查 allowlist 是否为空。"""
    al = _parse_allowlist()
    return not al["user_ids"] and not al["subjects"]


def _allowlist_matches(user_id: int | None = None, subject: str | None = None) -> bool:
    """检查 user_id 或 subject 是否命中 allowlist。

    subject 匹配时忽略大小写和首尾空格。
    """
    al = _parse_allowlist()
    if not al["user_ids"] and not al["subjects"]:
        return False

    if user_id is not None and user_id in al["user_ids"]:
        return True
    if subject is not None:
        normalized_subject = subject.strip().lower()
        if normalized_subject in al["subjects"]:
            return True
    return False


def is_vector_allowed_for(user_id: int | None = None, subject: str | None = None) -> bool:
    """检查指定用户或科目是否被允许使用向量检索。

    非 allowlist 模式总是返回 True。
    allowlist 模式：空 allowlist 全部拒绝；否则按 user_ids / subjects 过滤。
    """
    mode = resolve_vector_mode()
    if mode != "allowlist":
        return True

    # 空 allowlist = 全部拒绝（安全默认）
    if _is_allowlist_empty():
        return False

    return _allowlist_matches(user_id=user_id, subject=subject)

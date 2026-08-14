"""向量召回服务：向量检索、相似题推荐、智能刷题召回。"""

import hashlib
import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.cache import cache
from app.core.config import settings
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.services import embedding_service
from app.services.admin_subject_service import resolve_subject_ids
from app.services.knowledge_point_service import load_question_kps
from app.services.vector_config_service import EmbeddingConfig, VectorSearchConfig

logger = logging.getLogger("postgraduate-ai.vector_retrieval")

# 模块级缓存：避免每次请求都查询 pgvector 可用性（TTL 60 秒）
_vector_enabled_cache: dict[str, Any] = {
    "value": None,
    "checked": False,
    "checked_at": 0.0,
    "config_key": None,
}

_VECTOR_CACHE_TTL = 60  # 秒


# ---------------------------------------------------------------------------
# DB-first 配置访问器（同步 + TTL 缓存）
# 所有 settings.VECTOR_* / settings.EMBEDDING_* 引用通过此访问器间接获取，
# 优先从 DB 读取，环境变量仅作为兜底。
# ---------------------------------------------------------------------------


class _VectorSettings:
    """DB-first vector runtime configuration with a short process-local TTL.

    Vector search parameters come from ``admin_ai_configs``. Embedding model
    identity and credentials are resolved from ``admin_ai_model_configs`` via
    ``embedding_model_config_id`` / the ``embedding`` capability.
    """

    _cached: Any = None
    _cached_at: float = 0
    _TTL = 30  # seconds

    async def refresh_async(self, db: AsyncSession) -> None:
        """Refresh vector + embedding runtime config from DB."""
        now = time.monotonic()
        if self._cached and (now - self._cached_at) < self._TTL:
            return
        if hasattr(db, "_mock_name") or hasattr(db, "assert_called"):
            return

        try:
            from app.models.admin_ai_config import AdminAiConfig
            from app.services.vector_config_service import resolve_embedding_config

            result = await db.execute(select(AdminAiConfig))
            configs = {r.config_key: r.config_value for r in result.scalars().all()}
            vec = VectorSearchConfig(
                enabled=configs.get("vector_enabled", "false").lower() == "true",
                mode=(configs.get("vector_mode") or "off").strip().lower(),
                allowlist=configs.get("vector_allowlist", ""),
                cache_ttl_sec=int(configs.get("vector_cache_ttl_sec", 300)),
                top_k=int(configs.get("vector_top_k", 100)),
                similarity_threshold=float(configs.get("vector_similarity_threshold", "0.15")),
            )
            emb = await resolve_embedding_config(db)
            self._cached = {"vec": vec, "emb": emb}
            self._cached_at = now
        except BaseException:
            logger.debug("DB 向量配置读取失败，使用环境变量兜底", exc_info=True)

    @property
    def emb(self):
        if self._cached and "emb" in self._cached:
            return self._cached["emb"]
        return EmbeddingConfig(
            api_key="",
            base_url=settings.EMBEDDING_BASE_URL,
            model=settings.EMBEDDING_MODEL,
            dim=settings.EMBEDDING_DIM,
            timeout=settings.EMBEDDING_TIMEOUT,
            batch_size=settings.EMBEDDING_BATCH_SIZE,
            provider=settings.EMBEDDING_PROVIDER,
            model_config_id=None,
        )

    @property
    def vec(self):
        if self._cached and "vec" in self._cached:
            return self._cached["vec"]
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
    _vector_enabled_cache["config_key"] = None
    # 同步清理 DB-first 配置缓存
    _vs._cached = None
    _vs._cached_at = 0


def _dialect_name(db: AsyncSession) -> str:
    """安全获取当前 Session 的数据库 dialect。"""
    try:
        bind = db.get_bind()
    except (AttributeError, TypeError):
        bind = getattr(db, "bind", None)
    return bind.dialect.name if bind is not None else "unknown"


_VECTOR_TYPE_RE = re.compile(r"^vector\((\d+)\)$", re.IGNORECASE)


def _parse_vector_dimension(type_name: object) -> int | None:
    """从 PostgreSQL ``format_type`` 结果解析 vector 维度。"""
    if not isinstance(type_name, str):
        return None
    match = _VECTOR_TYPE_RE.fullmatch(type_name.strip())
    return int(match.group(1)) if match else None


async def _get_vector_column_dimension(db: AsyncSession) -> int | None:
    """读取当前 schema 中 question_embeddings.embedding 的物理维度。"""
    result = await db.execute(text("""
        SELECT pg_catalog.format_type(a.atttypid, a.atttypmod)
        FROM pg_catalog.pg_attribute a
        JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = current_schema()
          AND c.relname = 'question_embeddings'
          AND a.attname = 'embedding'
          AND a.attnum > 0
          AND NOT a.attisdropped
        LIMIT 1
    """))
    return _parse_vector_dimension(result.scalar())


async def _resolve_question_subject_code(
    db: AsyncSession,
    question: Question,
) -> str:
    """获取题目科目代码；relationship 未预加载时按 subject_id 回查。"""
    subject_ref = getattr(question, "subject_ref", None)
    if subject_ref is not None and getattr(subject_ref, "code", None):
        return str(subject_ref.code)

    subject_id = getattr(question, "subject_id", None)
    if subject_id is None:
        return ""

    from app.models.admin import Subject

    result = await db.execute(
        select(Subject.code).where(Subject.id == subject_id)
    )
    return str(result.scalar() or "")


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
    """统一向量访问决策。所有向量入口必须调用此函数。

    向量检索始终全局启用（mode=all），不再支持影子模式或科目白名单。
    """
    if not infra_available:
        return VectorDecision(
            enabled=False, execute=False, use_result=False,
            mode="all", reason="infra_unavailable",
        )

    return VectorDecision(
        enabled=True, execute=True, use_result=True,
        mode="all", reason="mode_all",
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

    config_key = (
        _vs.vec.enabled,
        _vs.emb.base_url,
        _vs.emb.model,
        _vs.emb.dim,
        bool(_vs.emb.api_key),
    )

    # 使用缓存避免重复查询（TTL 60 秒）；配置变化后不得复用旧结果。
    if (
        _vector_enabled_cache["checked"]
        and _vector_enabled_cache["config_key"] == config_key
    ):
        elapsed = time.monotonic() - _vector_enabled_cache["checked_at"]
        if elapsed < _VECTOR_CACHE_TTL:
            return bool(_vector_enabled_cache["value"])

    try:
        dialect_name = _dialect_name(db)
        if dialect_name != "postgresql":
            _vector_enabled_cache["value"] = False
            _vector_enabled_cache["checked"] = True
            _vector_enabled_cache["checked_at"] = time.monotonic()
            _vector_enabled_cache["config_key"] = config_key
            return False

        result = await db.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        )
        if result.scalar() is None:
            _vector_enabled_cache["value"] = False
            _vector_enabled_cache["checked"] = True
            _vector_enabled_cache["checked_at"] = time.monotonic()
            _vector_enabled_cache["config_key"] = config_key
            return False

        result = await db.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'question_embeddings'"
            )
        )
        if result.scalar() is None:
            _vector_enabled_cache["value"] = False
            _vector_enabled_cache["checked"] = True
            _vector_enabled_cache["checked_at"] = time.monotonic()
            _vector_enabled_cache["config_key"] = config_key
            return False

        database_dim = await _get_vector_column_dimension(db)
        if database_dim != _vs.emb.dim:
            logger.warning(
                "pgvector 维度不匹配: configured=%s database=%s",
                _vs.emb.dim,
                database_dim,
            )
            _vector_enabled_cache["value"] = False
            _vector_enabled_cache["checked"] = True
            _vector_enabled_cache["checked_at"] = time.monotonic()
            _vector_enabled_cache["config_key"] = config_key
            return False

        _vector_enabled_cache["value"] = True
        _vector_enabled_cache["checked"] = True
        _vector_enabled_cache["checked_at"] = time.monotonic()
        _vector_enabled_cache["config_key"] = config_key
        return True

    except Exception:
        logger.warning("检查向量功能可用性时出错", exc_info=True)
        _vector_enabled_cache["value"] = False
        _vector_enabled_cache["checked"] = True
        _vector_enabled_cache["checked_at"] = time.monotonic()
        _vector_enabled_cache["config_key"] = config_key
        return False


# ── upsert ──


async def upsert_question_embedding(
    db: AsyncSession, question: Question, force: bool = False
) -> dict:
    """为单个题目生成并存储 embedding。

    返回:
        {"question_id": int, "status": "created"|"updated"|"skipped"|"failed", "reason": str}
    """
    await _vs.refresh_async(db)

    qid = question.id
    model = _vs.emb.model
    subject_id = getattr(question, "subject_id", None)

    try:
        subject_code = await _resolve_question_subject_code(db, question)
        kp_map = await load_question_kps(db, [question.id])
        content_text = embedding_service.build_question_embedding_text(
            question,
            subject_code=subject_code,
            knowledge_points=kp_map.get(question.id, []),
        )
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

        embedding = await embedding_service.get_embedding(
            content_text,
            config=_vs.emb,
        )
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
                    "subject_id = :subject_id, question_type = :qtype, "
                    "updated_at = NOW(), embedded_at = NOW() "
                    "WHERE question_id = :qid AND embedding_model = :model"
                ),
                {
                    "hash": content_hash,
                    "text": content_text,
                    "emb": pg_literal,
                    "dim": dim,
                    "subject_id": subject_id,
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
                    "(question_id, subject_id, question_type, embedding_model, embedding_dim, "
                    "content_hash, content_text, embedding) "
                    "VALUES (:qid, :subject_id, :qtype, :model, :dim, :hash, :text, CAST(:emb AS vector))"
                ),
                {
                    "qid": qid,
                    "subject_id": subject_id,
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

    except SQLAlchemyError:
        # 让调用方的 SAVEPOINT 看见数据库异常并正确回滚，避免事务停留在
        # aborted 状态。非批量调用方会在上层降级为规则推荐。
        logger.warning(
            "upsert embedding database error for question_id=%d",
            qid,
            exc_info=True,
        )
        raise
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
        # 查询当前 model 下缺少“可召回”embedding 的题目。历史版本可能
        # 因 subject_ref 未预加载写入空 subject，也必须自动进入修复批次。
        conditions.append(
            ~Question.id.in_(
                select(text("question_id")).select_from(text("question_embeddings")).where(
                    text(
                        "embedding_model = :embedding_model "
                        "AND embedding_dim = :embedding_dim "
                        "AND subject_id IS NOT NULL"
                    )
                )
            )
        )

    query = (
        select(Question)
        .where(and_(*conditions))
        .options(selectinload(Question.subject_ref))
        .order_by(Question.id.asc())
        .limit(limit + 1)
    )

    query_params = (
        {
            "embedding_model": _vs.emb.model,
            "embedding_dim": _vs.emb.dim,
        }
        if not force
        else {}
    )
    result = await db.execute(query, query_params)
    fetched_questions = list(result.scalars().all())
    has_more = len(fetched_questions) > limit
    questions = fetched_questions[:limit]

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

    # 不存在，尝试生成。用 SAVEPOINT 隔离现场写入失败，确保后续规则
    # fallback 仍可继续使用当前 Session。
    try:
        async with db.begin_nested():
            res = await upsert_question_embedding(db, question)
    except SQLAlchemyError:
        logger.warning(
            "现场生成源题 embedding 失败 question_id=%d",
            question.id,
            exc_info=True,
        )
        return None
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
    """返回用户答题缓存版本号。

    版本由 ``invalidate_vector_cache`` 在 Redis 上递增（每次答题 +1），
    使该用户旧的向量推荐缓存 key 全部失效。正常走 Redis（避免每次
    smart/similar 请求做 COUNT(*))；Redis 故障时用 get_strict 抛出后回退到
    practice_records COUNT——DB 全局一致，防止多 worker 各自本地版本发散、
    答题后仍命中本进程陈旧缓存。读取失败时返回 0（不影响核心功能）。
    """
    from app.core.cache import CacheUnavailableError

    try:
        version_key = f"vector:answer_ver:{user_id}"
        current = await cache.get_strict(version_key)
        return int(current) if current else 0
    except CacheUnavailableError:
        try:
            result = await db.execute(
                select(func.count(PracticeRecord.id)).where(
                    PracticeRecord.user_id == user_id
                )
            )
            return result.scalar() or 0
        except Exception:
            return 0
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
        try:
            new_ver = (int(current) + 1) if current else 1
        except (TypeError, ValueError):
            new_ver = 1
        # 版本 key TTL 需长于推荐缓存 TTL：否则版本过期归零后新纪元计数会与
        # 旧纪元缓存 key 碰撞（vector_cache_ttl_sec 可配置 > 86400）。
        await cache.set(version_key, new_ver, ttl=30 * 86400)
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
        select(Question)
        .where(Question.id == question_id, Question.is_active)
        .options(selectinload(Question.subject_ref))
    )
    source_q = source.scalar_one_or_none()
    if not source_q:
        return base_result

    subject_id = getattr(source_q, "subject_id", None)

    # 确保源题有 embedding
    try:
        source_embedding = await _ensure_source_embedding(db, source_q)
    except SQLAlchemyError:
        logger.warning(
            "源题 embedding 读取或生成失败 question_id=%d",
            question_id,
            exc_info=True,
        )
        return base_result
    if source_embedding is None:
        return base_result

    try:
        source_embedding = validate_embedding(source_embedding, _vs.emb.dim)
    except ValueError:
        logger.warning("源题 embedding 维度或数值非法 question_id=%d", question_id)
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
                    SELECT qe.question_id, s.code AS subject, qe.question_type, qe.content_hash,
                           1 - (qe.embedding <=> CAST(:emb AS vector)) AS similarity
                    FROM question_embeddings qe
                    JOIN questions q ON q.id = qe.question_id
                    JOIN subjects s ON s.id = qe.subject_id
                    WHERE qe.question_id != :qid
                      AND q.is_active = true
                      AND q.review_status = 'approved'
                      AND qe.subject_id = :subject_id
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
                        "subject_id": subject_id,
                        "model": model,
                        "uid": user_id,
                        "cutoff": cutoff,
                        "top_k": top_k,
                    },
                )
            else:
                sql = text("""
                    SELECT qe.question_id, s.code AS subject, qe.question_type, qe.content_hash,
                           1 - (qe.embedding <=> CAST(:emb AS vector)) AS similarity
                    FROM question_embeddings qe
                    JOIN questions q ON q.id = qe.question_id
                    JOIN subjects s ON s.id = qe.subject_id
                    WHERE qe.question_id != :qid
                      AND q.is_active = true
                      AND q.review_status = 'approved'
                      AND qe.subject_id = :subject_id
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
                        "subject_id": subject_id,
                        "model": model,
                        "uid": user_id,
                        "top_k": top_k,
                    },
                )
        else:
            sql = text("""
                SELECT qe.question_id, s.code AS subject, qe.question_type, qe.content_hash,
                       1 - (qe.embedding <=> CAST(:emb AS vector)) AS similarity
                FROM question_embeddings qe
                JOIN questions q ON q.id = qe.question_id
                JOIN subjects s ON s.id = qe.subject_id
                WHERE qe.question_id != :qid
                  AND q.is_active = true
                  AND q.review_status = 'approved'
                  AND qe.subject_id = :subject_id
                  AND qe.embedding_model = :model
                ORDER BY qe.embedding <=> CAST(:emb AS vector)
                LIMIT :top_k
            """)
            result = await db.execute(
                sql,
                {
                    "emb": pg_literal,
                    "qid": question_id,
                    "subject_id": subject_id,
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

    kp_map = await load_question_kps(db, [question_id] + candidate_ids)
    source_kps = set(kp_map.get(question_id, []))

    # 二次排序
    scored = []
    for row in candidates:
        cid, c_subject, c_type, _c_hash, similarity = row[0], row[1], row[2], row[3], row[4]
        q = questions_map.get(cid)
        if not q:
            continue

        if similarity < _vs.vec.similarity_threshold:
            continue

        c_kps = set(kp_map.get(cid, []))
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
            "knowledge_points": kp_map.get(cid, []),
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

    # 按 subject 解析 id 集（父科目自动包含子科目）。subject 无法解析时
    # 无候选可召回，直接返回。
    subject_ids = await resolve_subject_ids(db, subject)
    if not subject_ids:
        return []

    query_embedding = await embedding_service.get_embedding(
        query_text,
        config=_vs.emb,
    )
    if query_embedding is None:
        logger.warning("smart 模式 query embedding 生成失败")
        return []

    try:
        query_embedding = validate_embedding(query_embedding, _vs.emb.dim)
    except ValueError:
        logger.warning("smart 模式 query embedding 维度或数值非法")
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
    top_k = max(count * 3, _vs.vec.top_k)

    try:
        # V1: 构建排除子查询，支持 no_repeat_days 时间窗口
        exclude_answered_active = exclude_answered or no_repeat_days
        if exclude_answered_active:
            if no_repeat_days:
                from datetime import timedelta

                from app.core.time_utils import utcnow
                cutoff = utcnow() - timedelta(days=no_repeat_days)
                sql = text("""
                    SELECT qe.question_id, s.code AS subject, qe.question_type,
                           1 - (qe.embedding <=> CAST(:emb AS vector)) AS similarity
                    FROM question_embeddings qe
                    JOIN questions q ON q.id = qe.question_id
                    JOIN subjects s ON s.id = qe.subject_id
                    WHERE q.is_active = true
                      AND q.review_status = 'approved'
                      AND qe.subject_id = ANY(:subject_ids)
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
                        "subject_ids": subject_ids,
                        "model": model,
                        "uid": user_id,
                        "cutoff": cutoff,
                        "top_k": top_k,
                    },
                )
            else:
                sql = text("""
                    SELECT qe.question_id, s.code AS subject, qe.question_type,
                           1 - (qe.embedding <=> CAST(:emb AS vector)) AS similarity
                    FROM question_embeddings qe
                    JOIN questions q ON q.id = qe.question_id
                    JOIN subjects s ON s.id = qe.subject_id
                    WHERE q.is_active = true
                      AND q.review_status = 'approved'
                      AND qe.subject_id = ANY(:subject_ids)
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
                        "subject_ids": subject_ids,
                        "model": model,
                        "uid": user_id,
                        "top_k": top_k,
                    },
                )
        else:
            sql = text("""
                SELECT qe.question_id, s.code AS subject, qe.question_type,
                       1 - (qe.embedding <=> CAST(:emb AS vector)) AS similarity
                FROM question_embeddings qe
                JOIN questions q ON q.id = qe.question_id
                JOIN subjects s ON s.id = qe.subject_id
                WHERE q.is_active = true
                  AND q.review_status = 'approved'
                  AND qe.subject_id = ANY(:subject_ids)
                  AND qe.embedding_model = :model
                ORDER BY qe.embedding <=> CAST(:emb AS vector)
                LIMIT :top_k
            """)
            result = await db.execute(
                sql,
                {
                    "emb": pg_literal,
                    "subject_ids": subject_ids,
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
    await _vs.refresh_async(db)

    dialect_name = _dialect_name(db)
    mode = resolve_vector_mode()

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
                "WHERE table_schema = current_schema() "
                "AND table_name = 'question_embeddings'"
            )
        )
        if result.scalar() is not None:
            info["table_exists"] = True

            # 从列类型读取实际物理维度；即使表中还没有数据也能正确判断。
            try:
                database_dim = await _get_vector_column_dimension(db)
                info["database_dimension"] = database_dim
                info["dimension_matches"] = (database_dim == _vs.emb.dim)
                if not info["dimension_matches"]:
                    issues.append(
                        f"dimension mismatch: configured={_vs.emb.dim}, "
                        f"database={database_dim}"
                    )

                count_result = await db.execute(
                    text(
                        "SELECT COUNT(*) FROM question_embeddings "
                        "WHERE embedding_model = :model"
                    ),
                    {"model": _vs.emb.model},
                )
                info["total_embeddings"] = count_result.scalar() or 0
            except Exception:
                issues.append("could not inspect vector dimension or embedding count")

            # 检查 HNSW 索引
            try:
                idx_result = await db.execute(text(
                    "SELECT 1 FROM pg_indexes "
                    "WHERE schemaname = current_schema() "
                    "AND tablename = 'question_embeddings' "
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
    if not info["configured"]:
        issues.append("vector search is disabled")
    if not info["embedding_api_configured"]:
        issues.append("embedding API is not fully configured")
    if info["table_exists"] and info["total_embeddings"] == 0:
        issues.append(
            f"no embeddings found for model {_vs.emb.model}; run embedding backfill"
        )

    info["healthy"] = bool(
        decision_full.enabled
        and info["dimension_matches"] is True
        and info["total_embeddings"] > 0
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


def is_vector_allowed_for(user_id=None, subject=None):
    """向量检索始终对所有用户/科目开放（allowlist 已移除）。"""
    return True

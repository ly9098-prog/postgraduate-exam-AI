"""向量召回服务：向量检索、相似题推荐、智能刷题召回。"""

import hashlib
import json as _json
import logging
import time
from typing import Any

from sqlalchemy import text, select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.cache import cache
from app.models.question import Question
from app.services import embedding_service

logger = logging.getLogger("postgraduate-ai.vector_retrieval")

# 模块级缓存：避免每次请求都查询 pgvector 可用性（TTL 60 秒）
_vector_enabled_cache: dict[str, Any] = {"value": None, "checked": False, "checked_at": 0.0}

_VECTOR_CACHE_TTL = 60  # 秒


def _reset_vector_enabled_cache():
    """重置向量可用性缓存（用于测试或配置变更后）。"""
    _vector_enabled_cache["value"] = None
    _vector_enabled_cache["checked"] = False
    _vector_enabled_cache["checked_at"] = 0.0


async def is_vector_enabled(db: AsyncSession) -> bool:
    """判断向量功能是否可用。

    条件：
    - settings.VECTOR_ENABLED == True
    - 数据库 dialect 是 postgresql
    - EMBEDDING_API_KEY、EMBEDDING_BASE_URL、EMBEDDING_MODEL 已配置
    - question_embeddings 表存在
    - pgvector 扩展可用
    """
    # 基础配置检查（不依赖数据库）
    if not settings.VECTOR_ENABLED:
        return False

    if not (
        settings.EMBEDDING_API_KEY
        and settings.EMBEDDING_BASE_URL
        and settings.EMBEDDING_MODEL
    ):
        return False

    # 使用缓存避免重复查询（TTL 60 秒）
    if _vector_enabled_cache["checked"]:
        elapsed = time.monotonic() - _vector_enabled_cache["checked_at"]
        if elapsed < _VECTOR_CACHE_TTL:
            return bool(_vector_enabled_cache["value"])
        # 缓存过期，重新检查

    try:
        # 检查 dialect
        dialect_name = db.bind.dialect.name if db.bind else "unknown"
        if dialect_name != "postgresql":
            _vector_enabled_cache["value"] = False
            _vector_enabled_cache["checked"] = True
            _vector_enabled_cache["checked_at"] = time.monotonic()
            return False

        # 检查 pgvector 扩展
        result = await db.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        )
        if result.scalar() is None:
            _vector_enabled_cache["value"] = False
            _vector_enabled_cache["checked"] = True
            _vector_enabled_cache["checked_at"] = time.monotonic()
            return False

        # 检查 question_embeddings 表
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


async def upsert_question_embedding(
    db: AsyncSession, question: Question, force: bool = False
) -> dict:
    """为单个题目生成并存储 embedding。

    返回:
        {"question_id": int, "status": "created"|"updated"|"skipped"|"failed", "reason": str}
    """
    qid = question.id
    model = settings.EMBEDDING_MODEL

    try:
        # 构造 embedding 文本
        content_text = embedding_service.build_question_embedding_text(question)
        content_hash = embedding_service.compute_content_hash(content_text)

        # 查询是否已有该 question_id + model 的记录
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

        # 调用 embedding API
        embedding = await embedding_service.get_embedding(content_text)
        if embedding is None:
            return {"question_id": qid, "status": "failed", "reason": "embedding api failed"}

        pg_literal = embedding_service.vector_to_pg_literal(embedding)
        dim = settings.EMBEDDING_DIM

        # UPSERT
        if existing:
            await db.execute(
                text(
                    "UPDATE question_embeddings SET "
                    "content_hash = :hash, content_text = :text, "
                    "embedding = :emb::vector, embedding_dim = :dim, "
                    "subject = :subject, question_type = :qtype, "
                    "updated_at = NOW(), embedded_at = NOW() "
                    "WHERE question_id = :qid AND embedding_model = :model"
                ),
                {
                    "hash": content_hash,
                    "text": content_text,
                    "emb": pg_literal,
                    "dim": dim,
                    "subject": question.subject,
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
                    "VALUES (:qid, :subject, :qtype, :model, :dim, :hash, :text, :emb::vector)"
                ),
                {
                    "qid": qid,
                    "subject": question.subject,
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


async def backfill_question_embeddings(
    db: AsyncSession,
    subject: str | None = None,
    limit: int = 100,
    force: bool = False,
) -> dict:
    """批量为题目生成 embedding。

    查询 is_active=True 且 review_status='approved' 的题目。
    """
    # 检查向量功能
    if not await is_vector_enabled(db):
        return {
            "total": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "enabled": False,
        }

    limit = min(max(1, limit), 1000)

    # 构建查询条件
    conditions = [
        Question.is_active == True,
        Question.review_status == "approved",
    ]

    if subject:
        conditions.append(
            or_(
                Question.subject == subject,
                Question.subject.like(f"{subject}-%"),
            )
        )

    result = await db.execute(
        select(Question).where(and_(*conditions)).limit(limit)
    )
    questions = list(result.scalars().all())

    stats = {"total": len(questions), "created": 0, "updated": 0, "skipped": 0, "failed": 0}
    errors: list[str] = []

    for q in questions:
        res = await upsert_question_embedding(db, q, force=force)
        status = res["status"]
        if status in stats:
            stats[status] += 1
        if status == "failed" and res.get("reason"):
            errors.append(f"question_id={q.id}: {res['reason']}")

    return {**stats, "enabled": True, "errors": errors}


async def _ensure_source_embedding(
    db: AsyncSession, question: Question
) -> list[float] | None:
    """确保源题有 embedding，如果没有则尝试现场生成。"""
    model = settings.EMBEDDING_MODEL

    # 先查询是否已有
    result = await db.execute(
        text(
            "SELECT embedding::text FROM question_embeddings "
            "WHERE question_id = :qid AND embedding_model = :model"
        ),
        {"qid": question.id, "model": model},
    )
    row = result.first()
    if row:
        # 解析 pgvector 文本格式 "[0.1,0.2,...]"
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
        # 重新查询
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


async def search_similar_questions(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    count: int = 5,
    exclude_answered: bool = True,
) -> dict:
    """向量相似题检索 + 二次排序。

    返回:
        {
            "enabled": bool,
            "source_question_id": int,
            "strategy": "vector_plus_rule",
            "recommendations": [...]
        }
    """
    if not await is_vector_enabled(db):
        return {"enabled": False, "source_question_id": question_id, "strategy": "fallback", "recommendations": []}

    # 获取源题
    source = await db.execute(
        select(Question).where(Question.id == question_id, Question.is_active == True)
    )
    source_q = source.scalar_one_or_none()
    if not source_q:
        return {"enabled": False, "source_question_id": question_id, "strategy": "fallback", "recommendations": []}

    # 确保源题有 embedding
    source_embedding = await _ensure_source_embedding(db, source_q)
    if source_embedding is None:
        return {"enabled": False, "source_question_id": question_id, "strategy": "fallback", "recommendations": []}

    # 缓存检查
    model = settings.EMBEDDING_MODEL
    cache_key = f"vector:similar:{user_id}:{question_id}:{count}:{exclude_answered}:{model}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return {
            "enabled": True,
            "source_question_id": question_id,
            "strategy": "vector_plus_rule",
            "recommendations": cached,
        }

    # 向量检索（已做题排除通过 SQL 子查询实现，避免全量加载到内存）
    top_k = max(count * 5, settings.VECTOR_TOP_K)
    pg_literal = embedding_service.vector_to_pg_literal(source_embedding)

    try:
        if exclude_answered:
            sql = text("""
                SELECT qe.question_id, qe.subject, qe.question_type, qe.content_hash,
                       1 - (qe.embedding <=> :emb::vector) AS similarity
                FROM question_embeddings qe
                WHERE qe.question_id != :qid
                  AND qe.subject = :subject
                  AND qe.embedding_model = :model
                  AND qe.question_id NOT IN (
                      SELECT pr.question_id FROM practice_records pr WHERE pr.user_id = :uid
                  )
                ORDER BY qe.embedding <=> :emb::vector
                LIMIT :top_k
            """)
            result = await db.execute(
                sql,
                {
                    "emb": pg_literal,
                    "qid": question_id,
                    "subject": source_q.subject,
                    "model": model,
                    "uid": user_id,
                    "top_k": top_k,
                },
            )
        else:
            sql = text("""
                SELECT qe.question_id, qe.subject, qe.question_type, qe.content_hash,
                       1 - (qe.embedding <=> :emb::vector) AS similarity
                FROM question_embeddings qe
                WHERE qe.question_id != :qid
                  AND qe.subject = :subject
                  AND qe.embedding_model = :model
                ORDER BY qe.embedding <=> :emb::vector
                LIMIT :top_k
            """)
            result = await db.execute(
                sql,
                {
                    "emb": pg_literal,
                    "qid": question_id,
                    "subject": source_q.subject,
                    "model": model,
                    "top_k": top_k,
                },
            )
        candidates = result.fetchall()
    except Exception:
        logger.warning("向量检索失败", exc_info=True)
        return {"enabled": False, "source_question_id": question_id, "strategy": "fallback", "recommendations": []}

    if not candidates:
        return {"enabled": True, "source_question_id": question_id, "strategy": "vector_plus_rule", "recommendations": []}

    # 加载候选题目详情
    candidate_ids = [row[0] for row in candidates]
    questions_result = await db.execute(
        select(Question).where(
            Question.id.in_(candidate_ids),
            Question.is_active == True,
            Question.review_status == "approved",
        )
    )
    questions_map = {q.id: q for q in questions_result.scalars().all()}

    source_kps = set(source_q.knowledge_points or [])

    # 二次排序
    scored = []
    for row in candidates:
        cid, c_subject, c_type, c_hash, similarity = row[0], row[1], row[2], row[3], row[4]
        q = questions_map.get(cid)
        if not q:
            continue

        if similarity < settings.VECTOR_SIMILARITY_THRESHOLD:
            continue

        # 二次打分
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

        # 匹配原因
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
    await cache.set(cache_key, recommendations, ttl=settings.VECTOR_CACHE_TTL_SEC)

    return {
        "enabled": True,
        "source_question_id": question_id,
        "strategy": "vector_plus_rule",
        "recommendations": recommendations,
    }


async def vector_recall_by_text(
    db: AsyncSession,
    user_id: int,
    subject: str,
    query_text: str,
    count: int = 20,
    exclude_answered: bool = False,
) -> list[dict]:
    """基于文本的向量召回，用于 smart 模式。

    返回 list[dict]，每个 dict 包含 question_id, similarity, recommend_score, match_reason。
    """
    if not await is_vector_enabled(db):
        return []

    # 获取 query embedding
    query_embedding = await embedding_service.get_embedding(query_text)
    if query_embedding is None:
        logger.warning("smart 模式 query embedding 生成失败")
        return []

    # 缓存检查
    model = settings.EMBEDDING_MODEL
    weak_hash = hashlib.sha256(query_text.encode()).hexdigest()[:12]
    cache_key = f"vector:smart:{user_id}:{subject}:{count}:{exclude_answered}:{weak_hash}:{model}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    # 向量检索（已做题排除通过 SQL 子查询实现）
    pg_literal = embedding_service.vector_to_pg_literal(query_embedding)
    top_k = max(count * 3, 50)

    try:
        if exclude_answered:
            sql = text("""
                SELECT qe.question_id, qe.subject, qe.question_type,
                       1 - (qe.embedding <=> :emb::vector) AS similarity
                FROM question_embeddings qe
                JOIN questions q ON q.id = qe.question_id
                WHERE q.is_active = true
                  AND q.review_status = 'approved'
                  AND (qe.subject = :subject OR qe.subject LIKE :subject_prefix)
                  AND qe.embedding_model = :model
                  AND qe.question_id NOT IN (
                      SELECT pr.question_id FROM practice_records pr WHERE pr.user_id = :uid
                  )
                ORDER BY qe.embedding <=> :emb::vector
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
                       1 - (qe.embedding <=> :emb::vector) AS similarity
                FROM question_embeddings qe
                JOIN questions q ON q.id = qe.question_id
                WHERE q.is_active = true
                  AND q.review_status = 'approved'
                  AND (qe.subject = :subject OR qe.subject LIKE :subject_prefix)
                  AND qe.embedding_model = :model
                ORDER BY qe.embedding <=> :emb::vector
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

    results = []
    for row in candidates:
        cid, c_subject, c_type, similarity = row[0], row[1], row[2], row[3]
        if similarity < settings.VECTOR_SIMILARITY_THRESHOLD:
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
    await cache.set(cache_key, results, ttl=settings.VECTOR_CACHE_TTL_SEC)

    return results


async def get_embedding_status(db: AsyncSession) -> dict:
    """获取向量功能状态和统计信息。"""
    dialect_name = db.bind.dialect.name if db.bind else "unknown"

    total_embeddings = 0
    total_questions = 0

    try:
        if dialect_name == "postgresql":
            # 检查表是否存在
            result = await db.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'question_embeddings'"
                )
            )
            if result.scalar() is not None:
                result = await db.execute(
                    text("SELECT COUNT(*) FROM question_embeddings")
                )
                total_embeddings = result.scalar() or 0

        # 总题数
        result = await db.execute(
            select(func.count(Question.id)).where(
                Question.is_active == True,
                Question.review_status == "approved",
            )
        )
        total_questions = result.scalar() or 0
    except Exception:
        logger.warning("获取 embedding 统计失败", exc_info=True)

    return {
        "vector_enabled": settings.VECTOR_ENABLED and dialect_name == "postgresql",
        "db_dialect": dialect_name,
        "embedding_model": settings.EMBEDDING_MODEL,
        "embedding_dim": settings.EMBEDDING_DIM,
        "total_embeddings": total_embeddings,
        "total_questions": total_questions,
    }


# ── VECTOR_MODE 解析 ──

_VALID_MODES = {"off", "shadow", "allowlist", "all"}


def resolve_vector_mode() -> str:
    """解析当前 VECTOR_MODE。

    优先级：
    1. VECTOR_MODE 显式设置（非默认 "off"）→ 使用 VECTOR_MODE
    2. VECTOR_ENABLED=True 且 VECTOR_MODE="off" → 兼容为 "all"
    3. 否则 → "off"

    返回: "off" | "shadow" | "allowlist" | "all"
    """
    mode = (settings.VECTOR_MODE or "off").strip().lower()
    if mode not in _VALID_MODES:
        logger.warning("VECTOR_MODE=%s 无效，回退为 off", mode)
        mode = "off"

    # 向后兼容：VECTOR_ENABLED=True 但 VECTOR_MODE 仍为默认 "off"
    if settings.VECTOR_ENABLED and mode == "off":
        return "all"

    return mode


def is_shadow_mode() -> bool:
    """判断当前是否为 shadow 模式。"""
    return resolve_vector_mode() == "shadow"


def _parse_allowlist() -> dict:
    """解析 VECTOR_ALLOWLIST JSON 配置。

    返回:
        {"user_ids": list[int], "subjects": list[str]}
    """
    raw = (settings.VECTOR_ALLOWLIST or "").strip()
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
                subjects.append(item)
        return {"user_ids": user_ids, "subjects": subjects}
    except (_json.JSONDecodeError, ValueError):
        logger.warning("VECTOR_ALLOWLIST 解析失败: %s", raw)
        return {"user_ids": [], "subjects": []}


def is_vector_allowed_for(user_id: int | None = None, subject: str | None = None) -> bool:
    """检查指定用户或科目是否被允许使用向量检索。

    非 allowlist 模式（all/shadow/off）总是返回 True。
    allowlist 模式：空 allowlist 全部允许；否则按 user_ids / subjects 过滤。
    """
    mode = resolve_vector_mode()
    if mode != "allowlist":
        return True

    allowlist = _parse_allowlist()

    # 空 allowlist = 全部允许
    if not allowlist["user_ids"] and not allowlist["subjects"]:
        return True

    if user_id is not None and user_id in allowlist["user_ids"]:
        return True
    if subject is not None and subject in allowlist["subjects"]:
        return True

    return False

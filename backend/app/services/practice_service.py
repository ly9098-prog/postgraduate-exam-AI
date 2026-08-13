import hashlib
import logging
import random
from datetime import date, datetime, timedelta

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.time_utils import normalize_to_naive_utc, utcnow
from app.models.practice_record import PracticeRecord
from app.models.practice_session import PracticeSession
from app.models.question import Question
from app.models.question_import import (
    QuestionImport,  # noqa: F401 — ensures Subject mapper resolves
)
from app.services.admin_subject_service import resolve_subject_ids
from app.services.behavior_service import record_answer_behavior
from app.services.knowledge_point_service import (
    kp_any_condition,
    kp_exact_conditions,
    load_question_kps,
)
from app.services.wrong_question_service import record_wrong
from app.utils.answer_normalizer import is_answer_correct

logger = logging.getLogger(__name__)

# 单次刷题会话时长上限（秒）。自由计时番茄钟上限 5h，刷题会话留余量到 6h；
# 用于防御异常客户端上报 duration_sec=999999999。
PRACTICE_SESSION_MAX_DURATION_SEC = 6 * 60 * 60
_PRACTICE_DURATION_ROUNDING_TOLERANCE = 2  # 允许 finished-start 与 duration 的少量取整误差


def _parse_session_datetime(value) -> "datetime | None":
    """Parse an ISO-8601 datetime (may carry ``Z`` / ``+00:00``) into naive UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            logger.warning("practice session datetime 缺少时区信息，按 UTC 处理: %s", value)
        return normalize_to_naive_utc(value)
    text_val = str(value).strip()
    if not text_val:
        return None
    try:
        parsed = datetime.fromisoformat(text_val.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # 客户端未带时区：无法区分是中国本地时间还是 UTC，按 UTC 处理并告警，
        # 避免把中国本地时间静默当成 UTC 导致统计日偏移 8h。
        logger.warning(
            "practice session datetime 缺少时区信息，按 UTC 处理（若为北京时间将偏移 8h）: %s",
            text_val,
        )
    return normalize_to_naive_utc(parsed)


def _normalize_practice_session(
    session_meta: dict | None,
    *,
    user_id: int,
    answered_count: int,
    total_correct: int,
    total_wrong: int,
) -> dict | None:
    """Validate & normalize a client-supplied practice session before insert.

    Returns column values for a ``PracticeSession`` row, or ``None`` when
    ``session_meta`` is absent (old clients never send a session — they must
    still be able to answer).  Raises ``ValueError`` when ``session_meta`` is
    present but structurally invalid (malformed timestamps / non-int duration).
    """
    if not session_meta:
        return None

    started_at = _parse_session_datetime(session_meta.get("started_at"))
    finished_at = _parse_session_datetime(session_meta.get("finished_at"))
    if started_at is None or finished_at is None:
        raise ValueError("session.start_at / session.finished_at 必须为合法 ISO 时间")
    if finished_at < started_at:
        raise ValueError("session.finished_at 不得早于 session.started_at")

    duration_sec = session_meta.get("duration_sec")
    try:
        duration_sec = int(duration_sec) if duration_sec is not None else None
    except (TypeError, ValueError):
        raise ValueError("session.duration_sec 必须为整数")

    wall_sec = max(0, int((finished_at - started_at).total_seconds()))
    if duration_sec is None or duration_sec < 0:
        # 缺省/非法：退化为墙钟时长
        duration_sec = wall_sec
    # 不允许明显超过墙钟（保留少量取整误差），并设置全局上限
    if duration_sec > wall_sec + _PRACTICE_DURATION_ROUNDING_TOLERANCE:
        duration_sec = max(0, wall_sec)
    duration_sec = min(duration_sec, PRACTICE_SESSION_MAX_DURATION_SEC)

    request_id = str(session_meta.get("request_id") or "").strip() or None
    if request_id is not None and len(request_id) > 255:
        # 数据库列 String(256)：超长直接入库会触发 Postgres DataError（非
        # IntegrityError），导致整个批量提交 500。不能简单截断 —— 两个不同的
        # 超长 request_id 若前缀相同会被截成同一个幂等 key，后一次会话被静默
        # 当作重复而丢弃。改为稳定 hash，不同 id 几乎必然映射到不同 key，
        # 且同一超长 id 重试仍得到同一 hash，幂等去重不受影响。
        request_id = "h:" + hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    subject_id = session_meta.get("subject_id")
    try:
        subject_id = int(subject_id) if subject_id is not None else None
    except (TypeError, ValueError):
        raise ValueError("session.subject_id 必须为整数")

    mode = str(session_meta.get("mode") or "random")[:16]
    question_count = session_meta.get("question_count")
    try:
        question_count = int(question_count) if question_count is not None else answered_count
    except (TypeError, ValueError):
        question_count = answered_count
    question_count = max(0, question_count)

    return {
        "user_id": user_id,
        "subject_id": subject_id,
        "request_id": request_id,
        "mode": mode,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_sec": duration_sec,
        "question_count": question_count,
        "answered_count": max(0, answered_count),
        "correct_count": max(0, total_correct),
        "wrong_count": max(0, total_wrong),
        "status": "completed",
    }


def _is_unique_violation(err: IntegrityError) -> bool:
    """True only for a unique-constraint IntegrityError (the intended idempotency
    collision).  Any other integrity error (FK / CHECK / NOT NULL) is a real data
    problem and must not be mislabeled as a duplicate request_id."""
    orig = getattr(err, "orig", None)
    if orig is None:
        return False
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if code == "23505":  # PostgreSQL unique_violation (asyncpg/psycopg)
        return True
    msg = str(orig)
    return "UNIQUE constraint failed" in msg or "duplicate key" in msg


def _random_sample_query(query, total_count: int, need: int, id_col=None):
    """Replace ``ORDER BY random()`` with a random offset for efficiency.

    For small result sets (total_count <= 2000), uses ``ORDER BY random()``
    which is simpler and well-tested.  For large result sets, uses a random
    offset to avoid the expensive full-table sort.

    The offset approach assumes roughly evenly-distributed IDs and is only
    a best-effort randomization — it's good enough for practice sampling
    where perfect uniformity isn't required.

    Falls back to ``ORDER BY random()`` when ``total_count`` is not a usable
    integer (e.g. mock objects in tests).
    """
    if not isinstance(total_count, int):
        return query.order_by(id_col.asc() if id_col else func.random()).limit(need)
    if total_count <= need:
        return query.order_by(id_col.asc() if id_col else func.random()).limit(need)
    if total_count > 2000 or need <= 20:
        # Large table or small sample: random offset to avoid full sort
        offset = random.randint(0, total_count - need)
        return query.order_by(id_col.asc() if id_col else func.random()).offset(offset).limit(need)
    return query.order_by(func.random()).limit(need)


async def get_practice_subject_tree(db: AsyncSession) -> list[dict]:
    """返回刷题页可用科目树。

    数据来源：subjects 表中 is_active=true 的记录。
    使用 parent_id 构建树，按 sort_order, id 排序。
    不硬编码任何 subject_id。
    """
    from app.models.admin import Subject

    result = await db.execute(
        select(Subject)
        .where(Subject.is_active.is_(True))
        .order_by(Subject.sort_order.asc(), Subject.id.asc())
    )
    subjects = list(result.scalars().all())

    def _to_node(s: Subject) -> dict:
        return {
            "subject_id": s.id,
            "subject_code": s.code,
            "subject_name": s.name,
            "display_name": s.name,
            "parent_id": s.parent_id,
            "level": s.level,
            "path": s.path,
            "sort_order": s.sort_order,
            "children": [],
        }

    nodes: dict[int, dict] = {s.id: _to_node(s) for s in subjects}
    roots: list[dict] = []
    for s in subjects:
        node = nodes[s.id]
        parent = nodes.get(s.parent_id) if s.parent_id else None
        if parent:
            parent["children"].append(node)
        else:
            roots.append(node)
    return roots


async def resolve_subject_id_to_code(db: AsyncSession, subject_id: int) -> tuple[str, str] | None:
    """将 subject_id 解析为 (subject_code, subject_name)。不存在返回 None。"""
    from app.models.admin import Subject

    subj = await db.get(Subject, subject_id)
    if subj is None:
        return None
    return (subj.code, subj.name)


_TRUE_FALSE_TRUE = {"a", "true", "对", "是", "正确", "t", "yes", "1"}
_TRUE_FALSE_FALSE = {"b", "false", "错", "否", "错误", "f", "no", "0"}


def _normalize_true_false_answer(value: str) -> str:
    v = str(value or "").strip().lower()
    if v in _TRUE_FALSE_TRUE:
        return "A"
    if v in _TRUE_FALSE_FALSE:
        return "B"
    return v.upper()


def _build_excluded_question_subquery(
    user_id: int,
    exclude_answered: bool = False,
    no_repeat_days: int | None = None,
) -> "select | None":
    """构建需要排除的题目 ID 子查询。

    V1: 支持按时间窗口排除最近 N 天已答题目。

    规则：
    1. exclude_answered=False 且 no_repeat_days=None：不排除，返回 None。
    2. exclude_answered=True 且 no_repeat_days=None：排除所有历史已答题（旧语义兼容）。
    3. no_repeat_days=N：排除最近 N 天内已答题。
    4. no_repeat_days 有值时，即使 exclude_answered=False，也启用周期排除。
    """
    if not exclude_answered and not no_repeat_days:
        return None

    sub = (
        select(PracticeRecord.question_id)
        .where(PracticeRecord.user_id == user_id)
    )

    if no_repeat_days:
        cutoff = utcnow() - timedelta(days=no_repeat_days)
        sub = sub.where(PracticeRecord.answered_at >= cutoff)

    return sub.distinct()


# ── 父级科目聚合刷题相关函数 ─────────────────────────────────


async def resolve_practice_subject_scope(
    db: AsyncSession,
    subject_id: int,
    include_children: bool,
) -> tuple[bool, list[int]]:
    """解析刷题科目范围。

    返回 (has_enabled_children, subject_ids)：
        has_enabled_children: 当前科目是否有启用的子科目。
        subject_ids: 需要查询的 subject_id 列表，按 sort_order, id 排序。

    - include_children=True 且有子科目时：返回自身 + 所有启用后代。
    - include_children=False 或叶子科目：只返回自身。
    """
    from app.models.admin import Subject

    subj = await db.get(Subject, subject_id)
    if subj is None:
        return False, []

    # 获取全部启用科目以构建树
    all_result = await db.execute(
        select(Subject)
        .where(Subject.is_active)
        .order_by(Subject.level.asc(), Subject.sort_order.asc(), Subject.id.asc())
    )
    all_subjects = list(all_result.scalars().all())

    # 检查是否有启用子科目
    children_by_parent: dict[int | None, list[Subject]] = {}
    for s in all_subjects:
        children_by_parent.setdefault(s.parent_id, []).append(s)
    has_enabled_children = len(children_by_parent.get(subj.id, [])) > 0

    if not include_children or not has_enabled_children:
        return has_enabled_children, [subj.id]

    # 包含后代：BFS 遍历子树
    result = []
    stack = [subj]
    seen = set()
    while stack:
        node = stack.pop()
        if node.id in seen:
            continue
        seen.add(node.id)
        result.append(node)
        for child in children_by_parent.get(node.id, []):
            if child.is_active:
                stack.append(child)

    # 按 sort_order, id 排序
    result.sort(key=lambda s: (s.sort_order, s.id))
    return has_enabled_children, [s.id for s in result]


def _round_robin_merge(
    buckets: list[list[object]],
    count: int,
    randomize_order: bool = False,
) -> list[object]:
    """轮询合并多个桶中的元素，使各桶输出尽量均衡。

    Args:
        buckets: 每个元素是一个桶（元素列表），桶内已按期望顺序排列。
        count: 期望返回的元素总数。
        randomize_order: 是否随机化桶的起始顺序（random 模式使用）。

    Returns:
        轮询合并后的元素列表，不超出 count。每个元素只出现一次（按 object
        identity 去重）。桶内顺序保持，桶间轮询。
    """
    if count <= 0 or not buckets:
        return []

    non_empty = [b for b in buckets if b]
    if not non_empty:
        return []

    if randomize_order:
        random.shuffle(non_empty)

    result: list[object] = []
    seen: set[int] = set()
    max_len = max(len(b) for b in non_empty)

    for i in range(max_len):
        for bucket in non_empty:
            if i < len(bucket):
                item = bucket[i]
                item_id = id(item)
                if hasattr(item, "id"):
                    item_id = item.id
                if item_id not in seen:
                    result.append(item)
                    seen.add(item_id)
                    if len(result) >= count:
                        return result
    return result


def _round_robin_merge_with_metadata(
    buckets: list[list[tuple[object, dict]]],
    count: int,
    randomize_order: bool = False,
) -> tuple[list[object], dict[int, dict]]:
    """轮询合并带 metadata 的桶（smart 模式用）。

    每个桶的元素为 (question, metadata_dict)。返回 (merged_questions, merged_metadata)，
    其中 merged_metadata 为 {question_id: metadata_dict}。
    """
    merged: list[object] = []
    metadata: dict[int, dict] = {}

    if count <= 0:
        return merged, metadata

    if not buckets:
        return merged, metadata

    non_empty = [b for b in buckets if b]
    if not non_empty:
        return merged, metadata

    if randomize_order:
        random.shuffle(non_empty)

    seen_ids: set[int] = set()
    max_len = max(len(b) for b in non_empty)

    for i in range(max_len):
        for bucket in non_empty:
            if i < len(bucket):
                item, meta = bucket[i]
                item_id = item.id if hasattr(item, "id") else id(item)
                if item_id not in seen_ids:
                    merged.append(item)
                    metadata[item_id] = meta
                    seen_ids.add(item_id)
                    if len(merged) >= count:
                        return merged, metadata
    return merged, metadata


async def get_aggregated_random_questions(
    db: AsyncSession,
    user_id: int,
    subject_code: str,
    subject_ids: list[int],
    count: int = 20,
    knowledge_points: list[str] | None = None,
    exclude_answered: bool = False,
    no_repeat_days: int | None = None,
    use_leitner: bool = True,
) -> list[Question]:
    """random 模式聚合刷题：每个精确 subject_id 独立生成候选后轮询均衡分配。

    对每个启用子科目独立查询（limit=count），保证每科都有候选进入轮询池，
    不存在因全局 LIMIT 导致子科目被完全排除的风险。每科最多返回 count 道题，
    再通过 round-robin 确保最终分布均衡。
    """
    buckets: list[list[Question]] = []

    for sid in subject_ids:
        # 为每个精确 subject_id 构建独立查询条件
        conds = [Question.is_active, Question.subject_id == sid]
        if knowledge_points:
            conds.extend(kp_exact_conditions(knowledge_points))

        if use_leitner:
            candidates = await _get_questions_with_leitner(
                db, user_id, conds, "random", count,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
            )
        else:
            candidates = await _get_questions_v1_fallback(
                db, conds, "random", count,
                user_id=user_id,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
            )
        if candidates:
            random.shuffle(candidates)
            buckets.append(candidates)

    if not buckets:
        logger.info(
            "[AGG_RANDOM] subject_code=%s subject_ids=%s count=%d no_buckets",
            subject_code, subject_ids, count,
        )
        return []

    result = _round_robin_merge(buckets, count, randomize_order=True)
    from collections import Counter
    per_subject = Counter(q.subject_id for q in result)
    logger.info(
        "[AGG_RANDOM] subject_code=%s subject_ids=%s count=%d "
        "non_empty_buckets=%d returned=%d per_subject=%s",
        subject_code, subject_ids, count,
        len(buckets), len(result), dict(per_subject),
    )
    return result


async def get_aggregated_smart_questions(
    db: AsyncSession,
    user_id: int,
    subject_code: str,
    subject_ids: list[int],
    count: int = 20,
    exclude_answered: bool = False,
    no_repeat_days: int | None = None,
    use_leitner: bool = True,
    request_id: str | None = None,
    smart_strategy: str = "scored",
) -> tuple[list[Question], dict[int, dict]]:
    """smart 模式聚合刷题：为每个精确 subject_code 独立生成 smart 候选后轮询合并。

    对每个子科目分别调用 get_smart_practice_questions(skip_finalize=True)，
    避免全局 top-K 截断导致某个子科目的 smart 候选被完全排除。
    所有子科目的候选在"带 metadata 的桶"中保持各自原有的推荐顺序和分数，
    经 round-robin 合并后，统一调用一次 _finalize_smart 写入推荐日志。

    性能注意：典型场景下对 N 个科目共 N 次 smart 调用，每次包括：
      - 一次向量召回（外部 API）
      - 一次薄弱知识点查询
      - 少量补齐查询
    N 通常为 3~5，属于可接受范围。
    """
    from app.models.admin import Subject

    # 批量加载子科目 code 映射
    subj_result = await db.execute(
        select(Subject).where(Subject.id.in_(subject_ids))
    )
    subj_map: dict[int, str] = {s.id: s.code for s in subj_result.scalars().all()}

    all_buckets: list[list[tuple[Question, dict]]] = []

    for sid in subject_ids:
        sid_code = subj_map.get(sid)
        if not sid_code:
            continue

        qs, meta = await get_smart_practice_questions(
            db=db, user_id=user_id, subject_code=sid_code,
            count=count,
            exclude_answered=exclude_answered,
            no_repeat_days=no_repeat_days,
            use_leitner=use_leitner,
            request_id=request_id,
            smart_strategy=smart_strategy,
            skip_finalize=True,
        )
        if qs:
            all_buckets.append([(q, meta.get(q.id, {})) for q in qs])

    if not all_buckets:
        logger.info(
            "[AGG_SMART] subject_code=%s subject_ids=%s count=%d no_buckets",
            subject_code, subject_ids, count,
        )
        return [], {}

    if len(all_buckets) <= 1:
        merged = all_buckets[0] if all_buckets else []
        merged_qs = [item[0] for item in merged[:count]]
        merged_meta = {item[0].id: item[1] for item in merged[:count]}
        logger.info(
            "[AGG_SMART] subject_code=%s subject_ids=%s count=%d buckets=%d returned=%d (single)",
            subject_code, subject_ids, count, len(all_buckets), len(merged_qs),
        )
        return await _finalize_smart(
            merged_qs, merged_meta, db, user_id, subject_code,
            request_id=request_id,
        )

    merged_qs, merged_meta = _round_robin_merge_with_metadata(
        all_buckets, count, randomize_order=False,
    )

    from collections import Counter
    per_subject = Counter(q.subject_id for q in merged_qs)
    logger.info(
        "[AGG_SMART] subject_code=%s subject_ids=%s count=%d "
        "non_empty_buckets=%d returned=%d per_subject=%s",
        subject_code, subject_ids, count,
        len(all_buckets), len(merged_qs), dict(per_subject),
    )

    # 统一写入推荐日志（仅记录最终实际返回的题目）
    return await _finalize_smart(
        merged_qs, merged_meta, db, user_id, subject_code,
        request_id=request_id,
    )


async def get_practice_questions(
    db: AsyncSession,
    user_id: int,
    subject_code: str,
    count: int = 20,
    mode: str = "random",
    knowledge_points: list[str] | None = None,
    exclude_answered: bool = False,
    no_repeat_days: int | None = None,
    use_leitner: bool = True,
    subject_ids: list[int] | None = None,
) -> list[Question]:
    """获取刷题题目。

    Args:
        subject_ids: 可选。如果提供，跳过 resolve_subject_ids 的内部扩展，
            直接使用给定的 subject_id 列表。用于 include_children=false 的精确查询。
    """
    if subject_ids is not None:
        ids = subject_ids
    else:
        ids = await resolve_subject_ids(db, subject_code)
    subject_cond = Question.subject_id.in_(ids)
    base_conditions = [Question.is_active, subject_cond]

    if knowledge_points:
        base_conditions.extend(kp_exact_conditions(knowledge_points))

    # ── V2 Leitner 模式 ──
    if use_leitner:
        return await _get_questions_with_leitner(
            db, user_id, base_conditions, mode, count,
            exclude_answered=exclude_answered,
            no_repeat_days=no_repeat_days,
        )

    # ── V1 兼容模式：use_leitner=False ──
    return await _get_questions_v1_fallback(
        db, base_conditions, mode, count,
        user_id=user_id,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
    )


async def _get_questions_with_leitner(
    db: AsyncSession,
    user_id: int,
    base_conditions: list,
    mode: str,
    count: int,
    exclude_answered: bool = False,
    no_repeat_days: int | None = None,
) -> list[Question]:
    """V2 Leitner 取题：新题 + 到期复习题优先，逐步 fallback。"""
    from app.models.user_question_state import UserQuestionState

    now = utcnow()

    async def _leitner_query(
        due_condition,
        exclude_ids: set[int] | None = None,
        limit: int | None = None,
        extra_order=None,
    ) -> list[Question]:
        """Leitner 内部查询：outer join UserQuestionState + 到期条件。"""
        conds = list(base_conditions)
        if exclude_ids:
            conds.append(Question.id.notin_(exclude_ids))

        q = (
            select(Question)
            .outerjoin(
                UserQuestionState,
                and_(
                    UserQuestionState.question_id == Question.id,
                    UserQuestionState.user_id == user_id,
                ),
            )
            .where(and_(*conds, due_condition))
            .options(selectinload(Question.subject_ref))
        )
        if extra_order is not None:
            q = q.order_by(extra_order)
        elif mode == "random":
            q = q.order_by(func.random())
        else:
            q = q.order_by(Question.id.asc())

        q = q.limit(limit if limit is not None else count)
        result = await db.execute(q)
        return list(result.scalars().all())

    # 第一层：新题 + 已到期复习题
    due_cond = or_(
        UserQuestionState.id.is_(None),
        UserQuestionState.next_review_at.is_(None),
        UserQuestionState.next_review_at <= now,
    )
    questions = await _leitner_query(due_cond)

    if len(questions) >= count:
        logger.info(
            "[Leitner Query] mode=%s count=%d resultCount=%d (layer: new+due)",
            mode, count, len(questions),
        )
        return questions[:count]

    existing_ids = {q.id for q in questions}

    # 第二层：快到期题（next_review_at <= now + 1 天）
    soon = now + timedelta(days=1)
    due_soon_cond = or_(
        UserQuestionState.id.is_(None),
        UserQuestionState.next_review_at.is_(None),
        UserQuestionState.next_review_at <= soon,
    )
    more = await _leitner_query(due_soon_cond, exclude_ids=existing_ids, limit=count - len(questions))
    questions.extend(more)
    existing_ids.update(q.id for q in more)

    if len(questions) >= count:
        logger.info(
            "[Leitner Query] mode=%s count=%d resultCount=%d (layer: due+1d)",
            mode, count, len(questions),
        )
        return questions[:count]

    # 第三层：最久未做的题（last_answered_at ASC NULLS FIRST）
    all_cond = or_(
        UserQuestionState.id.is_(None),
        UserQuestionState.next_review_at.is_(None),
        UserQuestionState.next_review_at <= soon + timedelta(days=30),
    )
    more = await _leitner_query(
        all_cond, exclude_ids=existing_ids, limit=count - len(questions),
        extra_order=UserQuestionState.last_answered_at.asc().nulls_first(),
    )
    questions.extend(more)
    existing_ids.update(q.id for q in more)

    if len(questions) >= count:
        logger.info(
            "[Leitner Query] mode=%s count=%d resultCount=%d (layer: oldest)",
            mode, count, len(questions),
        )
        return questions[:count]

    # 第四层：回退到 V1 no_repeat_days fallback
    v1_results = await _get_questions_v1_fallback(
        db, base_conditions, mode, count - len(questions),
        user_id=user_id,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
        exclude_ids=existing_ids,
    )
    questions.extend(v1_results)

    logger.info(
        "[Leitner Query] mode=%s count=%d resultCount=%d (layer: v1-fallback)",
        mode, count, len(questions),
    )
    return questions[:count]


async def _get_questions_v1_fallback(
    db: AsyncSession,
    base_conditions: list,
    mode: str,
    count: int,
    user_id: int,
    exclude_answered: bool = False,
    no_repeat_days: int | None = None,
    exclude_ids: set[int] | None = None,
) -> list[Question]:
    """V1 fallback 取题：N天 → 7天 → 1天 → 不排除。"""
    async def _query(
        excl_answered: bool,
        excl_days: int | None,
        extra_exclude_ids: set[int] | None = None,
        limit: int | None = None,
    ) -> list[Question]:
        conds = list(base_conditions)
        sub = _build_excluded_question_subquery(
            user_id=user_id,
            exclude_answered=excl_answered,
            no_repeat_days=excl_days,
        )
        if sub is not None:
            conds.append(Question.id.notin_(sub))
        all_excl = set()
        if exclude_ids:
            all_excl.update(exclude_ids)
        if extra_exclude_ids:
            all_excl.update(extra_exclude_ids)
        if all_excl:
            conds.append(Question.id.notin_(all_excl))

        q = select(Question).where(and_(*conds)).options(selectinload(Question.subject_ref))
        if mode == "random":
            # Use count + random offset instead of ORDER BY random() on large tables
            total_q = select(func.count()).select_from(
                select(Question).where(and_(*conds)).subquery()
            )
            total = (await db.execute(total_q)).scalar() or 0
            q = _random_sample_query(q, total, limit or count, Question.id)
        else:
            q = q.order_by(Question.id.asc())
        q = q.limit(limit if limit is not None else count)
        result = await db.execute(q)
        return list(result.scalars().all())

    questions = await _query(exclude_answered, no_repeat_days)
    if len(questions) >= count or not no_repeat_days:
        return questions

    existing = set(q.id for q in questions)
    if exclude_ids:
        existing.update(exclude_ids)

    if no_repeat_days > 7:
        more = await _query(True, 7, extra_exclude_ids=existing, limit=count - len(questions))
        questions.extend(more)
        existing.update(q.id for q in more)
    if len(questions) >= count:
        return questions[:count]

    if no_repeat_days > 1:
        more = await _query(True, 1, extra_exclude_ids=existing, limit=count - len(questions))
        questions.extend(more)
        existing.update(q.id for q in more)
    if len(questions) >= count:
        return questions[:count]

    more = await _query(False, None, extra_exclude_ids=existing, limit=count - len(questions))
    questions.extend(more)
    return questions[:count]


async def get_similar_practice_questions(
    db: AsyncSession,
    user_id: int,
    subject_code: str,
    source_question_id: int,
    count: int = 20,
    exclude_answered: bool = False,
    no_repeat_days: int | None = None,
    use_leitner: bool = True,
) -> tuple[list[Question], dict[int, dict]]:
    """similar 模式：基于源题的向量相似题召回，不足时用规则 + 随机补齐。

    返回: (questions_list, metadata_dict)
        metadata_dict: {question_id: {"recommend_reason": ..., "recommend_score": ..., "strategy": ..., "similarity": ...}}
    """
    # TODO(V3): use_leitner 参数当前未使用。向量召回后应通过
    # question_review_service.get_due_question_ids() 做二次过滤，
    # 过滤掉 next_review_at > now 的题目，不足时用 Leitner fallback 补齐。
    metadata: dict[int, dict] = {}

    # 1. 向量召回
    vector_questions: list[Question] = []
    try:
        from app.services import vector_retrieval_service

        result = await vector_retrieval_service.search_similar_questions(
            db=db,
            user_id=user_id,
            question_id=source_question_id,
            count=count,
            exclude_answered=exclude_answered,
            no_repeat_days=no_repeat_days,
        )
        if result.get("enabled") and result.get("recommendations"):
            rec_ids = [r["question_id"] for r in result["recommendations"]]
            if rec_ids:
                q_result = await db.execute(
                    select(Question).where(Question.id.in_(rec_ids), Question.is_active).options(selectinload(Question.subject_ref))
                )
                q_map = {q.id: q for q in q_result.scalars().all()}
                for rec in result["recommendations"]:
                    q = q_map.get(rec["question_id"])
                    if q:
                        vector_questions.append(q)
                        metadata[q.id] = {
                            "recommend_reason": rec.get("match_reason", "向量相似"),
                            "recommend_score": rec.get("recommend_score"),
                            "strategy": "vector",
                            "similarity": rec.get("similarity"),
                        }
    except Exception:
        logger.warning("similar 模式向量召回失败，回退到随机", exc_info=True)

    if len(vector_questions) >= count:
        return vector_questions[:count], metadata

    # 2. 补齐：规则推荐 + 随机
    existing_ids = {q.id for q in vector_questions}
    existing_ids.add(source_question_id)

    ids = await resolve_subject_ids(db, subject_code)
    subject_cond = Question.subject_id.in_(ids)
    conditions = [
        Question.is_active,
        subject_cond,
        Question.id.notin_(existing_ids),
    ]
    # V1: 使用公共排除函数，支持 no_repeat_days 时间窗口
    excluded_sub = _build_excluded_question_subquery(
        user_id=user_id,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
    )
    if excluded_sub is not None:
        conditions.append(Question.id.notin_(excluded_sub))

    need = count - len(vector_questions)
    q = select(func.count()).select_from(
        select(Question).where(and_(*conditions)).subquery()
    )
    total = (await db.execute(q)).scalar() or 0
    q = select(Question).where(and_(*conditions)).options(selectinload(Question.subject_ref))
    q = _random_sample_query(q, total, need, Question.id)
    result = await db.execute(q)
    fill_questions = list(result.scalars().all())

    for fq in fill_questions:
        metadata[fq.id] = {
            "recommend_reason": "规则补齐",
            "recommend_score": None,
            "strategy": "fallback",
            "similarity": None,
        }

    return vector_questions + fill_questions, metadata


async def _maybe_finalize_smart(
    questions: list[Question],
    metadata: dict[int, dict],
    skip: bool,
    db: AsyncSession,
    user_id: int,
    subject_code: str,
    request_id: str | None = None,
    experiment_id: int | None = None,
    variant_key: str | None = None,
) -> tuple[list[Question], dict[int, dict]]:
    """条件化收尾：skip=True 时跳过推荐日志，由调用方统一写入。

    聚合科目模式会先对各子科目执行 ``skip_finalize=True``，随后统一写日志。
    因此实验上下文必须随每道题的 metadata 一起向上传递，否则最终日志会丢失
    experiment_id / variant_key，导致 A/B 指标漏数。
    """
    if skip:
        returned_ids = {q.id for q in questions}
        for qid in returned_ids:
            meta = metadata.setdefault(qid, {})
            if experiment_id is not None:
                meta["experiment_id"] = experiment_id
            if variant_key is not None:
                meta["variant_key"] = variant_key
        return questions, metadata
    return await _finalize_smart(
        questions, metadata, db, user_id, subject_code,
        request_id=request_id,
        experiment_id=experiment_id,
        variant_key=variant_key,
    )


async def _apply_strategy_weight_rerank(
    db: AsyncSession,
    user_id: int,
    questions: list[Question],
    metadata: dict[int, dict],
    config: dict | None,
    weak_kp_names: list[str],
) -> tuple[list[Question], dict[int, dict]]:
    """按推荐策略配置权重对召回候选重排（best-effort）。

    仅当存在有效的 DB 策略配置且 config_json.strategy_type 为 weakness_vector 时生效；
    无配置 / 未激活 / 异常时原样返回，保持现有行为不变。
    """
    try:
        if not config or len(questions) < 2:
            return questions, metadata
        if not config.get("is_active") or config.get("id") is None:
            return questions, metadata
        strategy_type = (config.get("config_json") or {}).get("strategy_type")
        if strategy_type not in (None, "weakness_vector"):
            return questions, metadata

        # 批量加载知识点 id 与用户掌握度（固定 2 次查询，避免 N+1）
        from app.models.knowledge_point import KnowledgePoint
        from app.models.user_knowledge_state import UserKnowledgeState

        kp_map = await load_question_kps(db, [q.id for q in questions])

        candidate_names: set[str] = set()
        for q in questions:
            candidate_names.update(kp_map.get(q.id, []))

        kp_name_to_id: dict[str, int] = {}
        if candidate_names:
            kp_result = await db.execute(
                select(KnowledgePoint.id, KnowledgePoint.name).where(
                    KnowledgePoint.name.in_(candidate_names)
                )
            )
            for kp_id, name in kp_result.all():
                kp_name_to_id[name] = kp_id

        mastery_by_kp: dict[int, float] = {}
        kp_ids = set(kp_name_to_id.values())
        if kp_ids:
            state_result = await db.execute(
                select(
                    UserKnowledgeState.knowledge_point_id,
                    UserKnowledgeState.mastery_score,
                ).where(
                    UserKnowledgeState.user_id == user_id,
                    UserKnowledgeState.knowledge_point_id.in_(kp_ids),
                )
            )
            for kp_id, mastery in state_result.all():
                if mastery is not None:
                    mastery_by_kp[kp_id] = mastery

        known_mastery = list(mastery_by_kp.values())
        user_mean_mastery = (
            sum(known_mastery) / len(known_mastery) if known_mastery else None
        )
        target_difficulty = (
            3 + round(user_mean_mastery / 25) if user_mean_mastery is not None else None
        )
        exploration = float(config.get("exploration_ratio") or 0.0)

        from app.services.recommendation_strategy_service import apply_strategy_weights

        scored: list[tuple[Question, float, float]] = []
        weak_set = set(weak_kp_names)
        for q in questions:
            q_kps = kp_map.get(q.id, [])
            q_kp_set = set(q_kps)
            overlap = len(q_kp_set & weak_set) / max(1, len(q_kps))

            gaps = []
            for name in q_kps:
                kp_id = kp_name_to_id.get(name)
                mastery = mastery_by_kp.get(kp_id) if kp_id is not None else None
                gaps.append((100.0 - mastery) / 100.0 if mastery is not None else 0.5)
            mastery_gap = sum(gaps) / len(gaps) if gaps else 0.5

            if target_difficulty is None:
                difficulty_match = 1.0
            else:
                difficulty_match = 1.0 - min(
                    1.0, abs((q.difficulty or 3) - target_difficulty) / 4.0
                )

            base_scores = {
                "vector_similarity": (metadata.get(q.id) or {}).get("similarity") or 0.0,
                "knowledge_overlap": overlap,
                "difficulty_match": difficulty_match,
                "mastery_gap": mastery_gap,
                "path_priority": 0.0,
            }
            weighted = apply_strategy_weights(base_scores, config)
            final = (1.0 - exploration) * weighted + exploration * random.random()
            scored.append((q, final, weighted))

        scored.sort(key=lambda t: t[1], reverse=True)
        for q, _final, weighted in scored:
            meta = metadata.setdefault(q.id, {})
            meta["recommend_score"] = round(weighted, 4)
            meta["strategy_config_id"] = config.get("id")
        return [t[0] for t in scored], metadata
    except Exception:
        logger.warning("策略权重重排失败，保持原顺序", exc_info=True)
        return questions, metadata


async def get_smart_practice_questions(
    db: AsyncSession,
    user_id: int,
    subject_code: str,
    count: int = 20,
    exclude_answered: bool = False,
    no_repeat_days: int | None = None,
    use_leitner: bool = True,
    request_id: str | None = None,
    smart_strategy: str = "scored",
    skip_finalize: bool = False,
    subject_ids: list[int] | None = None,
) -> tuple[list[Question], dict[int, dict]]:
    """smart 模式：基于薄弱知识点构造 query_text 进行向量召回，不足时补齐。

    Phase 3: 新增 smart_strategy="path" 知识路径推荐策略。
    Phase 2: 优先使用 UserKnowledgeState 画像，fallback 到近 30 天 PracticeRecord 统计。
    返回: (questions_list, metadata_dict)
    """
    # TODO(V3): use_leitner 参数当前未使用。向量召回和 path 推荐结果应通过
    # question_review_service.get_due_question_ids() 做二次过滤，
    # 过滤掉 next_review_at > now 的题目，不足时用 Leitner fallback 补齐。
    metadata: dict[int, dict] = {}

    # Phase 4: 实验策略解析（best-effort）
    experiment_info = {
        "experiment_id": None,
        "variant_key": None,
        "strategy_config_id": None,
    }
    try:
        from app.services import recommendation_experiment_service

        resolved = await recommendation_experiment_service.resolve_strategy_for_user(
            db=db,
            user_id=user_id,
            scene="practice_smart",
            default_strategy=smart_strategy,
        )
        if resolved.get("source") == "experiment" and resolved.get("strategy"):
            smart_strategy = resolved["strategy"]
            experiment_info["experiment_id"] = resolved.get("experiment_id")
            experiment_info["variant_key"] = resolved.get("variant_key")
    except Exception:
        logger.warning("实验策略解析失败，使用默认策略", exc_info=True)

    # Historical/admin naming compatibility.  The experiment/config layer uses
    # ``knowledge_path`` while this service originally used ``path``; treat
    # them as the same strategy.  ``hybrid_graph`` / ``smart_scored`` are safe
    # aliases for the upgraded scored implementation rather than parallel
    # recommendation engines.
    smart_strategy = {
        "knowledge_path": "path",
        "hybrid_graph": "scored",
        "smart_scored": "scored",
    }.get(smart_strategy, smart_strategy)

    # V4: 综合打分策略
    if smart_strategy == "scored":
        try:
            scored_qs, scored_meta = await get_smart_scored_questions(
                db=db, user_id=user_id, subject_code=subject_code, count=count,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
                request_id=request_id,
                subject_ids=subject_ids,
            )
            if len(scored_qs) >= count:
                return await _maybe_finalize_smart(
                    scored_qs[:count], scored_meta, skip_finalize, db, user_id, subject_code,
                    request_id=request_id,
                    experiment_id=experiment_info.get("experiment_id"),
                    variant_key=experiment_info.get("variant_key"),
                )

            # scored 已经选出的题目包含复习/薄弱/图谱信号，不能因为题量不足就
            # 整批丢弃再从 weakness_vector 重做。保留已有结果，仅补齐缺口。
            logger.info(
                "scored 策略题量不足 (%d/%d)，保留 scored 结果并 fallback 到 weakness_vector 补齐",
                len(scored_qs), count,
            )
            remaining = count - len(scored_qs)
            fallback_qs, fallback_meta = await _smart_weakness_vector(
                db=db,
                user_id=user_id,
                subject_code=subject_code,
                count=remaining,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
                use_leitner=use_leitner,
                exclude_ids={q.id for q in scored_qs},
                subject_ids=subject_ids,
            )
            merged_qs = scored_qs + fallback_qs
            merged_meta = dict(scored_meta)
            merged_meta.update(fallback_meta)
            return await _maybe_finalize_smart(
                merged_qs[:count], merged_meta, skip_finalize, db, user_id, subject_code,
                request_id=request_id,
                experiment_id=experiment_info.get("experiment_id"),
                variant_key=experiment_info.get("variant_key"),
            )
        except Exception:
            logger.warning("scored 策略失败，fallback 到 weakness_vector", exc_info=True)

    # Phase 3: 知识路径策略
    if smart_strategy == "path":
        try:
            from app.services import knowledge_path_service

            path_result = await knowledge_path_service.get_user_path_recommendations(
                db=db,
                user_id=user_id,
                subject=subject_code,
                limit=8,
                questions_per_node=3,
            )
            path_qids = path_result.get("recommended_question_ids", [])
            if path_qids:
                # 获取题目
                q_result = await db.execute(
                    select(Question).where(
                        Question.id.in_(path_qids[:count]),
                        Question.is_active,
                    ).options(selectinload(Question.subject_ref))
                )
                q_map = {q.id: q for q in q_result.scalars().all()}
                # 保持 path_qids 的顺序（按优先级排序）
                path_questions = [q_map[qid] for qid in path_qids[:count] if qid in q_map]

                # 构建 metadata
                node_map = {}
                for node in path_result.get("nodes", []):
                    for qid in node.get("recommended_question_ids", []):
                        node_map[qid] = node

                for q in path_questions:
                    node = node_map.get(q.id, {})
                    metadata[q.id] = {
                        "recommend_reason": node.get("reason", f"知识路径推荐：{node.get('name', '')}"),
                        "recommend_score": node.get("priority"),
                        "strategy": "knowledge_path",
                        "similarity": None,
                    }

                if len(path_questions) >= count:
                    return await _maybe_finalize_smart(
                        path_questions[:count], metadata, skip_finalize, db, user_id, subject_code,
                        request_id=request_id,
                        experiment_id=experiment_info.get("experiment_id"),
                        variant_key=experiment_info.get("variant_key"),
                    )

                # 不足时 fallback 到 weakness_vector
                logger.info("path 策略题量不足 (%d/%d)，fallback 到 weakness_vector",
                            len(path_questions), count)
                remaining = count - len(path_questions)
                fallback_questions, fallback_meta = await _smart_weakness_vector(
                    db, user_id, subject_code, count=remaining,
                    exclude_answered=exclude_answered,
                    no_repeat_days=no_repeat_days,
                    exclude_ids={q.id for q in path_questions},
                    subject_ids=subject_ids,
                )
                path_questions.extend(fallback_questions)
                metadata.update(fallback_meta)
                return await _maybe_finalize_smart(
                    path_questions[:count], metadata, skip_finalize, db, user_id, subject_code,
                    request_id=request_id,
                    experiment_id=experiment_info.get("experiment_id"),
                    variant_key=experiment_info.get("variant_key"),
                )
        except Exception:
            logger.warning("knowledge_path 策略失败，fallback 到 weakness_vector", exc_info=True)
        # path 策略完全失败，继续走 weakness_vector 逻辑

    # 1. 获取薄弱知识点（Phase 2 优先使用掌握度画像）
    weak_kps: list[dict] = []
    try:
        from app.services import mastery_service
        weak_kps = await mastery_service.get_user_weak_knowledge_points(
            db, user_id, subject_code, limit=5,
        )
        if weak_kps:
            pass
    except Exception:
        logger.warning("mastery_service.get_user_weak_knowledge_points failed, fallback", exc_info=True)

    if not weak_kps:
        # Fallback: Phase 1 的临时统计
        weak_kps = await _compute_weak_knowledge_points(
            db, user_id,
            subject_ids if subject_ids is not None else await resolve_subject_ids(db, subject_code),
        )
        if weak_kps:
            pass

    if not weak_kps:
        # 没有足够的做题记录来判断薄弱点，退化为随机
        logger.info("smart 模式: 无足够做题记录，退化为随机")
        questions = await get_practice_questions(
            db=db, user_id=user_id, subject_code=subject_code, count=count,
            mode="random", exclude_answered=exclude_answered,
            no_repeat_days=no_repeat_days,
        )
        for q in questions:
            metadata[q.id] = {
                "recommend_reason": "随机推荐（无足够做题记录）",
                "recommend_score": None,
                "strategy": "random_fallback",
                "similarity": None,
            }
        return await _maybe_finalize_smart(questions, metadata, skip_finalize, db, user_id, subject_code,
                                     request_id=request_id,
                                     experiment_id=experiment_info.get("experiment_id"),
                                     variant_key=experiment_info.get("variant_key"))

    # 2. 构造 query_text 并向量召回
    kp_names = [kp["name"] for kp in weak_kps[:5]]
    query_text = (
        f"科目：{subject_code}。请推荐这些薄弱知识点的练习题："
        f"{'、'.join(kp_names)}。要求题目适合查漏补缺和变式训练。"
    )

    vector_questions: list[Question] = []
    try:
        from app.services import vector_retrieval_service

        recalls = await vector_retrieval_service.vector_recall_by_text(
            db=db,
            user_id=user_id,
            subject=subject_code,
            query_text=query_text,
            count=count,
            exclude_answered=exclude_answered,
            no_repeat_days=no_repeat_days,
        )
        if recalls:
            rec_ids = [r["question_id"] for r in recalls]
            q_result = await db.execute(
                select(Question).where(Question.id.in_(rec_ids), Question.is_active).options(selectinload(Question.subject_ref))
            )
            q_map = {q.id: q for q in q_result.scalars().all()}
            for rec in recalls:
                q = q_map.get(rec["question_id"])
                if q:
                    vector_questions.append(q)
                    metadata[q.id] = {
                        "recommend_reason": f"薄弱知识点推荐：{'、'.join(kp_names[:3])}",
                        "recommend_score": rec.get("recommend_score"),
                        "strategy": "smart_vector",
                        "similarity": rec.get("similarity"),
                    }
    except Exception:
        logger.warning("smart 模式向量召回失败，回退", exc_info=True)

    # Phase 4.6: 策略权重重排（best-effort；无 DB 配置时保持原顺序）
    strategy_config = None
    try:
        from app.services import recommendation_strategy_service

        # weakness_vector 的 rerank 必须显式读取自己的配置；practice_smart
        # 的 scene 默认现在是 default_scored，不能误拿 scored 的 legacy 0 权重。
        strategy_config = await recommendation_strategy_service.get_strategy_config(
            db, "practice_smart", strategy_name="default_weakness_vector",
        )
    except Exception:
        logger.debug("获取推荐策略配置失败，跳过权重重排", exc_info=True)

    if strategy_config:
        vector_questions, metadata = await _apply_strategy_weight_rerank(
            db, user_id, vector_questions, metadata, strategy_config, kp_names,
        )

    if len(vector_questions) >= count:
        return await _maybe_finalize_smart(vector_questions[:count], metadata, skip_finalize, db, user_id, subject_code,
                                     request_id=request_id,
                                     experiment_id=experiment_info.get("experiment_id"),
                                     variant_key=experiment_info.get("variant_key"))

    # 3. 补齐：按薄弱知识点过滤 + 随机
    existing_ids = {q.id for q in vector_questions}
    scope_ids = subject_ids if subject_ids is not None else await resolve_subject_ids(db, subject_code)
    subject_cond = Question.subject_id.in_(scope_ids)
    conditions = [
        Question.is_active,
        subject_cond,
        Question.id.notin_(existing_ids),
    ]
    # V1: 使用公共排除函数，支持 no_repeat_days 时间窗口
    excluded_sub = _build_excluded_question_subquery(
        user_id=user_id,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
    )
    if excluded_sub is not None:
        conditions.append(Question.id.notin_(excluded_sub))

    # 优先按薄弱知识点过滤（OR 语义，normalized_name 精确匹配）
    kp_cond = kp_any_condition(kp_names) if kp_names else None
    if kp_cond is not None:
        # Count first, then use random offset to avoid ORDER BY random() on large tables
        kp_count_q = select(func.count()).select_from(
            select(Question).where(and_(*conditions, kp_cond)).subquery()
        )
        kp_total = (await db.execute(kp_count_q)).scalar() or 0
        kp_remaining = count - len(vector_questions)
        if kp_total > 0 and kp_remaining > 0:
            kp_q = select(Question).where(and_(*conditions, kp_cond)).options(selectinload(Question.subject_ref))
            kp_q = _random_sample_query(kp_q, kp_total, min(kp_remaining, kp_total), Question.id)
            result = await db.execute(kp_q)
            kp_fill = list(result.scalars().all())

            for fq in kp_fill:
                if fq.id not in existing_ids:
                    existing_ids.add(fq.id)
                    vector_questions.append(fq)
                    metadata[fq.id] = {
                        "recommend_reason": f"薄弱知识点补齐：{'、'.join(kp_names[:3])}",
                        "recommend_score": None,
                        "strategy": "kp_fallback",
                        "similarity": None,
                    }
                    if len(vector_questions) >= count:
                        break

    # 4. 最终随机补齐
    if len(vector_questions) < count:
        remaining = count - len(vector_questions)
        fill_q = select(func.count()).select_from(
            select(Question).where(and_(*conditions, Question.id.notin_(existing_ids))).subquery()
        )
        total = (await db.execute(fill_q)).scalar() or 0
        fill_q = (
            select(Question)
            .where(and_(*conditions, Question.id.notin_(existing_ids)))
            .options(selectinload(Question.subject_ref))
        )
        fill_q = _random_sample_query(fill_q, total, remaining, Question.id)
        result = await db.execute(fill_q)
        random_fill = list(result.scalars().all())

        for fq in random_fill:
            metadata[fq.id] = {
                "recommend_reason": "随机补齐",
                "recommend_score": None,
                "strategy": "random_fallback",
                "similarity": None,
            }
        vector_questions.extend(random_fill)

    return await _maybe_finalize_smart(vector_questions[:count], metadata, skip_finalize, db, user_id, subject_code,
                                 request_id=request_id,
                                 experiment_id=experiment_info.get("experiment_id"),
                                 variant_key=experiment_info.get("variant_key"))


async def _finalize_smart(
    questions: list[Question],
    metadata: dict[int, dict],
    db: AsyncSession,
    user_id: int,
    subject_code: str,
    request_id: str | None = None,
    experiment_id: int | None = None,
    variant_key: str | None = None,
) -> tuple[list[Question], dict[int, dict]]:
    """smart 模式统一收尾：仅为最终实际返回的题目写推荐日志。

    每道题可以来自不同的 fallback/strategy，甚至在聚合科目模式下携带不同的
    subject_id。日志因此按题保留 strategy / strategy_config_id / 实验上下文，
    而不是用一个“主导策略”覆盖整批结果。
    """
    try:
        from app.services import recommendation_log_service

        recs: list[dict] = []
        for question in questions:
            meta = metadata.get(question.id, {})
            recs.append({
                "question_id": question.id,
                # 聚合刷题时 subject_code 可能是父科目；题目自身 subject_id 才是
                # 真实归属，指标必须按这个值记录。
                "subject_id": question.subject_id,
                "recommend_score": meta.get("recommend_score"),
                "similarity": meta.get("similarity"),
                "reason": meta.get("recommend_reason"),
                "strategy": meta.get("strategy", "fallback"),
                "strategy_config_id": meta.get("strategy_config_id"),
                "experiment_id": meta.get("experiment_id", experiment_id),
                "variant_key": meta.get("variant_key", variant_key),
            })

        if recs:
            await recommendation_log_service.create_recommendation_logs(
                db=db,
                user_id=user_id,
                recommendations=recs,
                scene="practice_smart",
                # 兼容旧调用：逐题字段缺失时由日志服务使用这些批次默认值。
                strategy="fallback",
                request_id=request_id,
                experiment_id=experiment_id,
                variant_key=variant_key,
                strategy_config_id=None,
            )
    except Exception:
        logger.warning("smart 推荐日志写入失败（不影响结果）", exc_info=True)

    return questions, metadata


async def _smart_weakness_vector(
    db: AsyncSession,
    user_id: int,
    subject_code: str,
    count: int = 20,
    exclude_answered: bool = False,
    no_repeat_days: int | None = None,
    use_leitner: bool = True,
    exclude_ids: set[int] | None = None,
    subject_ids: list[int] | None = None,
) -> tuple[list[Question], dict[int, dict]]:
    """Phase 2 weakness_vector 策略：薄弱知识点 → 向量召回 → KP 补齐 → 随机补齐。

    供 smart_strategy="path" 的 fallback 复用。
    exclude_ids: 需要额外排除的题目 ID 集合（如 path 策略已选的题）。
    subject_ids: 精确 subject_id 列表，提供时跳过 resolve_subject_ids 递归扩展。
    """
    exclude_ids = exclude_ids or set()
    metadata: dict[int, dict] = {}

    # 获取薄弱知识点
    weak_kps: list[dict] = []
    try:
        from app.services import mastery_service
        weak_kps = await mastery_service.get_user_weak_knowledge_points(
            db, user_id, subject_code, limit=5,
        )
    except Exception:
        logger.warning("mastery_service.get_user_weak_knowledge_points failed", exc_info=True)

    if not weak_kps:
        weak_kps = await _compute_weak_knowledge_points(
            db, user_id,
            subject_ids if subject_ids is not None else await resolve_subject_ids(db, subject_code),
        )

    if not weak_kps:
        # 退化为随机
        questions = await get_practice_questions(
            db=db, user_id=user_id, subject_code=subject_code, count=count,
            mode="random", exclude_answered=exclude_answered,
            no_repeat_days=no_repeat_days,
        )
        for q in questions:
            if q.id not in exclude_ids:
                metadata[q.id] = {
                    "recommend_reason": "随机推荐（薄弱知识点数据不足）",
                    "recommend_score": None,
                    "strategy": "random_fallback",
                    "similarity": None,
                }
        return [q for q in questions if q.id not in exclude_ids], metadata

    kp_names = [kp["name"] for kp in weak_kps[:5]]
    query_text = (
        f"科目：{subject_code}。请推荐这些薄弱知识点的练习题："
        f"{'、'.join(kp_names)}。要求题目适合查漏补缺和变式训练。"
    )

    result_questions: list[Question] = []
    try:
        from app.services import vector_retrieval_service
        recalls = await vector_retrieval_service.vector_recall_by_text(
            db=db, user_id=user_id, subject=subject_code,
            query_text=query_text, count=count,
            exclude_answered=exclude_answered,
            no_repeat_days=no_repeat_days,
        )
        if recalls:
            rec_ids = [r["question_id"] for r in recalls if r["question_id"] not in exclude_ids]
            if rec_ids:
                q_result = await db.execute(
                    select(Question).where(Question.id.in_(rec_ids), Question.is_active).options(selectinload(Question.subject_ref))
                )
                q_map = {q.id: q for q in q_result.scalars().all()}
                for rec in recalls:
                    q = q_map.get(rec["question_id"])
                    if q and q.id not in exclude_ids:
                        result_questions.append(q)
                        metadata[q.id] = {
                            "recommend_reason": f"薄弱知识点推荐：{'、'.join(kp_names[:3])}",
                            "recommend_score": rec.get("recommend_score"),
                            "strategy": "smart_vector",
                            "similarity": rec.get("similarity"),
                        }
    except Exception:
        logger.warning("weakness_vector 向量召回失败", exc_info=True)

    if len(result_questions) >= count:
        return result_questions[:count], metadata

    # 随机补齐
    existing_ids = {q.id for q in result_questions} | exclude_ids
    scope_ids = subject_ids if subject_ids is not None else await resolve_subject_ids(db, subject_code)
    subject_cond = Question.subject_id.in_(scope_ids)
    conditions = [
        Question.is_active,
        subject_cond,
        Question.id.notin_(existing_ids),
    ]
    # V1: 使用公共排除函数，支持 no_repeat_days 时间窗口
    excluded_sub = _build_excluded_question_subquery(
        user_id=user_id,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
    )
    if excluded_sub is not None:
        conditions.append(Question.id.notin_(excluded_sub))

    remaining = count - len(result_questions)
    fill_count_q = select(func.count()).select_from(
        select(Question).where(and_(*conditions)).subquery()
    )
    total = (await db.execute(fill_count_q)).scalar() or 0
    fill_q = (
        select(Question)
        .where(and_(*conditions))
        .options(selectinload(Question.subject_ref))
    )
    fill_q = _random_sample_query(fill_q, total, remaining, Question.id)
    fill_result = await db.execute(fill_q)
    fill_questions = list(fill_result.scalars().all())
    for fq in fill_questions:
        metadata[fq.id] = {
            "recommend_reason": "薄弱知识点补齐",
            "recommend_score": None,
            "strategy": "kp_fallback",
            "similarity": None,
        }
    result_questions.extend(fill_questions)

    return result_questions[:count], metadata


# ── V4: 智能推荐综合打分 ─────────────────────────────────────────


def _pick_graph_target_kps(
    kp_mastery: dict[int, tuple],
    *,
    limit: int = 5,
) -> list[int]:
    """Pick high-value weak KPs whose prerequisites are worth expanding.

    Low-confidence states are not treated as confirmed weakness.  This keeps
    the graph from turning an unobserved prerequisite into a hard learning
    detour while still allowing the graph helper to add a small diagnostic
    candidate for unknown *prerequisites* of a genuinely weak target.
    """
    ranked: list[tuple[int, float]] = []
    for kp_id, (mastery, confidence) in kp_mastery.items():
        mastery_value = 50.0 if mastery is None else mastery
        confidence_value = 0.0 if confidence is None else confidence
        mastery = max(0.0, min(float(mastery_value), 100.0))
        confidence = max(0.0, min(float(confidence_value), 1.0))
        if confidence < 0.3 or mastery >= 70.0:
            continue
        weakness = ((100.0 - mastery) / 100.0) * confidence
        ranked.append((kp_id, weakness))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return [kp_id for kp_id, _score in ranked[:limit]]


def _build_smart_recommendation_reason(
    reason_codes: list[str],
    kp_ids: list[int],
    kp_names: dict[int, str],
    graph_candidates: dict[int, dict] | None = None,
    blocked_kps: dict[int, list[dict]] | None = None,
) -> str:
    """Convert internal score reason codes into a concise combined Chinese reason.

    The explanation keeps the strongest recommendation signal as the main
    reason, then appends at most one useful secondary signal.  In particular,
    ``new_question`` is treated as supporting context instead of masking a more
    meaningful reason such as weak knowledge, review due, or wrong history.
    """
    graph_candidates = graph_candidates or {}
    blocked_kps = blocked_kps or {}
    reason_set = set(reason_codes)
    is_new = "new_question" in reason_set
    is_diverse = "diversity" in reason_set
    is_long_unpracticed = "long_unpracticed" in reason_set
    has_wrong_history = "wrong_history" in reason_set

    def _first_kp_name() -> str | None:
        return next((kp_names.get(k) for k in kp_ids if kp_names.get(k)), None)

    def _append_new_context(text: str) -> str:
        if not is_new:
            return text
        return f"{text} 同时推荐一道尚未练过的新题，用来检验当前掌握情况。"

    # Highest-value explanation: this question is a prerequisite selected to
    # repair a known weakness in another target KP.
    for kp_id in kp_ids:
        graph = graph_candidates.get(kp_id)
        if not graph:
            continue
        kp_name = graph.get("name") or kp_names.get(kp_id) or "这个知识点"
        origin_name = graph.get("origin_name") or "目标知识点"
        if graph.get("confirmed_gap"):
            return _append_new_context(
                f"你在「{origin_name}」上的掌握较弱，而「{kp_name}」是它的重要前置知识，建议先巩固「{kp_name}」。"
            )
        base = f"「{kp_name}」是「{origin_name}」的前置知识，目前掌握数据较少，这道题可用于快速确认基础是否扎实。"
        if is_new:
            return f"{base[:-1]}，并通过一道尚未练过的新题减少熟题记忆带来的干扰。"
        return base

    if "due_review" in reason_set:
        if has_wrong_history:
            return "这道题已进入复习窗口，而且你之前在这类题目上出现过错误，现在重做有助于巩固记忆并确认是否已经掌握。"
        return "这道题已进入复习窗口，现在练习有助于巩固记忆。"

    if "weak_kp" in reason_set:
        name = _first_kp_name()
        if name:
            if is_new:
                return f"你最近在「{name}」上的掌握度较低，推荐一道尚未练过的新题继续巩固并检验掌握情况。"
            if has_wrong_history:
                return f"你最近在「{name}」上的掌握度较低，而且之前在相关题目上出现过错误，建议继续巩固。"
            return f"你最近在「{name}」上的掌握度较低，这道题适合继续巩固。"
        if is_new:
            return "你最近在这类知识点上的掌握度较低，推荐一道尚未练过的新题继续巩固并检验掌握情况。"
        if has_wrong_history:
            return "你最近在这类知识点上的掌握度较低，而且之前在相关题目上出现过错误，建议继续巩固。"
        return "你最近在这类知识点上的掌握度较低，建议继续巩固。"

    if has_wrong_history:
        if is_long_unpracticed:
            return "你之前在这类题目上出现过错误，而且已有一段时间没有练习，建议现在重做确认是否已经掌握。"
        return "你之前在这类题目上出现过错误，建议再次练习确认是否已经掌握。"

    # A blocked target can still surface because it is overdue or has strong
    # historical signals.  Explain it honestly instead of exposing internal
    # tokens such as weak_prerequisite.
    for kp_id in kp_ids:
        blockers = blocked_kps.get(kp_id) or []
        if blockers:
            target_name = kp_names.get(kp_id) or "当前知识点"
            prereq_name = blockers[0].get("name") or "前置知识"
            return _append_new_context(
                f"「{target_name}」仍需巩固，同时「{prereq_name}」这一前置知识也较薄弱，建议结合练习。"
            )

    if "path_ready" in reason_set:
        name = _first_kp_name()
        if name:
            if is_new:
                return f"相关前置知识已经基本具备，可以继续巩固「{name}」；这道新题可用于检验能否顺利推进。"
            return f"相关前置知识已经基本具备，可以继续巩固「{name}」。"

    if is_new:
        if is_diverse:
            return "这是一道尚未练过的新题，同时用于补充近期练习的知识覆盖，检验当前掌握情况。"
        return "这是一道尚未练过的新题，用来检验当前掌握情况。"

    if is_long_unpracticed:
        if is_diverse:
            return "这个知识点已有一段时间没有练习，同时近期覆盖较少，适合现在做一次巩固。"
        return "这个知识点已有一段时间没有练习，适合现在做一次巩固。"

    if is_diverse:
        return "为避免重复刷同类题，这道题用于补充近期练习的知识覆盖。"

    return "根据你的近期答题表现和知识掌握情况推荐。"


def calculate_smart_score(
    question: Question,
    q_state,          # UserQuestionState | None
    kp_ids: list[int],
    kp_mastery: dict[int, tuple],   # kp_id -> (mastery_score, confidence)
    recent_kp_ids: set[int],
    now: datetime,
    blocked_kps: dict[int, list[dict]] | None = None,  # V6.3: kp_id -> [weak prereqs]
    graph_candidates: dict[int, dict] | None = None,  # V6.5: prereq kp -> graph context
    prerequisites_by_target: dict[int, list[dict]] | None = None,
    weights: dict[str, float] | None = None,  # 系统级 × 用户级综合权重
    graph_config: dict | None = None,
) -> tuple[float, list[str]]:
    """V4 综合打分 + V6.5 图谱候选扩展 + V6.4 权重个性化。

    维度:
      1. due_score        — 复习到期 (+40)         × due_weight
      2. overdue_score    — 逾期天数 (+2/天, max 20) × due_weight
      3. weakness_score   — 知识点薄弱              × weakness_weight
      4. wrong_history    — 错题历史 (+8/次, max 30) × wrong_weight
      5. new_question     — 新题 (+20)              × new_question_weight
      6. long_unpracticed — 长期未练                × diversity_weight
      7. diversity        — 知识点多样性 (+10)       × diversity_weight
      8. path_blocked     — 前置知识点薄弱 (最多 -25) × path_weight
      9. prerequisite_need— 推荐薄弱前置 (最多 +45)   × path_weight
     10. path_ready       — 前置已满足可推进 (+8)      × path_weight
    """
    reasons: list[str] = []

    # 分组计分
    due_total = 0.0
    weakness_total = 0.0
    wrong_total = 0.0
    new_total = 0.0
    diversity_total = 0.0
    path_total = 0.0

    graph_config = graph_config or {}
    prerequisite_mastery_threshold = max(
        1.0, min(float(graph_config.get("prerequisite_mastery_threshold", 60.0)), 100.0)
    )
    prerequisite_confidence_threshold = max(
        0.0, min(float(graph_config.get("prerequisite_confidence_threshold", 0.3)), 1.0)
    )

    # ── 1 & 2: 到期复习 + 逾期 ──
    if q_state and q_state.next_review_at and q_state.next_review_at <= now:
        due_total += 40
        reasons.append("due_review")
        overdue_days = (now - q_state.next_review_at).days
        overdue_score = min(overdue_days * 2, 20)
        due_total += overdue_score
        if overdue_score > 0:
            reasons.append(f"overdue_{overdue_days}d")

    # ── 3: 知识点薄弱 ──
    if kp_ids:
        total_ws = 0.0
        cnt = 0
        for kid in kp_ids:
            ms, conf = kp_mastery.get(kid, (50.0, 0.0))
            total_ws += (100 - ms) * conf * 0.4
            cnt += 1
        if cnt:
            ws = total_ws / cnt
            weakness_total += ws
            if ws >= 15:
                reasons.append("weak_kp")

    # ── 4: 错题历史 ──
    if q_state:
        ws = min(q_state.wrong_count * 8, 30)
        wrong_total += ws
        if q_state.wrong_count > 0:
            reasons.append("wrong_history")

    # ── 5: 新题 ──
    if not q_state or q_state.answer_count == 0:
        new_total += 20
        reasons.append("new_question")

    # ── 6: 长期未练 ──
    if q_state and q_state.last_answered_at:
        days_since = (now - q_state.last_answered_at).days
        if days_since >= 30:
            ls = min(days_since * 0.5, 15)
            diversity_total += ls
            reasons.append("long_unpracticed")

    # ── 7: 知识点多样性 ──
    if kp_ids and not set(kp_ids) & recent_kp_ids:
        diversity_total += 10
        reasons.append("diversity")

    # ── 8~10: 知识点路径感知 (V6.5) ──
    if blocked_kps is not None and kp_ids:
        has_blocked = False
        blocked_quality = 0.0
        for kid in kp_ids:
            blockers = blocked_kps.get(kid) or []
            if blockers:
                has_blocked = True
                blocked_quality = max(
                    blocked_quality,
                    max(float(b.get("path_quality") or 0.0) for b in blockers),
                )
        if has_blocked:
            # Low-confidence / low-weight edges should only have a small
            # influence; graph data is weighted evidence, not an absolute rule.
            path_total -= 25 * blocked_quality
            reasons.append("weak_prerequisite")

    if graph_candidates and kp_ids:
        best_bonus = 0.0
        for kid in kp_ids:
            graph = graph_candidates.get(kid)
            if not graph:
                continue
            path_quality = max(0.0, min(float(graph.get("path_quality") or 0.0), 1.0))
            raw_origin_mastery = graph.get("origin_mastery_score")
            raw_origin_conf = graph.get("origin_mastery_confidence")
            raw_prereq_mastery = graph.get("mastery_score")
            raw_prereq_conf = graph.get("mastery_confidence")
            origin_mastery = max(0.0, min(float(50.0 if raw_origin_mastery is None else raw_origin_mastery), 100.0))
            origin_conf = max(0.0, min(float(0.0 if raw_origin_conf is None else raw_origin_conf), 1.0))
            prereq_mastery = max(0.0, min(float(50.0 if raw_prereq_mastery is None else raw_prereq_mastery), 100.0))
            prereq_conf = max(0.0, min(float(0.0 if raw_prereq_conf is None else raw_prereq_conf), 1.0))

            origin_need = ((100.0 - origin_mastery) / 100.0) * origin_conf
            if graph.get("confirmed_gap"):
                prereq_gap = max(
                    0.0,
                    (prerequisite_mastery_threshold - prereq_mastery)
                    / prerequisite_mastery_threshold,
                ) * prereq_conf
                bonus = 45.0 * (0.55 + 0.45 * origin_need) * (0.65 + 0.35 * prereq_gap) * path_quality
            else:
                # Unknown prerequisite: diagnostic exploration only.  Never let
                # it dominate a confirmed weakness.
                bonus = 10.0 * (0.5 + 0.5 * origin_need) * path_quality
            best_bonus = max(best_bonus, bonus)

        if best_bonus > 0:
            path_total += best_bonus
            reasons.append("prerequisite_need")

    if prerequisites_by_target and kp_ids and not any(k in (blocked_kps or {}) for k in kp_ids):
        # Only award "ready to progress" when the KP has direct prerequisites
        # and every one is sufficiently observed + mastered.  Unknown prereqs
        # are diagnostic candidates, not proof that the path is unlocked.
        for kid in kp_ids:
            direct_prereqs = [
                p for p in (prerequisites_by_target.get(kid) or [])
                if int(p.get("depth") or 0) == 1
            ]
            if direct_prereqs and all(
                not p.get("unknown_gap")
                and float(p.get("mastery_score") or 0.0) >= prerequisite_mastery_threshold
                and float(p.get("mastery_confidence") or 0.0) >= prerequisite_confidence_threshold
                for p in direct_prereqs
            ):
                path_total += 8
                reasons.append("path_ready")
                break

    # ── V6.4: 应用个性化权重 ──
    if weights:
        score = (
            due_total * weights.get("due_weight", 1.0)
            + weakness_total * weights.get("weakness_weight", 1.0)
            + wrong_total * weights.get("wrong_weight", 1.0)
            + new_total * weights.get("new_question_weight", 1.0)
            + diversity_total * weights.get("diversity_weight", 1.0)
            + path_total * weights.get("path_weight", 1.0)
        )
    else:
        score = due_total + weakness_total + wrong_total + new_total + diversity_total + path_total

    return score, reasons


async def get_smart_scored_questions(
    db: AsyncSession,
    user_id: int,
    subject_code: str,
    count: int = 20,
    exclude_answered: bool = False,
    no_repeat_days: int | None = None,
    request_id: str | None = None,
    subject_ids: list[int] | None = None,
) -> tuple[list[Question], dict[int, dict]]:
    """V4 综合打分推荐。

    流程:
      1. 构建候选题池 (candidate_limit)
      2. 批量加载 UserQuestionState / UserKnowledgeState
      3. 查询最近练习知识点 (diversity)
      4. 批量加载 QuestionKnowledgePoint 映射
      5. 逐题打分 → 降序排列
      6. 知识点多样性控制 (同一 KP <= 50%)
      7. 不足时 5 层降级

    降级链:
      高分候选 → 放宽多样性 → 随机补齐(含24h内) → 放弃24h限制重查 → 最终随机
    """
    from app.models.question_knowledge_point import QuestionKnowledgePoint
    from app.models.user_knowledge_state import UserKnowledgeState
    from app.models.user_question_state import UserQuestionState

    now = utcnow()
    metadata: dict[int, dict] = {}
    fallback_level = 0

    # Admin 全局配置：default_scored 控制系统级权重和图谱门槛。
    # 配置读取失败时必须退化到内置默认值，不能影响刷题。
    scored_runtime = {
        "strategy_config_id": None,
        "weights": {
            "due_weight": 1.0,
            "weakness_weight": 1.0,
            "wrong_weight": 1.0,
            "new_question_weight": 1.0,
            "diversity_weight": 1.0,
            "path_weight": 1.0,
        },
        "graph": {
            "weak_target_limit": 5,
            "max_depth": 2,
            "max_nodes": 24,
            "prerequisite_mastery_threshold": 60.0,
            "prerequisite_confidence_threshold": 0.3,
        },
    }
    try:
        from app.services import recommendation_strategy_service
        scored_runtime = await recommendation_strategy_service.get_scored_runtime_config(db)
    except Exception:
        logger.warning("scored 全局策略配置读取失败，使用内置默认值", exc_info=True)

    system_weights = scored_runtime.get("weights") or {}
    graph_runtime = scored_runtime.get("graph") or {}

    # ── 1. 候选题池 ──
    candidate_limit = max(count * 5, 50)
    scope_ids = subject_ids if subject_ids is not None else await resolve_subject_ids(db, subject_code)
    subject_cond = Question.subject_id.in_(scope_ids)
    conditions: list = [Question.is_active, subject_cond]

    excluded_sub = _build_excluded_question_subquery(
        user_id=user_id,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
    )
    if excluded_sub is not None:
        conditions.append(Question.id.notin_(excluded_sub))

    # 硬性排除 24 h 内做过的题
    recent_cutoff = now - timedelta(hours=24)
    recent_q_sub = select(PracticeRecord.question_id).where(
        PracticeRecord.user_id == user_id,
        PracticeRecord.answered_at >= recent_cutoff,
    ).distinct()
    conditions.append(Question.id.notin_(recent_q_sub))

    cand_query = (
        select(Question)
        .where(and_(*conditions))
        .options(selectinload(Question.subject_ref))
        .limit(candidate_limit)
    )
    cand_result = await db.execute(cand_query)
    candidates: list[Question] = list(cand_result.scalars().all())
    active_candidate_conditions = conditions

    # 24h 过滤后不足 → 放宽（降级 1）
    if len(candidates) < count:
        fallback_level = 1
        relaxed = [c for c in conditions if c is not conditions[-1]]
        active_candidate_conditions = relaxed
        relaxed_query = (
            select(Question)
            .where(and_(*relaxed))
            .options(selectinload(Question.subject_ref))
            .limit(candidate_limit)
        )
        relaxed_result = await db.execute(relaxed_query)
        candidates = list(relaxed_result.scalars().all())

    if not candidates:
        logger.warning("[smart_scored] 候选题池为空 uid=%s subject=%s", user_id, subject_code)
        return [], metadata

    # ── 1.5 用户知识状态 + 图谱候选扩展 (V6.5) ──
    # Knowledge state is loaded before question state because graph expansion
    # starts from the user's weak KPs, not from whichever questions happened to
    # be in the first DB page.
    ks_result = await db.execute(
        select(UserKnowledgeState).where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.subject_id.in_(scope_ids),
        )
    )
    kp_mastery: dict[int, tuple] = {
        s.knowledge_point_id: (s.mastery_score, s.confidence)
        for s in ks_result.scalars().all()
    }

    graph_context: dict = {
        "blocked_targets": {},
        "prerequisite_candidates": {},
        "prerequisites_by_target": {},
    }
    try:
        from app.core.config import settings as _settings
        if _settings.ADAPTIVE_LEARNING_ENABLED and _settings.ADAPTIVE_PATH_ENABLED:
            weak_target_ids = _pick_graph_target_kps(
                kp_mastery,
                limit=int(graph_runtime.get("weak_target_limit", 5)),
            )
            if weak_target_ids:
                from app.services import adaptive_learning_service
                graph_context = await adaptive_learning_service.get_recommendation_graph_context(
                    db=db,
                    user_id=user_id,
                    target_kp_ids=weak_target_ids,
                    subject_ids=scope_ids,
                    max_depth=int(graph_runtime.get("max_depth", 2)),
                    max_nodes=int(graph_runtime.get("max_nodes", 24)),
                    min_mastery=float(graph_runtime.get("prerequisite_mastery_threshold", 60.0)),
                    min_confidence=float(graph_runtime.get("prerequisite_confidence_threshold", 0.3)),
                )

                graph_candidate_ids = list(graph_context.get("prerequisite_candidates", {}).keys())
                if graph_candidate_ids:
                    existing_ids = {q.id for q in candidates}
                    graph_limit = max(count * 3, 30)
                    graph_query = (
                        select(Question)
                        .join(
                            QuestionKnowledgePoint,
                            QuestionKnowledgePoint.question_id == Question.id,
                        )
                        .where(
                            and_(
                                *active_candidate_conditions,
                                QuestionKnowledgePoint.knowledge_point_id.in_(graph_candidate_ids),
                                Question.id.notin_(existing_ids),
                            )
                        )
                        .options(selectinload(Question.subject_ref))
                        .distinct()
                        .limit(graph_limit)
                    )
                    graph_result = await db.execute(graph_query)
                    graph_questions = list(graph_result.scalars().all())
                    candidates.extend(graph_questions)
                    if graph_questions:
                        logger.info(
                            "[smart_scored_graph] uid=%s targets=%s prereq_kps=%s expanded_questions=%d",
                            user_id,
                            weak_target_ids,
                            graph_candidate_ids,
                            len(graph_questions),
                        )
    except Exception:
        # Graph is an enhancement, never a single point of failure.
        logger.warning("V6.5 图谱候选扩展失败（继续使用基础 scored）uid=%s", user_id, exc_info=True)
        graph_context = {
            "blocked_targets": {},
            "prerequisite_candidates": {},
            "prerequisites_by_target": {},
        }

    cand_ids = {q.id for q in candidates}

    # ── 2. 批量加载状态 ──
    qs_result = await db.execute(
        select(UserQuestionState).where(
            UserQuestionState.user_id == user_id,
            UserQuestionState.question_id.in_(cand_ids),
        )
    )
    q_state_map: dict[int, object] = {
        s.question_id: s for s in qs_result.scalars().all()
    }

    # ── 3. 最近练习知识点 (diversity) ──
    recent_kp_result = await db.execute(
        select(QuestionKnowledgePoint.knowledge_point_id)
        .join(PracticeRecord, PracticeRecord.question_id == QuestionKnowledgePoint.question_id)
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.subject_id.in_(scope_ids),
        )
        .order_by(PracticeRecord.answered_at.desc())
        .limit(20)
    )
    recent_kp_ids: set[int] = {r[0] for r in recent_kp_result.all()}

    # ── 4. 批量加载 QKP 映射 ──
    qkp_result = await db.execute(
        select(
            QuestionKnowledgePoint.question_id,
            QuestionKnowledgePoint.knowledge_point_id,
        ).where(QuestionKnowledgePoint.question_id.in_(cand_ids))
    )
    q_kp_map: dict[int, list[int]] = {}
    for qid, kid in qkp_result.all():
        q_kp_map.setdefault(qid, []).append(kid)

    # ── 4.5 图谱上下文 (V6.5) ──
    blocked_kps: dict[int, list[dict]] = graph_context.get("blocked_targets", {})
    graph_candidates: dict[int, dict] = graph_context.get("prerequisite_candidates", {})
    prerequisites_by_target: dict[int, list[dict]] = graph_context.get("prerequisites_by_target", {})

    # Names are needed only for the user-facing explanation; load them once for
    # all candidate KPs instead of querying while building each reason.
    all_candidate_kp_ids = list({kid for kids in q_kp_map.values() for kid in kids})
    kp_names: dict[int, str] = {}
    if all_candidate_kp_ids:
        from app.models.knowledge_point import KnowledgePoint
        kp_name_result = await db.execute(
            select(KnowledgePoint.id, KnowledgePoint.name).where(
                KnowledgePoint.id.in_(all_candidate_kp_ids),
                KnowledgePoint.subject_id.in_(scope_ids),
                KnowledgePoint.is_active == True,  # noqa: E712
            )
        )
        kp_names = {row.id: row.name for row in kp_name_result.all()}

    # ── 4.6 加载用户推荐权重 (V6.4) + Admin 系统权重 ──
    # final_weight = system_weight × user_weight。系统层用于运营调参，用户层
    # 用于自适应个性化；任意一层读取失败都回退到 1.0。
    user_weights: dict[str, float] = {key: 1.0 for key in system_weights}
    try:
        from app.core.config import settings as _settings
        if _settings.ADAPTIVE_LEARNING_ENABLED and _settings.ADAPTIVE_WEIGHT_ENABLED:
            from app.services import adaptive_learning_service
            user_weights = await adaptive_learning_service.get_recommend_weights(db, user_id)
    except Exception:
        logger.debug("V6.4 用户权重加载失败（不影响推荐）uid=%s", user_id, exc_info=True)

    weight_keys = {
        "due_weight", "weakness_weight", "wrong_weight",
        "new_question_weight", "diversity_weight", "path_weight",
    }
    rec_weights = {
        key: float(system_weights.get(key, 1.0)) * float(user_weights.get(key, 1.0))
        for key in weight_keys
    }

    # ── 5. 逐题打分 ──
    scored: list[tuple[Question, float, list[str]]] = []
    for q in candidates:
        kp_ids = q_kp_map.get(q.id, [])
        qs = q_state_map.get(q.id)
        sc, reasons = calculate_smart_score(
            q, qs, kp_ids, kp_mastery, recent_kp_ids, now,
            blocked_kps=blocked_kps,
            graph_candidates=graph_candidates,
            prerequisites_by_target=prerequisites_by_target,
            weights=rec_weights,
            graph_config=graph_runtime,
        )
        scored.append((q, sc, reasons))

    scored.sort(key=lambda x: x[1], reverse=True)

    # 调试日志
    if scored:
        top = scored[:5]
        logger.info(
            "[smart_scored] top5 uid=%s: %s",
            user_id,
            [(q.id, round(s, 1), r) for q, s, r in top],
        )

    # ── 6. 知识点多样性控制 ──
    max_per_kp = max(1, int(count * 0.5))
    selected: list[Question] = []
    selected_ids: set[int] = set()
    kp_counter: dict[int, int] = {}

    for q, sc, reasons in scored:
        kp_ids = q_kp_map.get(q.id, [])
        if kp_ids:
            min_count = min(kp_counter.get(k, 0) for k in kp_ids)
            if min_count >= max_per_kp:
                continue

        selected.append(q)
        selected_ids.add(q.id)
        for k in kp_ids:
            kp_counter[k] = kp_counter.get(k, 0) + 1
        metadata[q.id] = {
            "recommend_score": round(sc, 2),
            "recommend_reason": _build_smart_recommendation_reason(
                reasons,
                kp_ids,
                kp_names,
                graph_candidates=graph_candidates,
                blocked_kps=blocked_kps,
            ),
            "strategy": "smart_scored",
            "strategy_config_id": scored_runtime.get("strategy_config_id"),
            "similarity": None,
        }
        if len(selected) >= count:
            break

    # ── 降级 2: 放宽多样性 ──
    if len(selected) < count:
        fallback_level = max(fallback_level, 2)
        for q, sc, reasons in scored:
            if q.id in selected_ids:
                continue
            selected.append(q)
            selected_ids.add(q.id)
            metadata[q.id] = {
                "recommend_score": round(sc, 2),
                "recommend_reason": _build_smart_recommendation_reason(
                    reasons,
                    q_kp_map.get(q.id, []),
                    kp_names,
                    graph_candidates=graph_candidates,
                    blocked_kps=blocked_kps,
                ),
                "strategy": "smart_scored",
                "strategy_config_id": scored_runtime.get("strategy_config_id"),
                "similarity": None,
            }
            if len(selected) >= count:
                break

    # ── 降级 3: 随机补齐（可放宽 24h，但仍尊重 exclude_answered/no_repeat_days） ──
    if len(selected) < count:
        fallback_level = max(fallback_level, 3)
        remaining = count - len(selected)
        fill_cond = [
            Question.is_active,
            subject_cond,
            Question.id.notin_(cand_ids | selected_ids),
        ]
        if excluded_sub is not None:
            fill_cond.append(Question.id.notin_(excluded_sub))

        # Use random offset to avoid ORDER BY random() on potentially large table
        fill_count_q = select(func.count(Question.id)).where(and_(*fill_cond))
        fill_total = (await db.execute(fill_count_q)).scalar() or 0
        if fill_total <= remaining:
            fill_q = (
                select(Question)
                .where(and_(*fill_cond))
                .options(selectinload(Question.subject_ref))
                .order_by(Question.id.asc())
            )
        elif fill_total <= 2000:
            fill_q = (
                select(Question)
                .where(and_(*fill_cond))
                .options(selectinload(Question.subject_ref))
                .order_by(func.random())
                .limit(remaining)
            )
        else:
            offset = random.randint(0, fill_total - remaining)
            fill_q = (
                select(Question)
                .where(and_(*fill_cond))
                .options(selectinload(Question.subject_ref))
                .order_by(Question.id.asc())
                .offset(offset)
                .limit(remaining)
            )
        fill_result = await db.execute(fill_q)
        for fq in fill_result.scalars().all():
            selected.append(fq)
            selected_ids.add(fq.id)
            metadata[fq.id] = {
                "recommend_score": None,
                "recommend_reason": "随机补齐",
                "strategy": "random_fallback",
                "similarity": None,
            }

    # ── 降级 4: 最终兜底，才放宽 exclude_answered/no_repeat_days ──
    if len(selected) < count:
        fallback_level = max(fallback_level, 4)
        remaining = count - len(selected)
        fill_cond2 = [
            Question.is_active,
            subject_cond,
            Question.id.notin_(selected_ids),
        ]
        fill_q2_base = select(Question).where(and_(*fill_cond2)).options(selectinload(Question.subject_ref))
        fill_count2 = (
            await db.execute(select(func.count(Question.id)).where(and_(*fill_cond2)))
        ).scalar() or 0
        fill_q2 = _random_sample_query(fill_q2_base, total_count=fill_count2, need=remaining, id_col=Question.id)
        fill_result2 = await db.execute(fill_q2)
        for fq in fill_result2.scalars().all():
            if fq.id in selected_ids:
                continue
            selected.append(fq)
            selected_ids.add(fq.id)
            metadata[fq.id] = {
                "recommend_score": None,
                "recommend_reason": "题量不足，放宽重复限制补齐",
                "strategy": "repeat_window_fallback",
                "similarity": None,
            }

    logger.info(
        "[smart_recommend] user_id=%s subject_id=%s candidates=%s selected=%s fallback=%s",
        user_id,
        subject_code,
        len(candidates),
        len(selected),
        fallback_level,
    )

    # 统一由 get_smart_practice_questions / get_aggregated_smart_questions
    # 收尾，避免 scored 策略重复写推荐日志，并保证 skip_finalize 生效。
    return selected[:count], metadata


async def _compute_weak_knowledge_points(
    db: AsyncSession, user_id: int, subject_ids: list[int]
) -> list[dict]:
    """计算薄弱知识点：最近 30 天，total >= 2 且 accuracy < 0.65。

    返回按 accuracy 升序、total 降序排列的前 5 个薄弱知识点。
    """
    cutoff = utcnow() - timedelta(days=30)
    if not subject_ids:
        return []
    subject_cond = PracticeRecord.subject_id.in_(subject_ids)

    # 获取最近 30 天的做题记录，带题目的知识点
    result = await db.execute(
        select(PracticeRecord, Question.id)
        .join(Question, PracticeRecord.question_id == Question.id)
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= cutoff,
            subject_cond,
        )
    )
    rows = result.all()

    if not rows:
        return []

    kp_map = await load_question_kps(db, [qid for _record, qid in rows])

    # 按知识点聚合
    kp_stats: dict[str, dict] = {}
    for record, qid in rows:
        kps = kp_map.get(qid, [])
        for kp in kps:
            if kp not in kp_stats:
                kp_stats[kp] = {"total": 0, "correct": 0}
            kp_stats[kp]["total"] += 1
            if record.is_correct:
                kp_stats[kp]["correct"] += 1

    # 筛选薄弱知识点
    weak = []
    for kp_name, stats in kp_stats.items():
        total = stats["total"]
        correct = stats["correct"]
        if total >= 2:
            accuracy = correct / total
            if accuracy < 0.65:
                weak.append({
                    "name": kp_name,
                    "total": total,
                    "correct": correct,
                    "accuracy": round(accuracy, 4),
                })

    # 按 accuracy 升序、total 降序
    weak.sort(key=lambda x: (x["accuracy"], -x["total"]))
    return weak[:5]


async def submit_answer(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    user_answer: str,
    used_time: int | None = None,
    request_id: str | None = None,
) -> dict:
    result = await db.execute(
        select(Question)
        .options(selectinload(Question.subject_ref))
        .where(Question.id == question_id, Question.is_active)
    )
    question = result.scalar_one_or_none()
    if not question:
        raise ValueError(f"题目不存在: {question_id}")

    kp_map = await load_question_kps(db, [question_id])

    is_correct = is_answer_correct(user_answer, question.answer or "", question.question_type or "")

    record = PracticeRecord(
        user_id=user_id,
        question_id=question_id,
        subject_id=question.subject_id,
        question_type=question.question_type,
        user_answer=user_answer.strip(),
        is_correct=is_correct,
        used_time=used_time,
        answered_at=utcnow(),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    # 答题后清理向量推荐缓存（best-effort，失败不影响核心流程）
    try:
        from app.services.vector_retrieval_service import invalidate_vector_cache
        await invalidate_vector_cache(user_id)
    except Exception:
        logger.debug("向量缓存清理失败（不影响答题）uid=%d", user_id, exc_info=True)

    # ── Phase 2: 最佳效果后置操作（不影响答题主流程）──
    # 以下全部在 db.commit() 之后执行，失败不影响核心数据。
    # 注意：此时已在新的隐式事务中，catch 块不做 db.rollback()
    # 以免回滚其他并行的 best-effort 操作。
    is_wrong_added = False
    wq_id_for_prewarm = None
    try:
        if not is_correct:
            wq_obj = await record_wrong(db, user_id, question_id, user_answer.strip())
            is_wrong_added = True
            wq_id_for_prewarm = wq_obj.id
    except Exception:
        logger.warning("错题记录失败（不影响答题）qid=%d uid=%d", question_id, user_id, exc_info=True)

    try:
        await record_answer_behavior(
            db=db,
            user_id=user_id,
            question_id=question_id,
            practice_record_id=record.id,
            time_spent_sec=used_time or 0,
            is_first_correct=is_correct,
            is_final_correct=is_correct,
            user_answer=user_answer.strip(),
            correct_answer=question.answer,
            subject_id=question.subject_id,
            session_type="practice",
        )
    except Exception:
        logger.warning("答题行为记录失败（不影响答题）qid=%d uid=%d", question_id, user_id, exc_info=True)

    # ── Phase 3: 掌握度更新 + 推荐反馈（best-effort）──
    mastery_update: dict | None = None
    try:
        from app.services import mastery_service
        mastery_update = await mastery_service.update_user_knowledge_state_after_answer(
            db, user_id, question_id, is_correct, used_time=used_time,
        )
    except Exception:
        logger.warning("掌握度更新失败（不影响答题）qid=%d uid=%d", question_id, user_id, exc_info=True)

    try:
        from app.services import recommendation_log_service
        await recommendation_log_service.mark_recommendation_answered(
            db, user_id, question_id, is_correct, request_id=request_id,
            mastery_after=(mastery_update or {}).get("mastery_after"),
            mastery_delta=(mastery_update or {}).get("mastery_delta"),
        )
    except Exception:
        logger.warning("推荐日志标记失败（不影响答题）qid=%d uid=%d", question_id, user_id, exc_info=True)

    # ── V2: Leitner 盒子状态更新（best-effort）──
    try:
        from app.services import question_review_service
        await question_review_service.update_user_question_state_after_answer(
            db, user_id, question_id, is_correct, used_time=used_time,
        )
    except Exception:
        logger.warning(
            "Leitner 状态更新失败（不影响答题）qid=%d uid=%d",
            question_id, user_id, exc_info=True,
        )

    # ── V6: 个性化调度状态更新（best-effort）──
    try:
        from app.services import adaptive_learning_service
        await adaptive_learning_service.update_adaptive_state_after_answer(
            db, user_id=user_id, question_id=question_id,
            is_correct=is_correct, answer_time_seconds=used_time,
            answered_at=record.answered_at,
        )
    except Exception:
        logger.warning(
            "V6 自适应更新失败（不影响答题）qid=%d uid=%d",
            question_id, user_id, exc_info=True,
        )

    # 提交全部 best-effort 后置写入。mastery / 推荐日志 / Leitner / 自适应
    # 均不内部 commit，若不在此提交，session 在 get_db 收尾 close() 时会被
    # 回滚，这些状态每次答题都会静默丢失。
    try:
        await db.commit()
    except Exception:
        logger.warning("后置状态提交失败（不影响答题）uid=%d", user_id, exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass

    # ── Phase 4: 后台预生成 AI 错题分析（不阻塞答题流程）──
    if wq_id_for_prewarm is not None:
        try:
            from app.services.ai_prewarm_worker import enqueue_prewarm
            queued = await enqueue_prewarm(wq_id_for_prewarm, user_id)
            if not queued:
                logger.warning("Prewarm queue unavailable (Redis?), skipped wq_id=%d uid=%d", wq_id_for_prewarm, user_id)
        except Exception:
            logger.warning("AI 预生成调度失败（不影响答题）id=%d uid=%d", wq_id_for_prewarm, user_id, exc_info=True)

    return {
        "record_id": record.id,
        "question_id": question_id,
        "is_correct": is_correct,
        "correct_answer": question.answer,
        "analysis": question.analysis,
        "knowledge_points": kp_map.get(question_id, []),
        "is_wrong_added": is_wrong_added,
    }


async def batch_submit_answers(
    db: AsyncSession,
    user_id: int,
    answers: list[dict],
    session_meta: dict | None = None,
) -> dict:
    """批量提交答案，使用单个事务减少 commit 次数。

    ``session_meta`` 可选：携带时在同一事务内落库一条 PracticeSession（一次
    完整刷题会话），并依赖 (user_id, request_id) 幂等去重 —— 客户端网络重试
    不会把同一组刷题重复记为两条学习记录。旧客户端不携带 session，仅正常答题。
    """
    question_ids = [a["question_id"] for a in answers]
    result = await db.execute(
        select(Question)
        .options(selectinload(Question.subject_ref))
        .where(Question.id.in_(question_ids), Question.is_active)
    )
    questions = {q.id: q for q in result.scalars().all()}

    missing = [qid for qid in question_ids if qid not in questions]
    if missing:
        raise ValueError(f"题目不存在: {missing}")

    now = utcnow()
    records = []
    answer_request_ids: dict[int, str | None] = {}
    total_correct = 0
    total_wrong = 0

    for a in answers:
        q = questions[a["question_id"]]
        user_answer = a.get("user_answer", a.get("answer", "")).strip()
        used_time = a.get("used_time")
        answer_request_ids[q.id] = a.get("request_id")
        is_correct = is_answer_correct(
            user_answer, q.answer or "", q.question_type or "",
        )

        record = PracticeRecord(
            user_id=user_id,
            question_id=q.id,
            subject_id=q.subject_id,
            question_type=q.question_type,
            user_answer=user_answer,
            is_correct=is_correct,
            used_time=used_time,
            answered_at=now,
        )
        db.add(record)
        # 保存当前 record 对应 answer 的 used_time，避免后置逻辑引用外层循环
        # 遗留变量 ``a`` 而串题。
        records.append((record, q, is_correct, user_answer, used_time))
        if is_correct:
            total_correct += 1
        else:
            total_wrong += 1

    # ── PracticeSession 与 PracticeRecord 同事务落库 ──
    if session_meta is not None and records:
        fallback_subject_id = next(iter(questions.values())).subject_id
        try:
            session_values = _normalize_practice_session(
                session_meta,
                user_id=user_id,
                answered_count=len(records),
                total_correct=total_correct,
                total_wrong=total_wrong,
            )
        except ValueError as e:
            # 会话元数据结构非法时不阻断答题：记警告并跳过会话落库，
            # 保证用户的作答记录照常入库（session 是 optional 的增强项）。
            logger.warning("practice session 结构非法，跳过会话落库: %s", e)
            session_values = None
        if session_values is not None:
            subject_id = session_values["subject_id"]
            if subject_id is None:
                session_values["subject_id"] = fallback_subject_id
            else:
                # 客户端 subject_id 指向不存在的科目（如已被删除）时回退到
                # 本组题目的科目，避免 FK 违约导致会话被误判为重复而静默丢弃。
                from app.models.admin import Subject

                subj_exists = await db.scalar(
                    select(Subject.id).where(Subject.id == subject_id)
                )
                if subj_exists is None:
                    session_values["subject_id"] = fallback_subject_id
            if session_values["subject_id"] is not None:
                request_id = session_values["request_id"]
                dup = None
                if request_id:
                    dup = await db.scalar(
                        select(PracticeSession.id).where(
                            PracticeSession.user_id == user_id,
                            PracticeSession.request_id == request_id,
                        )
                    )
                if dup is None:
                    session_obj = PracticeSession(**session_values)
                    try:
                        # 并发重试兜底：仅唯一索引冲突回滚到 savepoint，
                        # 不破坏主提交事务（PracticeRecord 仍然正常入库）。
                        # 其它 IntegrityError 上抛，避免把真实数据错误误标成
                        # "duplicate request_id" 而静默丢弃会话。
                        async with db.begin_nested():
                            db.add(session_obj)
                            await db.flush()
                    except IntegrityError as e:
                        if not _is_unique_violation(e):
                            raise
                        logger.warning(
                            "practice session duplicate request_id=%s uid=%d; skipping",
                            request_id, user_id,
                        )

    await db.commit()

    # 全部 commit 后，逐个执行 best-effort 后置操作
    # （错题、行为、掌握度等 — 不影响主流程结果）
    wrong_question_ids_for_prewarm: list[int] = []
    for record, q, is_correct, user_answer, used_time in records:
        if not is_correct:
            try:
                from app.services.wrong_question_service import record_wrong

                wq = await record_wrong(db, user_id, q.id, user_answer)
                wrong_question_ids_for_prewarm.append(wq.id)
            except Exception:
                logger.warning("批量错题记录失败 qid=%d uid=%d", q.id, user_id, exc_info=True)

        try:
            from app.services.behavior_service import record_answer_behavior
            await record_answer_behavior(
                db=db, user_id=user_id, question_id=q.id,
                practice_record_id=record.id,
                time_spent_sec=used_time or 0,
                is_first_correct=is_correct,
                is_final_correct=is_correct,
                user_answer=user_answer,
                correct_answer=q.answer,
                subject_id=q.subject_id,
                session_type="practice",
            )
        except Exception:
            logger.warning("批量行为记录失败 qid=%d uid=%d", q.id, user_id, exc_info=True)

        mastery_update: dict | None = None
        try:
            from app.services import mastery_service
            mastery_update = await mastery_service.update_user_knowledge_state_after_answer(
                db, user_id, q.id, is_correct, used_time=used_time,
            )
        except Exception:
            logger.warning("批量掌握度更新失败 qid=%d uid=%d", q.id, user_id, exc_info=True)

        # 与单题提交保持一致：批量刷题也闭合推荐日志的 answered / mastery 指标。
        try:
            from app.services import recommendation_log_service
            await recommendation_log_service.mark_recommendation_answered(
                db, user_id, q.id, is_correct,
                request_id=answer_request_ids.get(q.id),
                mastery_after=(mastery_update or {}).get("mastery_after"),
                mastery_delta=(mastery_update or {}).get("mastery_delta"),
            )
        except Exception:
            logger.warning("批量推荐日志标记失败 qid=%d uid=%d", q.id, user_id, exc_info=True)

    # 批量路径 mastery / 推荐日志不内部 commit，统一收尾提交，否则 session 关闭时回滚丢失。
    try:
        await db.commit()
    except Exception:
        logger.warning("批量后置状态提交失败 uid=%d", user_id, exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass

    # 批量答题同样失效向量推荐缓存（版本号经 invalidate_vector_cache 递增，
    # 不在批量路径递增会导致批量提交后仍命中含已答题目的旧缓存）。
    try:
        from app.services.vector_retrieval_service import invalidate_vector_cache
        await invalidate_vector_cache(user_id)
    except Exception:
        logger.debug("批量向量缓存清理失败（不影响答题）uid=%d", user_id, exc_info=True)

    # 本次练习成功落库后统一预生成所有新增/更新错题的 AI 解析。
    # 调度失败不影响成绩返回，用户进入错题详情时仍可手动生成。
    if wrong_question_ids_for_prewarm:
        try:
            from app.services.ai_prewarm_worker import enqueue_prewarm_batch

            await enqueue_prewarm_batch(wrong_question_ids_for_prewarm, user_id)
        except Exception:
            logger.warning(
                "批量 AI 错题分析调度失败 uid=%d count=%d",
                user_id, len(wrong_question_ids_for_prewarm), exc_info=True,
            )

    kp_map = await load_question_kps(db, [q.id for _r, q, _c, _x, _y in records])
    return {
        "results": [
            {
                "record_id": r.id,
                "question_id": q.id,
                "is_correct": c,
                "correct_answer": q.answer,
                "analysis": q.analysis,
                "knowledge_points": kp_map.get(q.id, []),
            }
            for r, q, c, _, _ in records
        ],
        "total_correct": total_correct,
        "total_wrong": total_wrong,
    }


async def get_practice_stats(
    db: AsyncSession,
    user_id: int,
    days: int = 7,
) -> dict:
    base = select(
        func.count(PracticeRecord.id),
        func.coalesce(
            func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0
        ),
    ).where(PracticeRecord.user_id == user_id)

    total_row = (await db.execute(base)).one()
    total_answered = total_row[0]
    total_correct = total_row[1]
    accuracy = round(total_correct / total_answered, 4) if total_answered > 0 else 0.0

    # By subject_code
    from app.models.admin import Subject
    subject_result = await db.execute(
        select(
            PracticeRecord.subject_id,
            Subject.code,
            Subject.name,
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0
            ),
        )
        .outerjoin(Subject, PracticeRecord.subject_id == Subject.id)
        .where(PracticeRecord.user_id == user_id)
        .group_by(PracticeRecord.subject_id, Subject.code, Subject.name)
    )
    by_subject = []
    for row in subject_result.all():
        answered = row[3]
        correct = row[4]
        by_subject.append({
            "subject_id": row[0],
            "subject_code": row[1] or "",
            "subject_name": row[2] or "",
            "answered": answered,
            "correct": correct,
            "accuracy": round(correct / answered, 4) if answered > 0 else 0.0,
        })

    # Daily stats
    since = datetime.combine(date.today() - timedelta(days=days - 1), datetime.min.time())
    daily_result = await db.execute(
        select(
            func.date(PracticeRecord.answered_at),
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0
            ),
        )
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= since,
        )
        .group_by(func.date(PracticeRecord.answered_at))
        .order_by(func.date(PracticeRecord.answered_at))
    )
    daily_map = {str(r[0]): {"answered": r[1], "correct": r[2]} for r in daily_result.all()}

    daily_stats = []
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        entry = daily_map.get(d, {"answered": 0, "correct": 0})
        daily_stats.append({"date": d, **entry})

    streak = await _calc_streak(db, user_id)

    return {
        "total_answered": total_answered,
        "total_correct": total_correct,
        "accuracy": accuracy,
        "by_subject": by_subject,
        "daily_stats": daily_stats,
        "current_streak": streak,
    }


async def _calc_streak(db: AsyncSession, user_id: int) -> int:
    today = date.today()
    result = await db.execute(
        select(func.date(PracticeRecord.answered_at))
        .where(PracticeRecord.user_id == user_id)
        .distinct()
        .order_by(func.date(PracticeRecord.answered_at).desc())
    )
    dates = {row[0] for row in result.all()}

    streak = 0
    for i in range(365):
        d = today - timedelta(days=i)
        if d in dates:
            streak += 1
        else:
            break
    return streak

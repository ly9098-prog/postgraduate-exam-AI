import random
from datetime import date, datetime, timedelta
import re

import logging
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.time_utils import utcnow
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.question_import import QuestionImport  # noqa: F401 — ensures Subject mapper resolves
from app.utils.answer_normalizer import is_answer_correct
from app.services.admin_subject_service import resolve_subject_ids
from app.services.behavior_service import record_answer_behavior
from app.services.wrong_question_service import record_wrong

logger = logging.getLogger(__name__)


def _random_sample_query(query, total_count: int, need: int, id_col=None):
    """Replace ``ORDER BY random()`` with a random offset for efficiency.

    For small result sets (total_count <= 2000), uses ``ORDER BY random()``
    which is simpler and well-tested.  For large result sets, uses a random
    offset to avoid the expensive full-table sort.

    The offset approach assumes roughly evenly-distributed IDs and is only
    a best-effort randomization — it's good enough for practice sampling
    where perfect uniformity isn't required.
    """
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
        .where(Subject.is_active == True)
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
        conds = [Question.is_active == True, Question.subject_id == sid]
        if knowledge_points:
            for kp in knowledge_points:
                conds.append(Question.knowledge_points.like(f'%"{kp}"%'))

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
    smart_strategy: str = "weakness_vector",
) -> tuple[list[Question], dict[int, dict]]:
    """smart 模式聚合刷题：为每个精确 subject 独立生成 smart 候选后轮询合并。

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
            db=db, user_id=user_id, subject=sid_code,
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
        return merged_qs, merged_meta

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
    subject: str,
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
        ids = await resolve_subject_ids(db, subject)
    subject_cond = Question.subject_id.in_(ids)
    base_conditions = [Question.is_active == True, subject_cond]

    if knowledge_points:
        for kp in knowledge_points:
            base_conditions.append(Question.knowledge_points.like(f'%"{kp}"%'))

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
    subject: str,
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
                    select(Question).where(Question.id.in_(rec_ids), Question.is_active == True).options(selectinload(Question.subject_ref))
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

    ids = await resolve_subject_ids(db, subject)
    subject_cond = Question.subject_id.in_(ids)
    conditions = [
        Question.is_active == True,
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
    subject: str,
    request_id: str | None = None,
    experiment_id: int | None = None,
    variant_key: str | None = None,
) -> tuple[list[Question], dict[int, dict]]:
    """条件化收尾：skip=True 时跳过推荐日志，由调用方统一写入。"""
    if skip:
        return questions, metadata
    return await _finalize_smart(
        questions, metadata, db, user_id, subject,
        request_id=request_id,
        experiment_id=experiment_id,
        variant_key=variant_key,
    )


async def get_smart_practice_questions(
    db: AsyncSession,
    user_id: int,
    subject: str,
    count: int = 20,
    exclude_answered: bool = False,
    no_repeat_days: int | None = None,
    use_leitner: bool = True,
    request_id: str | None = None,
    smart_strategy: str = "weakness_vector",
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

    # V4: 综合打分策略
    if smart_strategy == "scored":
        try:
            scored_qs, scored_meta = await get_smart_scored_questions(
                db=db, user_id=user_id, subject=subject, count=count,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
                request_id=request_id,
                subject_ids=subject_ids,
            )
            if len(scored_qs) >= count:
                return await _maybe_finalize_smart(
                    scored_qs[:count], scored_meta, skip_finalize, db, user_id, subject,
                    request_id=request_id,
                    experiment_id=experiment_info.get("experiment_id"),
                    variant_key=experiment_info.get("variant_key"),
                )
            # 不足时 fallback 到 path / weakness_vector
            logger.info("scored 策略题量不足 (%d/%d)，fallback",
                        len(scored_qs), count)
        except Exception:
            logger.warning("scored 策略失败，fallback", exc_info=True)

    # Phase 3: 知识路径策略
    if smart_strategy == "path":
        try:
            from app.services import knowledge_path_service

            path_result = await knowledge_path_service.get_user_path_recommendations(
                db=db,
                user_id=user_id,
                subject=subject,
                limit=8,
                questions_per_node=3,
            )
            path_qids = path_result.get("recommended_question_ids", [])
            if path_qids:
                # 获取题目
                q_result = await db.execute(
                    select(Question).where(
                        Question.id.in_(path_qids[:count]),
                        Question.is_active == True,
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
                        path_questions[:count], metadata, skip_finalize, db, user_id, subject,
                        request_id=request_id,
                        experiment_id=experiment_info.get("experiment_id"),
                        variant_key=experiment_info.get("variant_key"),
                    )

                # 不足时 fallback 到 weakness_vector
                logger.info("path 策略题量不足 (%d/%d)，fallback 到 weakness_vector",
                            len(path_questions), count)
                remaining = count - len(path_questions)
                fallback_questions, fallback_meta = await _smart_weakness_vector(
                    db, user_id, subject, count=remaining,
                    exclude_answered=exclude_answered,
                    no_repeat_days=no_repeat_days,
                    exclude_ids={q.id for q in path_questions},
                    subject_ids=subject_ids,
                )
                path_questions.extend(fallback_questions)
                metadata.update(fallback_meta)
                return await _maybe_finalize_smart(
                    path_questions[:count], metadata, skip_finalize, db, user_id, subject,
                    request_id=request_id,
                    experiment_id=experiment_info.get("experiment_id"),
                    variant_key=experiment_info.get("variant_key"),
                )
        except Exception:
            logger.warning("knowledge_path 策略失败，fallback 到 weakness_vector", exc_info=True)
        # path 策略完全失败，继续走 weakness_vector 逻辑

    # 1. 获取薄弱知识点（Phase 2 优先使用掌握度画像）
    weak_kps: list[dict] = []
    weak_source = "unknown"
    try:
        from app.services import mastery_service
        weak_kps = await mastery_service.get_user_weak_knowledge_points(
            db, user_id, subject, limit=5,
        )
        if weak_kps:
            weak_source = "knowledge_state"
    except Exception:
        logger.warning("mastery_service.get_user_weak_knowledge_points failed, fallback", exc_info=True)

    if not weak_kps:
        # Fallback: Phase 1 的临时统计
        weak_kps = await _compute_weak_knowledge_points(db, user_id, subject)
        if weak_kps:
            weak_source = "practice_record"

    if not weak_kps:
        # 没有足够的做题记录来判断薄弱点，退化为随机
        logger.info("smart 模式: 无足够做题记录，退化为随机")
        questions = await get_practice_questions(
            db=db, user_id=user_id, subject=subject, count=count,
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
        return await _maybe_finalize_smart(questions, metadata, skip_finalize, db, user_id, subject,
                                     request_id=request_id,
                                     experiment_id=experiment_info.get("experiment_id"),
                                     variant_key=experiment_info.get("variant_key"))

    # 2. 构造 query_text 并向量召回
    kp_names = [kp["name"] for kp in weak_kps[:5]]
    query_text = (
        f"科目：{subject}。请推荐这些薄弱知识点的练习题："
        f"{'、'.join(kp_names)}。要求题目适合查漏补缺和变式训练。"
    )

    vector_questions: list[Question] = []
    try:
        from app.services import vector_retrieval_service

        recalls = await vector_retrieval_service.vector_recall_by_text(
            db=db,
            user_id=user_id,
            subject=subject,
            query_text=query_text,
            count=count,
            exclude_answered=exclude_answered,
            no_repeat_days=no_repeat_days,
        )
        if recalls:
            rec_ids = [r["question_id"] for r in recalls]
            q_result = await db.execute(
                select(Question).where(Question.id.in_(rec_ids), Question.is_active == True).options(selectinload(Question.subject_ref))
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

    if len(vector_questions) >= count:
        return await _maybe_finalize_smart(vector_questions[:count], metadata, skip_finalize, db, user_id, subject,
                                     request_id=request_id,
                                     experiment_id=experiment_info.get("experiment_id"),
                                     variant_key=experiment_info.get("variant_key"))

    # 3. 补齐：按薄弱知识点过滤 + 随机
    existing_ids = {q.id for q in vector_questions}
    scope_ids = subject_ids if subject_ids is not None else await resolve_subject_ids(db, subject)
    subject_cond = Question.subject_id.in_(scope_ids)
    conditions = [
        Question.is_active == True,
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

    # 优先按薄弱知识点过滤
    if kp_names:
        kp_conditions = []
        for kp in kp_names:
            kp_conditions.append(Question.knowledge_points.like(f'%"{kp}"%'))
        kp_cond = or_(*kp_conditions)
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

    return await _maybe_finalize_smart(vector_questions[:count], metadata, skip_finalize, db, user_id, subject,
                                 request_id=request_id,
                                 experiment_id=experiment_info.get("experiment_id"),
                                 variant_key=experiment_info.get("variant_key"))


async def _finalize_smart(
    questions: list[Question],
    metadata: dict[int, dict],
    db: AsyncSession,
    user_id: int,
    subject: str,
    request_id: str | None = None,
    experiment_id: int | None = None,
    variant_key: str | None = None,
) -> tuple[list[Question], dict[int, dict]]:
    """smart 模式统一收尾：写推荐日志（best-effort），返回结果。"""
    try:
        from collections import Counter
        from app.services import recommendation_log_service

        recs = [
            {
                "question_id": qid,
                "subject": subject,
                "recommend_score": meta.get("recommend_score"),
                "similarity": meta.get("similarity"),
                "reason": meta.get("recommend_reason"),
            }
            for qid, meta in metadata.items()
        ]
        if recs:
            # 取出现最多的 strategy 而非仅第一条
            strategy_counts = Counter(
                meta.get("strategy", "fallback") for meta in metadata.values()
            )
            dominant_strategy = strategy_counts.most_common(1)[0][0]

            await recommendation_log_service.create_recommendation_logs(
                db=db,
                user_id=user_id,
                recommendations=recs,
                scene="practice_smart",
                strategy=dominant_strategy,
                request_id=request_id,
                experiment_id=experiment_id,
                variant_key=variant_key,
            )
    except Exception:
        logger.warning("smart 推荐日志写入失败（不影响结果）", exc_info=True)

    return questions, metadata


async def _smart_weakness_vector(
    db: AsyncSession,
    user_id: int,
    subject: str,
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
            db, user_id, subject, limit=5,
        )
    except Exception:
        logger.warning("mastery_service.get_user_weak_knowledge_points failed", exc_info=True)

    if not weak_kps:
        weak_kps = await _compute_weak_knowledge_points(db, user_id, subject)

    if not weak_kps:
        # 退化为随机
        questions = await get_practice_questions(
            db=db, user_id=user_id, subject=subject, count=count,
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
        f"科目：{subject}。请推荐这些薄弱知识点的练习题："
        f"{'、'.join(kp_names)}。要求题目适合查漏补缺和变式训练。"
    )

    result_questions: list[Question] = []
    try:
        from app.services import vector_retrieval_service
        recalls = await vector_retrieval_service.vector_recall_by_text(
            db=db, user_id=user_id, subject=subject,
            query_text=query_text, count=count,
            exclude_answered=exclude_answered,
            no_repeat_days=no_repeat_days,
        )
        if recalls:
            rec_ids = [r["question_id"] for r in recalls if r["question_id"] not in exclude_ids]
            if rec_ids:
                q_result = await db.execute(
                    select(Question).where(Question.id.in_(rec_ids), Question.is_active == True).options(selectinload(Question.subject_ref))
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
    scope_ids = subject_ids if subject_ids is not None else await resolve_subject_ids(db, subject)
    subject_cond = Question.subject_id.in_(scope_ids)
    conditions = [
        Question.is_active == True,
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


def calculate_smart_score(
    question: Question,
    q_state,          # UserQuestionState | None
    kp_ids: list[int],
    kp_mastery: dict[int, tuple],   # kp_id -> (mastery_score, confidence)
    recent_kp_ids: set[int],
    now: datetime,
    blocked_kps: dict[int, list[dict]] | None = None,  # V6.3: kp_id -> [weak prereqs]
    weights: dict[str, float] | None = None,  # V6.4: 个性化权重
) -> tuple[float, list[str]]:
    """V4 综合打分 + V6.3 路径感知 + V6.4 权重个性化。

    维度:
      1. due_score        — 复习到期 (+40)         × due_weight
      2. overdue_score    — 逾期天数 (+2/天, max 20) × due_weight
      3. weakness_score   — 知识点薄弱              × weakness_weight
      4. wrong_history    — 错题历史 (+8/次, max 30) × wrong_weight
      5. new_question     — 新题 (+20)              × new_question_weight
      6. long_unpracticed — 长期未练                × diversity_weight
      7. diversity        — 知识点多样性 (+10)       × diversity_weight
      8. path_blocked     — 前置知识点薄弱 (-25)     × path_weight
      9. path_unlock      — 前置已掌握可推进 (+15)   × path_weight
    """
    reasons: list[str] = []

    # 分组计分
    due_total = 0.0
    weakness_total = 0.0
    wrong_total = 0.0
    new_total = 0.0
    diversity_total = 0.0
    path_total = 0.0

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

    # ── 8 & 9: 知识点路径感知 (V6.3) ──
    if blocked_kps is not None and kp_ids:
        has_blocked = False
        has_unlock = False
        for kid in kp_ids:
            if kid in blocked_kps:
                has_blocked = True
            else:
                ms, conf = kp_mastery.get(kid, (50.0, 0.0))
                if conf >= 0.3 and ms < 60:
                    has_unlock = True
        if has_blocked:
            path_total -= 25
            reasons.append("weak_prerequisite")
        if has_unlock and not has_blocked:
            path_total += 15
            reasons.append("path_unlock")

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
    subject: str,
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
    from app.models.user_question_state import UserQuestionState
    from app.models.user_knowledge_state import UserKnowledgeState
    from app.models.question_knowledge_point import QuestionKnowledgePoint

    now = utcnow()
    metadata: dict[int, dict] = {}
    fallback_level = 0

    # ── 1. 候选题池 ──
    candidate_limit = max(count * 5, 50)
    scope_ids = subject_ids if subject_ids is not None else await resolve_subject_ids(db, subject)
    subject_cond = Question.subject_id.in_(scope_ids)
    conditions: list = [Question.is_active == True, subject_cond]

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

    # 24h 过滤后不足 → 放宽（降级 1）
    if len(candidates) < count:
        fallback_level = 1
        relaxed = [c for c in conditions if c is not conditions[-1]]
        relaxed_query = (
            select(Question)
            .where(and_(*relaxed))
            .options(selectinload(Question.subject_ref))
            .limit(candidate_limit)
        )
        relaxed_result = await db.execute(relaxed_query)
        candidates = list(relaxed_result.scalars().all())

    if not candidates:
        logger.warning("[smart_scored] 候选题池为空 uid=%s subject=%s", user_id, subject)
        return [], metadata

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

    ks_result = await db.execute(
        select(UserKnowledgeState).where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.subject == subject,
        )
    )
    kp_mastery: dict[int, tuple] = {
        s.knowledge_point_id: (s.mastery_score, s.confidence)
        for s in ks_result.scalars().all()
    }

    # ── 3. 最近练习知识点 (diversity) ──
    recent_kp_result = await db.execute(
        select(QuestionKnowledgePoint.knowledge_point_id)
        .join(PracticeRecord, PracticeRecord.question_id == QuestionKnowledgePoint.question_id)
        .where(
            PracticeRecord.user_id == user_id,
            or_(
                PracticeRecord.subject == subject,
                PracticeRecord.subject.like(f"{subject}-%"),
            ),
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

    # ── 4.5 批量加载前置知识点阻塞信息 (V6.3) ──
    blocked_kps: dict[int, list[dict]] = {}
    try:
        from app.core.config import settings as _settings
        if _settings.ADAPTIVE_LEARNING_ENABLED and _settings.ADAPTIVE_PATH_ENABLED:
            all_kp_ids = list({kid for kids in q_kp_map.values() for kid in kids})
            if all_kp_ids:
                from app.services import adaptive_learning_service
                blocked_kps = await adaptive_learning_service.get_blocked_knowledge_points(
                    db, user_id, all_kp_ids, subject,
                )
    except Exception:
        logger.debug("V6.3 前置知识点加载失败（不影响推荐）uid=%s", user_id, exc_info=True)

    # ── 4.6 加载用户推荐权重 (V6.4) ──
    rec_weights: dict[str, float] | None = None
    try:
        from app.core.config import settings as _settings
        if _settings.ADAPTIVE_LEARNING_ENABLED and _settings.ADAPTIVE_WEIGHT_ENABLED:
            from app.services import adaptive_learning_service
            rec_weights = await adaptive_learning_service.get_recommend_weights(db, user_id)
    except Exception:
        logger.debug("V6.4 权重加载失败（不影响推荐）uid=%s", user_id, exc_info=True)

    # ── 5. 逐题打分 ──
    scored: list[tuple[Question, float, list[str]]] = []
    for q in candidates:
        kp_ids = q_kp_map.get(q.id, [])
        qs = q_state_map.get(q.id)
        sc, reasons = calculate_smart_score(
            q, qs, kp_ids, kp_mastery, recent_kp_ids, now,
            blocked_kps=blocked_kps, weights=rec_weights,
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
            "recommend_reason": ",".join(reasons),
            "strategy": "smart_scored",
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
                "recommend_reason": ",".join(reasons),
                "strategy": "smart_scored",
                "similarity": None,
            }
            if len(selected) >= count:
                break

    # ── 降级 3: 随机补齐 (排除候选题) ──
    if len(selected) < count:
        fallback_level = max(fallback_level, 3)
        remaining = count - len(selected)
        fill_cond = [
            Question.is_active == True,
            subject_cond,
            Question.id.notin_(cand_ids | selected_ids),
        ]
        fill_q = (
            select(Question)
            .where(and_(*fill_cond))
            .options(selectinload(Question.subject_ref))
            .order_by(func.random())
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

    # ── 降级 4: 放弃 24h 限制重查 ──
    if len(selected) < count:
        fallback_level = max(fallback_level, 4)
        remaining = count - len(selected)
        fill_cond2 = [
            Question.is_active == True,
            subject_cond,
            Question.id.notin_(selected_ids),
        ]
        if excluded_sub is not None:
            fill_cond2.append(Question.id.notin_(excluded_sub))
        fill_q2 = (
            select(Question)
            .where(and_(*fill_cond2))
            .options(selectinload(Question.subject_ref))
            .order_by(func.random())
            .limit(remaining)
        )
        fill_result2 = await db.execute(fill_q2)
        for fq in fill_result2.scalars().all():
            selected.append(fq)
            selected_ids.add(fq.id)
            metadata[fq.id] = {
                "recommend_score": None,
                "recommend_reason": "放弃24h限制补齐",
                "strategy": "no_24h_fallback",
                "similarity": None,
            }

    logger.info(
        "[smart_recommend] user_id=%s subject_id=%s candidates=%s selected=%s fallback=%s",
        user_id,
        subject,
        len(candidates),
        len(selected),
        fallback_level,
    )

    return await _finalize_smart(
        selected[:count], metadata, db, user_id, subject,
        request_id=request_id,
    )


async def _compute_weak_knowledge_points(
    db: AsyncSession, user_id: int, subject: str
) -> list[dict]:
    """计算薄弱知识点：最近 30 天，total >= 2 且 accuracy < 0.65。

    返回按 accuracy 升序、total 降序排列的前 5 个薄弱知识点。
    """
    cutoff = utcnow() - timedelta(days=30)
    subject_cond = or_(
        PracticeRecord.subject == subject,
        PracticeRecord.subject.like(f"{subject}-%"),
    )

    # 获取最近 30 天的做题记录，带题目的 knowledge_points
    result = await db.execute(
        select(PracticeRecord, Question.knowledge_points)
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

    # 按知识点聚合
    kp_stats: dict[str, dict] = {}
    for record, kps_json in rows:
        kps = kps_json or []
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
        select(Question).where(
            Question.id == question_id, Question.is_active == True
        )
    )
    question = result.scalar_one_or_none()
    if not question:
        raise ValueError(f"题目不存在: {question_id}")

    is_correct = is_answer_correct(user_answer, question.answer or "", question.question_type or "")

    record = PracticeRecord(
        user_id=user_id,
        question_id=question_id,
        subject=question.subject_ref.code if question.subject_ref else "",
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
            subject=question.subject_ref.code if question.subject_ref else "",
            session_type="practice",
        )
    except Exception:
        logger.warning("答题行为记录失败（不影响答题）qid=%d uid=%d", question_id, user_id, exc_info=True)

    # ── Phase 3: 掌握度更新 + 推荐反馈（best-effort）──
    try:
        from app.services import mastery_service
        await mastery_service.update_user_knowledge_state_after_answer(
            db, user_id, question_id, is_correct, used_time=used_time,
        )
    except Exception:
        logger.warning("掌握度更新失败（不影响答题）qid=%d uid=%d", question_id, user_id, exc_info=True)

    try:
        from app.services import recommendation_log_service
        await recommendation_log_service.mark_recommendation_answered(
            db, user_id, question_id, is_correct, request_id=request_id,
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
        "knowledge_points": question.knowledge_points or [],
        "is_wrong_added": is_wrong_added,
    }


async def batch_submit_answers(
    db: AsyncSession,
    user_id: int,
    answers: list[dict],
) -> dict:
    """批量提交答案，使用单个事务减少 commit 次数。"""
    question_ids = [a["question_id"] for a in answers]
    result = await db.execute(
        select(Question).where(
            Question.id.in_(question_ids), Question.is_active == True
        )
    )
    questions = {q.id: q for q in result.scalars().all()}

    missing = [qid for qid in question_ids if qid not in questions]
    if missing:
        raise ValueError(f"题目不存在: {missing}")

    now = utcnow()
    records = []
    total_correct = 0
    total_wrong = 0

    for a in answers:
        q = questions[a["question_id"]]
        user_answer = a.get("user_answer", a.get("answer", "")).strip()
        is_correct = is_answer_correct(
            user_answer, q.answer or "", q.question_type or "",
        )

        record = PracticeRecord(
            user_id=user_id,
            question_id=q.id,
            subject=q.subject_ref.code if q.subject_ref else "",
            question_type=q.question_type,
            user_answer=user_answer,
            is_correct=is_correct,
            used_time=a.get("used_time"),
            answered_at=now,
        )
        db.add(record)
        records.append((record, q, is_correct, user_answer))
        if is_correct:
            total_correct += 1
        else:
            total_wrong += 1

    await db.commit()

    # 全部 commit 后，逐个执行 best-effort 后置操作
    # （错题、行为、掌握度等 — 不影响主流程结果）
    for record, q, is_correct, user_answer in records:
        if not is_correct:
            try:
                from app.services.wrong_question_service import record_wrong

                wq = await record_wrong(db, user_id, q.id, user_answer)
                try:
                    from app.services.ai_prewarm_worker import enqueue_prewarm
                    await enqueue_prewarm(wq.id, user_id)
                except Exception:
                    pass
            except Exception:
                logger.warning("批量错题记录失败 qid=%d uid=%d", q.id, user_id, exc_info=True)

        try:
            from app.services.behavior_service import record_answer_behavior
            await record_answer_behavior(
                db=db, user_id=user_id, question_id=q.id,
                practice_record_id=record.id,
                time_spent_sec=a.get("used_time", 0),
                is_first_correct=is_correct,
                is_final_correct=is_correct,
                user_answer=user_answer,
                correct_answer=q.answer,
                subject=q.subject_ref.code if q.subject_ref else "",
                session_type="practice",
            )
        except Exception:
            logger.warning("批量行为记录失败 qid=%d uid=%d", q.id, user_id, exc_info=True)

        try:
            from app.services import mastery_service
            await mastery_service.update_user_knowledge_state_after_answer(
                db, user_id, q.id, is_correct, used_time=a.get("used_time"),
            )
        except Exception:
            logger.warning("批量掌握度更新失败 qid=%d uid=%d", q.id, user_id, exc_info=True)

    return {
        "results": [
            {
                "record_id": r.id,
                "question_id": q.id,
                "is_correct": c,
                "correct_answer": q.answer,
                "analysis": q.analysis,
                "knowledge_points": q.knowledge_points or [],
            }
            for r, q, c, _ in records
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
            func.sum(case((PracticeRecord.is_correct == True, 1), else_=0)), 0
        ),
    ).where(PracticeRecord.user_id == user_id)

    total_row = (await db.execute(base)).one()
    total_answered = total_row[0]
    total_correct = total_row[1]
    accuracy = round(total_correct / total_answered, 4) if total_answered > 0 else 0.0

    # By subject
    subject_result = await db.execute(
        select(
            PracticeRecord.subject,
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct == True, 1), else_=0)), 0
            ),
        )
        .where(PracticeRecord.user_id == user_id)
        .group_by(PracticeRecord.subject)
    )
    by_subject = {}
    for row in subject_result.all():
        answered = row[1]
        correct = row[2]
        by_subject[row[0]] = {
            "answered": answered,
            "correct": correct,
            "accuracy": round(correct / answered, 4) if answered > 0 else 0.0,
        }

    # Daily stats
    since = datetime.combine(date.today() - timedelta(days=days - 1), datetime.min.time())
    daily_result = await db.execute(
        select(
            func.date(PracticeRecord.answered_at),
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct == True, 1), else_=0)), 0
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


async def get_wrong_questions(
    db: AsyncSession,
    user_id: int,
    subject: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    from app.services.wrong_question_service import list_wrong

    items, total = await list_wrong(
        db, user_id, subject=subject, page=page, page_size=page_size
    )

    question_ids = [wq.question_id for wq in items]
    if question_ids:
        q_result = await db.execute(
            select(Question).where(Question.id.in_(question_ids))
        )
        q_map = {q.id: q for q in q_result.scalars().all()}
    else:
        q_map = {}

    wrong_list = []
    for wq in items:
        q = q_map.get(wq.question_id)
        wrong_list.append({
            "id": wq.id,
            "question_id": wq.question_id,
            "wrong_answer": wq.wrong_answer,
            "review_count": wq.review_count,
            "mastered": wq.mastered,
            "last_review_at": str(wq.last_review_at) if wq.last_review_at else None,
            "question": {
                "id": q.id,
                "subject": q.subject_ref.code if q.subject_ref else "",
                "question_type": q.question_type,
                "content": q.content,
                "options": q.options,
                "answer": q.answer,
                "analysis": q.analysis,
            } if q else None,
        })

    return {
        "items": wrong_list,
        "total": total,
        "page": page,
        "page_size": page_size,
    }

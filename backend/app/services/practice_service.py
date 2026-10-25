import logging
import random
from datetime import date, datetime, timedelta

from fastapi.encoders import jsonable_encoder
from sqlalchemy import Date as SQLDate
from sqlalchemy import and_, case, cast, delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings  # noqa: F401 — historical public import
from app.core.subject_scope import (
    EXAM408_DISPLAY_ORDER,
    canonical_408_code,
    is_study_subject_enabled,
    select_study_subject_records,
    selected_study_subject_ids,
    study_subject_display_name,
)
from app.core.time_utils import (
    shanghai_date_utc_range,
    shanghai_today,
    utcnow,
)
from app.features.question_type import (
    QT_MULTI_BLANK_CHOICE,
    QT_MULTI_BLANK_MULTIPLE_CHOICE,
    QT_MULTIPLE_CHOICE,
    QT_SINGLE_CHOICE,
    QT_TRUE_FALSE,
)
from app.models.admin import QuestionVersion, QuestionVersionKnowledgePoint
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.practice_session import PracticeSession
from app.models.question import Question
from app.models.question_import import (
    QuestionImport,  # noqa: F401 — ensures Subject mapper resolves
)
from app.models.sequential_reservation import SequentialReservation
from app.models.syllabus import SyllabusKnowledgePoint
from app.services.knowledge_point_service import (
    kp_any_condition,
    kp_exact_conditions,
    kp_id_any_condition,
    load_question_kps,
)
from app.services.practice.aggregated_random import (
    AggregatedRandomRequest,
    run_aggregated_random,
)
from app.services.practice.aggregated_smart import run_aggregated_smart
from app.services.practice.answer_projection_contract import (
    ANSWER_PROJECTION_TASK_SCHEMA_VERSION,
)
from app.services.practice.batch_token import (
    PRACTICE_ANSWER_DURATION_TOLERANCE_SEC,
    PRACTICE_BATCH_CLOCK_SKEW_SEC,  # noqa: F401 — historical public import
    PRACTICE_BATCH_MAX_QUESTIONS,
    PracticeBatchTokenError,
    _PRACTICE_BATCH_TOKEN_VERSION,  # noqa: F401 — historical public import
    _decode_practice_batch_token,  # noqa: F401 — historical public import
    _validate_practice_batch_token,
    create_practice_batch_token,  # noqa: F401 — historical public import
)
from app.services.practice.chapter_scope import (
    bucket_targets as _chapter_bucket_targets,
)
from app.services.practice.chapter_scope import (
    knowledge_bucket as _chapter_knowledge_bucket,
)
from app.services.practice.merge_utils import (
    build_fallback_metadata as _build_fallback_metadata,
)
from app.services.practice.merge_utils import (
    extract_graph_context as _extract_graph_context,
)
from app.services.practice.merge_utils import (
    practice_submission_fingerprint as _practice_submission_fingerprint,
)
from app.services.practice.merge_utils import (
    round_robin_merge as _round_robin_merge,
)
from app.services.practice.merge_utils import (
    round_robin_merge_with_metadata as _round_robin_merge_with_metadata,
)
from app.services.practice.normalization import (
    PRACTICE_ANSWER_MAX_USED_TIME_SEC as PRACTICE_ANSWER_MAX_USED_TIME_SEC,  # noqa: F401 — re-exported for tests
)
from app.services.practice.normalization import (
    PRACTICE_SESSION_MAX_DURATION_SEC as PRACTICE_SESSION_MAX_DURATION_SEC,  # noqa: F401 — re-exported for tests
)
from app.services.practice.normalization import (
    detect_408_subject_mismatch as _detect_408_subject_mismatch,
)
from app.services.practice.normalization import (
    normalize_answer_used_time as _normalize_answer_used_time,
)
from app.services.practice.normalization import (
    normalize_practice_request_id as _normalize_practice_request_id,
)
from app.services.practice.normalization import (
    normalize_practice_session as _normalize_practice_session,
)
from app.services.practice.normalization import (
    question_stem_for_subject_guard as _question_stem_for_subject_guard,
)
from app.services.practice.recommendation_pipeline import (
    merge_recommendation_results,
    normalize_smart_strategy,
)
from app.services.practice.revision_scope_guard import (
    filter_questions_to_revision_scope as _filter_questions_to_revision_scope,
)
from app.services.practice.scored_fallback import (
    load_random_fill_questions,
    load_repeat_fill_questions,
)
from app.services.practice.scored_fallback_flow import (
    ScoredFallbackRequest,
    run_scored_fallback,
)
from app.services.practice.scored_fallback_merge import merge_fill_questions
from app.services.practice.scored_ranking import score_and_rank_candidates
from app.services.practice.scored_selection import select_scored_candidates
from app.services.practice.sequential_service import (
    SEQUENTIAL_MODE,
    get_sequential_practice_questions,
    reset_sequential_progress,  # noqa: F401 — re-exported for the practice API
)
from app.services.practice.strategy_weight_rerank import apply_strategy_weight_rerank
from app.services.practice.smart_scored_supplement import (
    ScoredSupplementRequest,
    run_scored_supplement,
)
from app.services.practice.smart_orchestrator import (
    SmartPracticeRequest,
    run_smart_practice,
)
from app.services.practice.stats import (
    accuracy as _practice_accuracy,
    load_daily_breakdown,
    load_practice_totals,
    load_subject_breakdown,
)
from app.services.practice.batch_wrong_book import (
    enqueue_wrong_answer_prewarm,
    persist_wrong_answer,
)
from app.services.practice.smart_weakness_vector import (
    SmartWeaknessVectorRequest,
    run_smart_weakness_vector,
)
from app.services.practice.smart_path_supplement import (
    SmartPathRequest,
    run_smart_path,
)
from app.services.practice.time_window import excluded_question_subquery
from app.services.practice.v1_fallback import (
    V1FallbackRequest,
    run_v1_fallback,
)
from app.services.practice.smart_scoring import (
    _build_smart_recommendation_reason,
    _pick_graph_target_kps,
    calculate_smart_score,
)
from app.services.question_revision_service import (
    latest_question_revision_scope_condition,
    load_latest_question_revision_ids,
)
from app.services.subject_resolution import resolve_subject_ids
from app.utils.answer_normalizer import (
    extract_multi_blank_slot_ids,
    is_answer_correct,
)

logger = logging.getLogger(__name__)


class PracticeSubmissionConflictError(ValueError):
    """The idempotency key belongs to a different semantic submission."""


# The current mini-program runner only provides interactive controls for these
# question types.  Text/free-response revisions must not be issued into a batch
# until the runner has an input path for them, otherwise the user can never mark
# the question answered and is forced to submit it as skipped.
PRACTICE_ANSWERABLE_QUESTION_TYPES = frozenset(
    {
        QT_SINGLE_CHOICE,
        QT_MULTIPLE_CHOICE,
        QT_TRUE_FALSE,
        QT_MULTI_BLANK_CHOICE,
        QT_MULTI_BLANK_MULTIPLE_CHOICE,
    }
)


async def _china_date_expr(db: AsyncSession, column):
    bind = await db.connection()
    if bind.sync_connection.dialect.name == "sqlite":
        return func.date(column, "+8 hours")
    return cast(column + text("INTERVAL '8 hours'"), SQLDate)


async def _start_explicit_transaction(db: AsyncSession) -> None:
    """Start an outer transaction before creating SQLite savepoints.

    SQLite's implicit transaction starts only at the first write. Releasing a
    savepoint created in that state can persist the write even if the caller
    later rolls back. PostgreSQL does not have this edge case; an explicit
    BEGIN keeps the nested claim semantics equivalent on both dialects.
    """
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "sqlite":
        await db.execute(text("BEGIN"))


def _is_unique_violation(err: IntegrityError) -> bool:
    """Return True only for the expected request-id unique collision."""
    orig = getattr(err, "orig", None)
    if orig is None:
        return False
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if code == "23505":  # PostgreSQL unique_violation (asyncpg/psycopg)
        return True
    message = str(orig)
    return "UNIQUE constraint failed" in message or "duplicate key" in message


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
        return query.order_by(func.random()).limit(need)
    if total_count <= 2000:
        # Typical per-subject practice pools are small enough for a real random
        # order.  The previous ``need <= 20`` branch selected one contiguous ID
        # window for almost every 5/10/20-question session, so imported batches
        # and neighboring knowledge points appeared together and random mode was
        # visibly biased.
        return query.order_by(func.random()).limit(need)

    # Large pool: avoid a full random sort.  A random offset is best-effort but
    # keeps the database work bounded.
    offset = random.randint(0, total_count - need)
    return (
        query.order_by(id_col.asc() if id_col else func.random())
        .offset(offset)
        .limit(need)
    )


async def get_practice_subject_tree(db: AsyncSession) -> list[dict]:
    """返回当前产品可练习的 408 科目树。

    ``subjects.id`` 是唯一业务 ID；运行时仅接受规范化后的 canonical code。
    若 408 根科目缺失、重复或被停用，公共入口直接关闭，不再按名称/旧编码
    进行兼容回退。

    科目树变化只来自 Admin 科目写接口，因此这里使用 24h 共享缓存；
    Admin 写路径会调用 ``invalidate_subject_tree_cache()`` 立即失效。
    """
    from app.models.admin import Subject
    from app.services.subject_tree_cache import (
        get_cached_subject_tree,
        set_cached_subject_tree,
    )

    cached = await get_cached_subject_tree()
    if cached is not None:
        return cached

    result = await db.execute(
        select(Subject).order_by(
            Subject.level.asc(), Subject.sort_order.asc(), Subject.id.asc()
        )
    )
    all_subjects = list(result.scalars().all())
    subjects = select_study_subject_records(all_subjects)

    def _to_node(s: Subject) -> dict:
        product_code = canonical_408_code(s.code) or str(s.code or "").strip().lower()
        display_name = study_subject_display_name(s.name)
        return {
            "subject_id": s.id,
            "subject_code": s.code,
            "subject_name": display_name,
            "display_name": display_name,
            "product_code": product_code,
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

    def _node_sort_key(node: dict) -> tuple[int, int, int]:
        return (
            EXAM408_DISPLAY_ORDER.get(node.get("product_code") or "", 999),
            int(node.get("sort_order") or 0),
            int(node.get("subject_id") or 0),
        )

    def _sort_tree(items: list[dict]) -> None:
        items.sort(key=_node_sort_key)
        for item in items:
            _sort_tree(item["children"])

    _sort_tree(roots)
    await set_cached_subject_tree(roots)
    return roots


async def resolve_subject_id_to_code(
    db: AsyncSession, subject_id: int
) -> tuple[str, str] | None:
    """将可练习的 408 subject_id 解析为 (subject_code, subject_name)。"""
    from app.models.admin import Subject

    all_result = await db.execute(select(Subject))
    all_subjects = list(all_result.scalars().all())
    allowed_ids = selected_study_subject_ids(all_subjects)
    if subject_id not in allowed_ids:
        return None
    subj = next((item for item in all_subjects if item.id == subject_id), None)
    if subj is None or not is_study_subject_enabled(subj):
        return None
    return (subj.code, subj.name)


def _practice_revision_scope_condition(subject_ids: list[int]):
    """Require the mutable question and its newest immutable revision to agree.

    Practice responses are serialized from ``QuestionVersion`` while candidate
    queries run against ``Question``.  If those two rows temporarily disagree
    (for example after a partial repair/import), filtering only
    ``Question.subject_id`` can select a data-structure row whose issued revision
    still belongs to another 408 discipline.  Bind every practice candidate to
    a current revision in the same requested scope so such rows are never issued.
    """
    return latest_question_revision_scope_condition(
        subject_ids,
        PRACTICE_ANSWERABLE_QUESTION_TYPES,
    )


async def filter_questions_to_revision_scope(
    db: AsyncSession,
    questions: list[Question],
    subject_ids: list[int],
    revision_ids: dict[int, int] | None = None,
) -> list[Question]:
    """Final defense-in-depth check before a practice batch is signed.

    Smart/similar strategies can receive candidates from vector services, so not
    every path is built by the ordinary SQL query helpers.  Validate the exact
    immutable revision that will be sent to the client and drop any candidate
    whose mutable row, current revision or requested subject scope disagree.
    """
    return await _filter_questions_to_revision_scope(
        db,
        questions,
        subject_ids,
        revision_ids,
        load_revision_ids=load_latest_question_revision_ids,
        answerable_types=PRACTICE_ANSWERABLE_QUESTION_TYPES,
    )


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
    return excluded_question_subquery(
        user_id=user_id,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
        utcnow=utcnow,
    )


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
    if subj is None or not is_study_subject_enabled(subj):
        return False, []

    # 获取当前学生端可用科目以构建树。额外开放的四个科目即使曾被旧迁移
    # 标记为 inactive，也应在学生端继续可练习。
    all_result = await db.execute(
        select(Subject).order_by(
            Subject.level.asc(), Subject.sort_order.asc(), Subject.id.asc()
        )
    )
    all_subjects = select_study_subject_records(all_result.scalars().all())

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
            if is_study_subject_enabled(child):
                stack.append(child)

    # 按 sort_order, id 排序
    result.sort(key=lambda s: (s.sort_order, s.id))
    return has_enabled_children, [s.id for s in result]


async def resolve_practice_knowledge_scope(
    db: AsyncSession,
    *,
    knowledge_point_id: int,
    subject_ids: list[int],
    include_descendants: bool = False,
) -> dict | None:
    """Resolve a practice knowledge scope against the active syllabus hierarchy.

    ``knowledge_point_id`` is canonical and must be active, belong to the requested
    subject scope, and be present in the active syllabus.  When descendants are
    requested, only active-syllabus nodes reachable through active ``parent`` edges
    are returned.  The root itself is always included so parent nodes that own
    questions directly remain trainable.
    """
    from collections import defaultdict, deque

    from app.models.knowledge_edge import KnowledgeEdge
    from app.services import syllabus_service

    normalized_subject_ids = list(
        dict.fromkeys(int(value) for value in subject_ids if int(value) > 0)
    )
    if not normalized_subject_ids:
        return None

    point = (
        await db.execute(
            select(KnowledgePoint).where(
                KnowledgePoint.id == int(knowledge_point_id),
                KnowledgePoint.subject_id.in_(normalized_subject_ids),
                KnowledgePoint.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if point is None:
        return None

    syllabus_version, memberships = await syllabus_service.active_memberships(
        db, [int(point.subject_id)]
    )
    if syllabus_version is None or int(point.id) not in memberships:
        return None

    if not include_descendants:
        return {
            "root_id": int(point.id),
            "root_name": str(point.name),
            "subject_id": int(point.subject_id),
            "syllabus_version_id": int(syllabus_version.id),
            "knowledge_point_ids": [int(point.id)],
            "include_descendants": False,
        }

    allowed_ids = set(int(kp_id) for kp_id in memberships)
    active_rows = await db.execute(
        select(KnowledgePoint.id).where(
            KnowledgePoint.subject_id == int(point.subject_id),
            KnowledgePoint.id.in_(allowed_ids),
            KnowledgePoint.is_active.is_(True),
        )
    )
    active_ids = {int(value) for value in active_rows.scalars().all()}
    if int(point.id) not in active_ids:
        return None

    edge_rows = await db.execute(
        select(
            KnowledgeEdge.source_knowledge_point_id,
            KnowledgeEdge.target_knowledge_point_id,
        ).where(
            KnowledgeEdge.subject_id == int(point.subject_id),
            KnowledgeEdge.relation_type == "parent",
            KnowledgeEdge.is_active.is_(True),
            KnowledgeEdge.source_knowledge_point_id.in_(active_ids),
            KnowledgeEdge.target_knowledge_point_id.in_(active_ids),
        )
    )
    children: dict[int, list[int]] = defaultdict(list)
    for parent_id, child_id in edge_rows.all():
        children[int(parent_id)].append(int(child_id))

    # Preserve syllabus order in each level so diagnostics and future client
    # surfaces receive a stable scope even though the SQL edge table has no order.
    def sort_key(kp_id: int) -> tuple[int, int]:
        return (
            int(memberships[kp_id].sort_order or 0) if kp_id in memberships else 0,
            kp_id,
        )

    for child_ids in children.values():
        child_ids.sort(key=sort_key)

    ordered_ids: list[int] = []
    queue = deque([int(point.id)])
    seen: set[int] = set()
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        ordered_ids.append(current)
        queue.extend(children.get(current, ()))

    return {
        "root_id": int(point.id),
        "root_name": str(point.name),
        "subject_id": int(point.subject_id),
        "syllabus_version_id": int(syllabus_version.id),
        "knowledge_point_ids": ordered_ids,
        "include_descendants": True,
    }


async def get_knowledge_scope_practice_questions(
    db: AsyncSession,
    *,
    user_id: int,
    subject_code: str,
    subject_ids: list[int],
    knowledge_point_ids: list[int],
    count: int,
    exclude_answered: bool = False,
    no_repeat_days: int | None = None,
    use_leitner: bool = True,
) -> list[Question]:
    """Build a chapter batch biased toward weak and not-yet-established nodes.

    Candidate eligibility still uses the normal practice/Leitner pipeline.  The
    chapter layer only re-ranks an over-fetched, already-valid candidate pool so
    it cannot bypass review windows, immutable revision guards, or subject scope.
    A question linked to several target KPs is assigned to its highest-priority
    bucket and is returned at most once.
    """
    from collections import defaultdict

    from app.models.question_knowledge_point import QuestionKnowledgePoint
    from app.models.user_knowledge_state import UserKnowledgeState

    target_ids = list(
        dict.fromkeys(int(value) for value in knowledge_point_ids if int(value) > 0)
    )
    if not target_ids or count <= 0:
        return []

    candidate_count = min(100, max(int(count) * 5, 50))
    candidates = await get_practice_questions(
        db=db,
        user_id=user_id,
        subject_code=subject_code,
        count=candidate_count,
        mode="random",
        knowledge_point_ids=target_ids,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
        use_leitner=use_leitner,
        subject_ids=subject_ids,
    )
    if len(candidates) <= count:
        return candidates

    candidate_ids = [int(question.id) for question in candidates]
    state_rows = await db.execute(
        select(UserKnowledgeState).where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.knowledge_point_id.in_(target_ids),
        )
    )
    states = {
        int(state.knowledge_point_id): state for state in state_rows.scalars().all()
    }

    mapping_rows = await db.execute(
        select(
            QuestionKnowledgePoint.question_id,
            QuestionKnowledgePoint.knowledge_point_id,
        ).where(
            QuestionKnowledgePoint.question_id.in_(candidate_ids),
            QuestionKnowledgePoint.knowledge_point_id.in_(target_ids),
        )
    )
    q_to_kps: dict[int, list[int]] = defaultdict(list)
    for question_id, kp_id in mapping_rows.all():
        q_to_kps[int(question_id)].append(int(kp_id))

    bucket_rank = {"weak": 0, "unobserved": 1, "developing": 2, "stable": 3}
    buckets: dict[str, list[Question]] = {name: [] for name in bucket_rank}
    for question in candidates:
        kp_ids = q_to_kps.get(int(question.id), [])
        labels = [_chapter_knowledge_bucket(states.get(kp_id)) for kp_id in kp_ids]
        bucket = (
            min(labels, key=lambda name: bucket_rank[name]) if labels else "unobserved"
        )
        buckets[bucket].append(question)

    # Preserve the candidate order produced by the Leitner/fallback pipeline.
    # Its SQL sampling already supplies randomness where appropriate; reshuffling
    # here would incorrectly let relaxed-repeat candidates jump ahead of fresh/due ones.
    targets = _chapter_bucket_targets(count)
    selected: list[Question] = []
    selected_ids: set[int] = set()
    for bucket in ("weak", "unobserved", "developing", "stable"):
        for question in buckets[bucket][: targets[bucket]]:
            if int(question.id) in selected_ids:
                continue
            selected.append(question)
            selected_ids.add(int(question.id))

    # Sparse buckets are common for new users. Fill the remaining capacity in
    # priority order instead of returning a short batch.
    if len(selected) < count:
        for bucket in ("weak", "unobserved", "developing", "stable"):
            for question in buckets[bucket]:
                if int(question.id) in selected_ids:
                    continue
                selected.append(question)
                selected_ids.add(int(question.id))
                if len(selected) >= count:
                    break
            if len(selected) >= count:
                break

    logger.info(
        "[KNOWLEDGE_SCOPE_PRACTICE] root_scope_size=%d requested=%d candidates=%d "
        "bucket_sizes=%s target_mix=%s returned=%d",
        len(target_ids),
        count,
        len(candidates),
        {name: len(values) for name, values in buckets.items()},
        targets,
        len(selected[:count]),
    )
    return selected[:count]


async def get_aggregated_random_questions(
    db: AsyncSession,
    user_id: int,
    subject_code: str,
    subject_ids: list[int],
    count: int = 20,
    knowledge_points: list[str] | None = None,
    knowledge_point_ids: list[int] | None = None,
    exclude_answered: bool = False,
    no_repeat_days: int | None = None,
    use_leitner: bool = True,
) -> list[Question]:
    """random 模式聚合刷题：每个精确 subject_id 独立生成候选后轮询均衡分配。

    对每个启用子科目独立查询（limit=count），保证每科都有候选进入轮询池，
    不存在因全局 LIMIT 导致子科目被完全排除的风险。每科最多返回 count 道题，
    再通过 round-robin 确保最终分布均衡。
    """

    async def load_bucket(db, sid, bucket_count):
        conds = [
            Question.is_active,
            Question.subject_id == sid,
            _practice_revision_scope_condition([sid]),
        ]
        if knowledge_points:
            conds.extend(kp_exact_conditions(knowledge_points))
        if knowledge_point_ids:
            kp_id_condition = kp_id_any_condition(knowledge_point_ids)
            if kp_id_condition is not None:
                conds.append(kp_id_condition)

        if use_leitner:
            return await _get_questions_with_leitner(
                db,
                user_id,
                conds,
                "random",
                bucket_count,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
            )
        return await _get_questions_v1_fallback(
            db,
            conds,
            "random",
            bucket_count,
            user_id=user_id,
            exclude_answered=exclude_answered,
            no_repeat_days=no_repeat_days,
        )

    return await run_aggregated_random(
        AggregatedRandomRequest(
            db=db,
            subject_code=subject_code,
            subject_ids=subject_ids,
            count=count,
            logger=logger,
            load_bucket=load_bucket,
            merge=_round_robin_merge,
        )
    )


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

    async def load_subjects(ids: list[int]) -> list[Subject]:
        result = await db.execute(select(Subject).where(Subject.id.in_(ids)))
        return list(result.scalars().all())

    return await run_aggregated_smart(
        db=db,
        user_id=user_id,
        subject_code=subject_code,
        subject_ids=subject_ids,
        count=count,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
        use_leitner=use_leitner,
        request_id=request_id,
        smart_strategy=smart_strategy,
        logger=logger,
        load_subjects=load_subjects,
        load_smart=get_smart_practice_questions,
        merge_metadata=_round_robin_merge_with_metadata,
        finalize=_finalize_smart,
    )


async def get_targeted_practice_questions(
    db: AsyncSession,
    *,
    question_ids: list[int],
    subject_ids: list[int],
) -> list[Question]:
    """按调用方给定顺序加载一组严格受科目/当前版本约束的题目。

    该入口用于 Study Hub 的“个人难题重练”等定向任务。它不建立新的
    practice mode：最终仍由普通 batch token 签发与 batch-submit 判题。
    任一 ID 不存在、停用、越出请求科目范围、版本不一致或题型不可作答时，
    调用方都应拒绝整批，而不是静默替换成其他题。
    """
    ordered_ids = [int(qid) for qid in question_ids if int(qid) > 0]
    if not ordered_ids or not subject_ids:
        return []

    rows = await db.execute(
        select(Question)
        .where(
            Question.id.in_(ordered_ids),
            Question.subject_id.in_(subject_ids),
            Question.is_active.is_(True),
            _practice_revision_scope_condition(subject_ids),
        )
        .options(selectinload(Question.subject_ref))
    )
    by_id = {int(question.id): question for question in rows.scalars().all()}
    return [by_id[qid] for qid in ordered_ids if qid in by_id]


async def get_practice_questions(
    db: AsyncSession,
    user_id: int,
    subject_code: str,
    count: int = 20,
    mode: str = "random",
    knowledge_points: list[str] | None = None,
    knowledge_point_ids: list[int] | None = None,
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
    base_conditions = [
        Question.is_active,
        subject_cond,
        _practice_revision_scope_condition(ids),
    ]

    if knowledge_points:
        base_conditions.extend(kp_exact_conditions(knowledge_points))
    if knowledge_point_ids:
        kp_id_condition = kp_id_any_condition(knowledge_point_ids)
        if kp_id_condition is not None:
            base_conditions.append(kp_id_condition)

    # ── 顺序模式：严格题库进度，不参与 Leitner / no-repeat 调度 ──
    if mode == SEQUENTIAL_MODE:
        if len(ids) != 1:
            raise ValueError("顺序练习仅支持单一具体科目")
        questions, _progress = await get_sequential_practice_questions(
            db,
            user_id=user_id,
            subject_id=ids[0],
            subject_ids=ids,
            count=count,
            knowledge_points=knowledge_points,
        )
        return questions

    # ── V2 Leitner 模式 ──
    if use_leitner:
        return await _get_questions_with_leitner(
            db,
            user_id,
            base_conditions,
            mode,
            count,
            exclude_answered=exclude_answered,
            no_repeat_days=no_repeat_days,
        )

    # ── V1 兼容模式：use_leitner=False ──
    return await _get_questions_v1_fallback(
        db,
        base_conditions,
        mode,
        count,
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
    # ``use_leitner`` only controls *which* questions are due; it must not
    # silently disable the caller's repeat-window contract.  The practice page
    # currently requests ``exclude_answered=true&no_repeat_days=30``.  Before
    # this guard the first three Leitner layers ignored both arguments, so a
    # question answered minutes ago could be selected again simply because its
    # UserQuestionState was due (or had a NULL next_review_at).
    excluded_sub = _build_excluded_question_subquery(
        user_id=user_id,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
    )

    async def _leitner_query(
        due_condition,
        exclude_ids: set[int] | None = None,
        limit: int | None = None,
        extra_order=None,
    ) -> list[Question]:
        """Leitner 内部查询：outer join UserQuestionState + 到期条件。"""
        conds = list(base_conditions)
        if excluded_sub is not None:
            conds.append(Question.id.notin_(excluded_sub))
        if exclude_ids:
            conds.append(Question.id.notin_(exclude_ids))

        base_q = (
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
        limit_value = limit if limit is not None else count
        if extra_order is not None:
            q = base_q.order_by(extra_order).limit(limit_value)
        elif mode == "random":
            # Default practice uses Leitner, so random-mode performance must be
            # bounded here as well (not only in the V1 fallback).  Keep true
            # random ordering for ordinary per-subject pools and switch to the
            # bounded random-offset strategy for unusually large pools.
            count_base = (
                select(Question.id)
                .outerjoin(
                    UserQuestionState,
                    and_(
                        UserQuestionState.question_id == Question.id,
                        UserQuestionState.user_id == user_id,
                    ),
                )
                .where(and_(*conds, due_condition))
                .subquery()
            )
            total = int(
                (await db.scalar(select(func.count()).select_from(count_base))) or 0
            )
            q = _random_sample_query(base_q, total, limit_value, Question.id)
        else:
            q = base_q.order_by(Question.id.asc()).limit(limit_value)
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
            mode,
            count,
            len(questions),
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
    more = await _leitner_query(
        due_soon_cond, exclude_ids=existing_ids, limit=count - len(questions)
    )
    questions.extend(more)
    existing_ids.update(q.id for q in more)

    if len(questions) >= count:
        logger.info(
            "[Leitner Query] mode=%s count=%d resultCount=%d (layer: due+1d)",
            mode,
            count,
            len(questions),
        )
        return questions[:count]

    # 第三层：最久未做的题（last_answered_at ASC NULLS FIRST）
    all_cond = or_(
        UserQuestionState.id.is_(None),
        UserQuestionState.next_review_at.is_(None),
        UserQuestionState.next_review_at <= soon + timedelta(days=30),
    )
    more = await _leitner_query(
        all_cond,
        exclude_ids=existing_ids,
        limit=count - len(questions),
        extra_order=UserQuestionState.last_answered_at.asc().nulls_first(),
    )
    questions.extend(more)
    existing_ids.update(q.id for q in more)

    if len(questions) >= count:
        logger.info(
            "[Leitner Query] mode=%s count=%d resultCount=%d (layer: oldest)",
            mode,
            count,
            len(questions),
        )
        return questions[:count]

    # 第四层：回退到 V1 no_repeat_days fallback
    v1_results = await _get_questions_v1_fallback(
        db,
        base_conditions,
        mode,
        count - len(questions),
        user_id=user_id,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
        exclude_ids=existing_ids,
    )
    questions.extend(v1_results)

    logger.info(
        "[Leitner Query] mode=%s count=%d resultCount=%d (layer: v1-fallback)",
        mode,
        count,
        len(questions),
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
    return await run_v1_fallback(
        V1FallbackRequest(
            db=db,
            base_conditions=base_conditions,
            mode=mode,
            count=count,
            user_id=user_id,
            exclude_answered=exclude_answered,
            no_repeat_days=no_repeat_days,
            exclude_ids=exclude_ids,
            utcnow=utcnow,
            random_sample=_random_sample_query,
            execute=db.execute,
        )
    )


async def get_similar_practice_questions(
    db: AsyncSession,
    user_id: int,
    subject_code: str,
    source_question_id: int,
    count: int = 20,
    exclude_answered: bool = False,
    no_repeat_days: int | None = None,
    use_leitner: bool = True,
    subject_ids: list[int] | None = None,
) -> tuple[list[Question], dict[int, dict]]:
    """similar 模式：基于源题的向量相似题召回，不足时用规则 + 随机补齐。

    返回: (questions_list, metadata_dict)
        metadata_dict: {question_id: {"recommend_reason": ..., "recommend_score": ..., "strategy": ..., "similarity": ...}}
    """
    # use_leitner 由 issuance 层统一执行：candidate_schedule.filter_due_candidates
    # 在向量召回后用 question_review_service.get_due_question_ids() 二次过滤
    # next_review_at > now 的题目，不足时用 random fallback 补齐（见
    # question_issuance.issue_practice_questions）。本函数只负责候选召回。
    metadata: dict[int, dict] = {}
    scope_ids = (
        subject_ids
        if subject_ids is not None
        else await resolve_subject_ids(db, subject_code)
    )

    # 1. 向量召回
    vector_questions: list[Question] = []
    vector_excluded_sub = _build_excluded_question_subquery(
        user_id=user_id,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
    )
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
                vector_conditions = [
                    Question.id.in_(rec_ids),
                    # A similarity session must never hand the seed question
                    # straight back to the user, even if the vector provider
                    # includes self-similarity in its top-k response.
                    Question.id != source_question_id,
                    Question.is_active,
                    Question.subject_id.in_(scope_ids),
                    _practice_revision_scope_condition(scope_ids),
                ]
                # Enforce repeat-window semantics at the authoritative DB read,
                # rather than trusting a vector service/cache to have applied
                # the latest PracticeRecord state perfectly.
                if vector_excluded_sub is not None:
                    vector_conditions.append(Question.id.notin_(vector_excluded_sub))
                q_result = await db.execute(
                    select(Question)
                    .where(and_(*vector_conditions))
                    .options(selectinload(Question.subject_ref))
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

    subject_cond = Question.subject_id.in_(scope_ids)
    conditions = [
        Question.is_active,
        subject_cond,
        _practice_revision_scope_condition(scope_ids),
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
    q = (
        select(Question)
        .where(and_(*conditions))
        .options(selectinload(Question.subject_ref))
    )
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
        questions,
        metadata,
        db,
        user_id,
        subject_code,
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
    """Compatibility wrapper around the extracted strategy-weight reranker."""
    return await apply_strategy_weight_rerank(
        db, user_id, questions, metadata, config, weak_kp_names
    )


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
    # use_leitner 由 issuance 层统一执行；本函数只负责候选召回与策略编排。
    from app.services import recommendation_experiment_service

    scope_ids = (
        subject_ids
        if subject_ids is not None
        else await resolve_subject_ids(db, subject_code)
    )

    async def run_scored_branch(
        experiment_info: dict,
        _strategy: str,
        branch_scope_ids: list[int],
    ) -> tuple[list[Question], dict[int, dict]] | None:
        return await run_scored_supplement(
            ScoredSupplementRequest(
                db=db,
                user_id=user_id,
                subject_code=subject_code,
                count=count,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
                use_leitner=use_leitner,
                request_id=request_id,
                scope_ids=branch_scope_ids,
                skip_finalize=skip_finalize,
                experiment_id=experiment_info.get("experiment_id"),
                variant_key=experiment_info.get("variant_key"),
                logger=logger,
                load_scored=get_smart_scored_questions,
                load_fallback=_smart_weakness_vector,
                merge_results=merge_recommendation_results,
                finalize=_maybe_finalize_smart,
            )
        )

    async def run_path_branch(
        experiment_info: dict,
        _strategy: str,
        branch_scope_ids: list[int],
    ) -> tuple[list[Question], dict[int, dict]] | None:
        from app.services import knowledge_path_service

        def build_path_conditions(
            *,
            candidate_ids: list[int],
            scope_ids: list[int],
            user_id: int,
            exclude_answered: bool,
            no_repeat_days: int | None,
        ) -> list:
            conditions = [
                Question.id.in_(candidate_ids),
                Question.is_active,
                Question.subject_id.in_(scope_ids),
                _practice_revision_scope_condition(scope_ids),
            ]
            excluded_sub = _build_excluded_question_subquery(
                user_id=user_id,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
            )
            if excluded_sub is not None:
                conditions.append(Question.id.notin_(excluded_sub))
            return conditions

        return await run_smart_path(
            SmartPathRequest(
                db=db,
                user_id=user_id,
                subject_code=subject_code,
                count=count,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
                use_leitner=use_leitner,
                scope_ids=branch_scope_ids,
                skip_finalize=skip_finalize,
                experiment_id=experiment_info.get("experiment_id"),
                variant_key=experiment_info.get("variant_key"),
                request_id=request_id,
                logger=logger,
                load_path=knowledge_path_service.get_user_path_recommendations,
                load_fallback=_smart_weakness_vector,
                merge_results=merge_recommendation_results,
                finalize=_maybe_finalize_smart,
                build_conditions=build_path_conditions,
            )
        )

    async def run_weakness_branch(**kwargs) -> tuple[list[Question], dict[int, dict]]:
        return await _legacy_weakness_vector(**kwargs)

    return await run_smart_practice(
        SmartPracticeRequest(
            db=db,
            user_id=user_id,
            subject_code=subject_code,
            count=count,
            exclude_answered=exclude_answered,
            no_repeat_days=no_repeat_days,
            use_leitner=use_leitner,
            request_id=request_id,
            smart_strategy=smart_strategy,
            skip_finalize=skip_finalize,
            subject_ids=scope_ids,
            logger=logger,
            resolve_experiment=(
                recommendation_experiment_service.resolve_strategy_for_user
            ),
            resolve_scope_ids=resolve_subject_ids,
            run_scored=run_scored_branch,
            run_path=run_path_branch,
            run_weakness=run_weakness_branch,
        )
    )


async def _legacy_weakness_vector(
    db: AsyncSession,
    user_id: int,
    subject_code: str,
    *,
    count: int = 20,
    exclude_answered: bool = False,
    no_repeat_days: int | None = None,
    use_leitner: bool = True,
    subject_ids: list[int] | None = None,
    skip_finalize: bool = False,
    request_id: str | None = None,
    experiment_id: int | None = None,
    variant_key: str | None = None,
) -> tuple[list[Question], dict[int, dict]]:
    """Legacy weakness-vector branch retained for direct smart-entry fallback."""

    metadata: dict[int, dict] = {}
    # 1. 获取薄弱知识点（Phase 2 优先使用掌握度画像）
    weak_kps: list[dict] = []
    try:
        from app.services import mastery_service

        weak_kps = await mastery_service.get_user_weak_knowledge_points(
            db,
            user_id,
            subject_code,
            limit=5,
        )
        if weak_kps:
            pass
    except Exception:
        logger.warning(
            "mastery_service.get_user_weak_knowledge_points failed, fallback",
            exc_info=True,
        )

    if not weak_kps:
        # Fallback: Phase 1 的临时统计
        weak_kps = await _compute_weak_knowledge_points(
            db,
            user_id,
            subject_ids or [],
        )
        if weak_kps:
            pass

    if not weak_kps:
        # 没有足够的做题记录来判断薄弱点，退化为随机
        logger.info("smart 模式: 无足够做题记录，退化为随机")
        questions = await get_practice_questions(
            db=db,
            user_id=user_id,
            subject_code=subject_code,
            count=count,
            mode="random",
            exclude_answered=exclude_answered,
            no_repeat_days=no_repeat_days,
            use_leitner=use_leitner,
            subject_ids=subject_ids,
        )
        for q in questions:
            metadata[q.id] = {
                "recommend_reason": "随机推荐（无足够做题记录）",
                "recommend_score": None,
                "strategy": "random_fallback",
                "similarity": None,
            }
        return await _maybe_finalize_smart(
            questions,
            metadata,
            skip_finalize,
            db,
            user_id,
            subject_code,
            request_id=request_id,
            experiment_id=experiment_id,
            variant_key=variant_key,
        )

    # 2. 构造 query_text 并向量召回
    kp_names = [kp["name"] for kp in weak_kps[:5]]
    query_text = (
        f"科目：{subject_code}。请推荐这些薄弱知识点的练习题："
        f"{'、'.join(kp_names)}。要求题目适合查漏补缺和变式训练。"
    )

    vector_questions: list[Question] = []
    vector_excluded_sub = _build_excluded_question_subquery(
        user_id=user_id,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
    )
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
            vector_conditions = [
                Question.id.in_(rec_ids),
                Question.is_active,
                Question.subject_id.in_(subject_ids or []),
                _practice_revision_scope_condition(subject_ids or []),
            ]
            if vector_excluded_sub is not None:
                vector_conditions.append(Question.id.notin_(vector_excluded_sub))
            q_result = await db.execute(
                select(Question)
                .where(and_(*vector_conditions))
                .options(selectinload(Question.subject_ref))
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
            db,
            "practice_smart",
            strategy_name="default_weakness_vector",
        )
    except Exception:
        logger.debug("获取推荐策略配置失败，跳过权重重排", exc_info=True)

    if strategy_config:
        vector_questions, metadata = await _apply_strategy_weight_rerank(
            db,
            user_id,
            vector_questions,
            metadata,
            strategy_config,
            kp_names,
        )

    if len(vector_questions) >= count:
        return await _maybe_finalize_smart(
            vector_questions[:count],
            metadata,
            skip_finalize,
            db,
            user_id,
            subject_code,
            request_id=request_id,
            experiment_id=experiment_id,
            variant_key=variant_key,
        )

    # 3. 补齐：按薄弱知识点过滤 + 随机
    existing_ids = {q.id for q in vector_questions}
    subject_cond = Question.subject_id.in_(subject_ids or [])
    conditions = [
        Question.is_active,
        subject_cond,
        _practice_revision_scope_condition(subject_ids or []),
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
            kp_q = (
                select(Question)
                .where(and_(*conditions, kp_cond))
                .options(selectinload(Question.subject_ref))
            )
            kp_q = _random_sample_query(
                kp_q, kp_total, min(kp_remaining, kp_total), Question.id
            )
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
            select(Question)
            .where(and_(*conditions, Question.id.notin_(existing_ids)))
            .subquery()
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

    return await _maybe_finalize_smart(
        vector_questions[:count],
        metadata,
        skip_finalize,
        db,
        user_id,
        subject_code,
        request_id=request_id,
        experiment_id=experiment_id,
        variant_key=variant_key,
    )


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
            recs.append(
                {
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
                }
            )

        if recs:
            await recommendation_log_service.create_recommendation_logs_isolated(
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
    from app.services import mastery_service, vector_retrieval_service

    async def load_vector_matches(
        recalls: list[dict],
        scope_ids: list[int],
        exclude_ids: set[int],
    ) -> list[tuple[Question, dict]]:
        rec_ids = [
            recall["question_id"]
            for recall in recalls
            if recall["question_id"] not in exclude_ids
        ]
        if not rec_ids:
            return []
        vector_conditions = [
            Question.id.in_(rec_ids),
            Question.is_active,
            Question.subject_id.in_(scope_ids),
            _practice_revision_scope_condition(scope_ids),
        ]
        vector_excluded_sub = _build_excluded_question_subquery(
            user_id=user_id,
            exclude_answered=exclude_answered,
            no_repeat_days=no_repeat_days,
        )
        if vector_excluded_sub is not None:
            vector_conditions.append(Question.id.notin_(vector_excluded_sub))
        result = await db.execute(
            select(Question)
            .where(and_(*vector_conditions))
            .options(selectinload(Question.subject_ref))
        )
        by_id = {question.id: question for question in result.scalars().all()}
        return [
            (by_id[recall["question_id"]], recall)
            for recall in recalls
            if recall["question_id"] in by_id
            and recall["question_id"] not in exclude_ids
        ]

    async def load_fill_questions(
        remaining: int,
        scope_ids: list[int],
        existing_ids: set[int],
    ) -> list[Question]:
        conditions = [
            Question.is_active,
            Question.subject_id.in_(scope_ids),
            _practice_revision_scope_condition(scope_ids),
            Question.id.notin_(existing_ids),
        ]
        excluded_sub = _build_excluded_question_subquery(
            user_id=user_id,
            exclude_answered=exclude_answered,
            no_repeat_days=no_repeat_days,
        )
        if excluded_sub is not None:
            conditions.append(Question.id.notin_(excluded_sub))
        total = (
            await db.execute(
                select(func.count()).select_from(
                    select(Question).where(and_(*conditions)).subquery()
                )
            )
        ).scalar() or 0
        query = (
            select(Question)
            .where(and_(*conditions))
            .options(selectinload(Question.subject_ref))
        )
        query = _random_sample_query(query, total, remaining, Question.id)
        return list((await db.execute(query)).scalars().all())

    return await run_smart_weakness_vector(
        SmartWeaknessVectorRequest(
            db=db,
            user_id=user_id,
            subject_code=subject_code,
            count=count,
            exclude_answered=exclude_answered,
            no_repeat_days=no_repeat_days,
            use_leitner=use_leitner,
            exclude_ids=exclude_ids,
            subject_ids=subject_ids,
            logger=logger,
            resolve_scope_ids=resolve_subject_ids,
            load_mastery=mastery_service.get_user_weak_knowledge_points,
            compute_weak_kps=_compute_weak_knowledge_points,
            load_random=get_practice_questions,
            load_vector_recalls=vector_retrieval_service.vector_recall_by_text,
            load_vector_matches=load_vector_matches,
            load_fill_questions=load_fill_questions,
        )
    )


# ── V4: 智能推荐综合打分 ─────────────────────────────────────────
def _build_scored_metadata(
    score: float,
    reasons: list[str],
    question_kp_ids: list[int],
    kp_names: dict[int, str],
    *,
    graph_candidates: dict,
    blocked_kps: dict,
    kp_mastery: dict,
    kp_observations: dict,
    strategy_config_id: int | None,
) -> dict:
    """Build a smart-scored metadata entry preserving the original field set."""
    return {
        "recommend_score": round(score, 2),
        "recommend_reason": _build_smart_recommendation_reason(
            reasons,
            question_kp_ids,
            kp_names,
            graph_candidates=graph_candidates,
            blocked_kps=blocked_kps,
            kp_mastery=kp_mastery,
            kp_observations=kp_observations,
        ),
        "strategy": "smart_scored",
        "strategy_config_id": strategy_config_id,
        "similarity": None,
    }


async def _load_scored_runtime_config(db: AsyncSession) -> dict:
    """Load scored recommendation config, falling back to built-in defaults."""
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

        scored_runtime = (
            await recommendation_strategy_service.get_scored_runtime_config(db)
        )
    except Exception:
        logger.warning("scored 全局策略配置读取失败，使用内置默认值", exc_info=True)
    return scored_runtime


def _build_smart_scored_candidate_conditions(
    user_id: int,
    scope_ids: list[int],
    exclude_answered: bool,
    no_repeat_days: int | None,
    now: datetime,
) -> tuple[list, object | None]:
    """Build candidate query conditions including 24h and exclude filters."""
    subject_cond = Question.subject_id.in_(scope_ids)
    conditions: list = [
        Question.is_active,
        subject_cond,
        _practice_revision_scope_condition(scope_ids),
    ]

    excluded_sub = _build_excluded_question_subquery(
        user_id=user_id,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
    )
    if excluded_sub is not None:
        conditions.append(Question.id.notin_(excluded_sub))

    # 硬性排除 24 h 内做过的题
    recent_cutoff = now - timedelta(hours=24)
    recent_q_sub = (
        select(PracticeRecord.question_id)
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= recent_cutoff,
        )
        .distinct()
    )
    conditions.append(Question.id.notin_(recent_q_sub))
    return conditions, excluded_sub


async def _load_smart_scored_candidates(
    db: AsyncSession,
    user_id: int,
    subject_code: str,
    subject_ids: list[int] | None,
    candidate_limit: int,
    exclude_answered: bool,
    no_repeat_days: int | None,
    count: int,
    now: datetime,
) -> tuple[list[Question], list, list[int], object | None, int]:
    """Build candidate pool with 24h exclusion, relaxing to fallback level 1 if insufficient."""
    scope_ids = (
        subject_ids
        if subject_ids is not None
        else await resolve_subject_ids(db, subject_code)
    )
    conditions, excluded_sub = _build_smart_scored_candidate_conditions(
        user_id,
        scope_ids,
        exclude_answered,
        no_repeat_days,
        now,
    )

    candidates = await _execute_candidate_query(db, conditions, candidate_limit)
    active_candidate_conditions = conditions
    fallback_level = 0

    # 24h 过滤后不足 → 放宽（降级 1）
    if len(candidates) < count:
        fallback_level = 1
        relaxed = [c for c in conditions if c is not conditions[-1]]
        active_candidate_conditions = relaxed
        candidates = await _execute_candidate_query(
            db,
            relaxed,
            candidate_limit,
        )

    return (
        candidates,
        active_candidate_conditions,
        scope_ids,
        excluded_sub,
        fallback_level,
    )


async def _execute_candidate_query(
    db: AsyncSession,
    conditions: list,
    candidate_limit: int,
) -> list[Question]:
    """Count, random-sample and execute a candidate query."""
    total = int(
        (
            await db.scalar(
                select(func.count()).select_from(
                    select(Question.id).where(and_(*conditions)).subquery()
                )
            )
        )
        or 0
    )
    query = (
        select(Question)
        .where(and_(*conditions))
        .options(selectinload(Question.subject_ref))
    )
    query = _random_sample_query(
        query,
        total,
        min(candidate_limit, total),
        Question.id,
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def _load_knowledge_and_graph_context(
    db: AsyncSession,
    user_id: int,
    scope_ids: list[int],
    candidates: list[Question],
    active_candidate_conditions: list,
    graph_runtime: dict,
    count: int,
) -> tuple[dict[int, tuple], dict[int, tuple[int, int]], dict]:
    """Load user knowledge state and optional adaptive graph expansion."""
    from app.models.user_knowledge_state import UserKnowledgeState

    ks_result = await db.execute(
        select(UserKnowledgeState).where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.subject_id.in_(scope_ids),
        )
    )
    knowledge_states = list(ks_result.scalars().all())
    kp_mastery: dict[int, tuple] = {
        s.knowledge_point_id: (s.mastery_score, s.confidence) for s in knowledge_states
    }
    kp_observations: dict[int, tuple[int, int]] = {
        s.knowledge_point_id: (s.attempt_count, s.wrong_count) for s in knowledge_states
    }

    graph_context: dict = {
        "blocked_targets": {},
        "prerequisite_candidates": {},
        "prerequisites_by_target": {},
    }
    try:
        from app.core.config import settings as _settings

        if _settings.ADAPTIVE_LEARNING_ENABLED and _settings.ADAPTIVE_PATH_ENABLED:
            graph_context = await _expand_graph_candidates(
                db,
                user_id,
                scope_ids,
                candidates,
                active_candidate_conditions,
                kp_mastery,
                graph_runtime,
                count,
                graph_context,
            )
    except Exception:
        # Graph is an enhancement, never a single point of failure.
        logger.warning(
            "V6.5 图谱候选扩展失败（继续使用基础 scored）uid=%s", user_id, exc_info=True
        )
        graph_context = {
            "blocked_targets": {},
            "prerequisite_candidates": {},
            "prerequisites_by_target": {},
        }
    return kp_mastery, kp_observations, graph_context


async def _fetch_graph_context(
    adaptive_learning_service: object,
    db: AsyncSession,
    user_id: int,
    target_kp_ids: list[int],
    subject_ids: list[int],
    graph_runtime: dict,
) -> dict:
    """Fetch adaptive prerequisite context without copying the provider result."""
    return await adaptive_learning_service.get_recommendation_graph_context(
        db=db,
        user_id=user_id,
        target_kp_ids=target_kp_ids,
        subject_ids=subject_ids,
        max_depth=int(graph_runtime.get("max_depth", 2)),
        max_nodes=int(graph_runtime.get("max_nodes", 24)),
        min_mastery=float(graph_runtime.get("prerequisite_mastery_threshold", 60.0)),
        min_confidence=float(
            graph_runtime.get("prerequisite_confidence_threshold", 0.3)
        ),
    )


async def _extend_with_graph_question_candidates(
    db: AsyncSession,
    user_id: int,
    candidates: list[Question],
    active_candidate_conditions: list,
    graph_candidate_ids: list[int],
    weak_target_ids: list[int],
    count: int,
) -> None:
    """Query prerequisite-linked questions and extend the candidate list."""
    from app.models.question_knowledge_point import QuestionKnowledgePoint

    existing_ids = {q.id for q in candidates}
    graph_limit = max(count * 3, 30)
    graph_question_ids = select(QuestionKnowledgePoint.question_id).where(
        QuestionKnowledgePoint.knowledge_point_id.in_(graph_candidate_ids)
    )
    graph_query = (
        select(Question)
        .where(
            and_(
                *active_candidate_conditions,
                Question.id.in_(graph_question_ids),
                Question.id.notin_(existing_ids),
            )
        )
        .options(selectinload(Question.subject_ref))
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


async def _expand_graph_candidates(
    db: AsyncSession,
    user_id: int,
    scope_ids: list[int],
    candidates: list[Question],
    active_candidate_conditions: list,
    kp_mastery: dict[int, tuple],
    graph_runtime: dict,
    count: int,
    graph_context: dict,
) -> dict:
    """Expand candidates via adaptive prerequisite graph (SAVEPOINT isolated)."""
    from app.models.question_knowledge_point import (
        QuestionKnowledgePoint,  # noqa: F401 - preserve pre-savepoint import
    )

    async with db.begin_nested():
        weak_target_ids = _pick_graph_target_kps(
            kp_mastery,
            limit=int(graph_runtime.get("weak_target_limit", 5)),
        )
        if not weak_target_ids:
            return graph_context
        from app.services import adaptive_learning_service

        graph_context = await _fetch_graph_context(
            adaptive_learning_service,
            db,
            user_id,
            weak_target_ids,
            scope_ids,
            graph_runtime,
        )
        graph_candidate_ids = list(
            graph_context.get("prerequisite_candidates", {}).keys()
        )
        if not graph_candidate_ids:
            return graph_context
        await _extend_with_graph_question_candidates(
            db,
            user_id,
            candidates,
            active_candidate_conditions,
            graph_candidate_ids,
            weak_target_ids,
            count,
        )
    return graph_context


async def _load_candidate_states(
    db: AsyncSession,
    user_id: int,
    cand_ids: set[int],
    scope_ids: list[int],
) -> tuple[dict[int, object], set[int], dict[int, list[int]]]:
    """Load user question state, recent knowledge points, and QKP mapping."""
    from app.models.user_question_state import UserQuestionState

    qs_result = await db.execute(
        select(UserQuestionState).where(
            UserQuestionState.user_id == user_id,
            UserQuestionState.question_id.in_(cand_ids),
        )
    )
    q_state_map: dict[int, object] = {
        s.question_id: s for s in qs_result.scalars().all()
    }

    recent_kp_result = await db.execute(
        select(QuestionVersionKnowledgePoint.knowledge_point_id)
        .join(
            PracticeRecord,
            PracticeRecord.question_version_id
            == QuestionVersionKnowledgePoint.question_version_id,
        )
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.subject_id.in_(scope_ids),
        )
        .order_by(PracticeRecord.answered_at.desc())
        .limit(20)
    )
    recent_kp_ids: set[int] = {r[0] for r in recent_kp_result.all()}

    from app.models.question_knowledge_point import QuestionKnowledgePoint

    qkp_result = await db.execute(
        select(
            QuestionKnowledgePoint.question_id,
            QuestionKnowledgePoint.knowledge_point_id,
        ).where(QuestionKnowledgePoint.question_id.in_(cand_ids))
    )
    q_kp_map: dict[int, list[int]] = {}
    for qid, kid in qkp_result.all():
        q_kp_map.setdefault(qid, []).append(kid)
    return q_state_map, recent_kp_ids, q_kp_map


async def _load_kp_names(
    db: AsyncSession,
    q_kp_map: dict[int, list[int]],
    scope_ids: list[int],
) -> dict[int, str]:
    """Load KP names for all candidate knowledge points."""
    all_candidate_kp_ids = list({kid for kids in q_kp_map.values() for kid in kids})
    if not all_candidate_kp_ids:
        return {}
    from app.models.knowledge_point import KnowledgePoint

    kp_name_result = await db.execute(
        select(KnowledgePoint.id, KnowledgePoint.name).where(
            KnowledgePoint.id.in_(all_candidate_kp_ids),
            KnowledgePoint.subject_id.in_(scope_ids),
            KnowledgePoint.is_active == True,  # noqa: E712
        )
    )
    return {row.id: row.name for row in kp_name_result.all()}


async def _compute_recommendation_weights(
    db: AsyncSession,
    user_id: int,
    system_weights: dict,
) -> dict[str, float]:
    """Merge admin system weights with user adaptive weights."""
    user_weights: dict[str, float] = {key: 1.0 for key in system_weights}
    try:
        from app.core.config import settings as _settings

        if _settings.ADAPTIVE_LEARNING_ENABLED and _settings.ADAPTIVE_WEIGHT_ENABLED:
            from app.services import adaptive_learning_service

            user_weights = await adaptive_learning_service.get_recommend_weights(
                db, user_id
            )
    except Exception:
        logger.debug(
            "V6.4 用户权重加载失败（不影响推荐）uid=%s", user_id, exc_info=True
        )

    weight_keys = {
        "due_weight",
        "weakness_weight",
        "wrong_weight",
        "new_question_weight",
        "diversity_weight",
        "path_weight",
    }
    return {
        key: float(system_weights.get(key, 1.0)) * float(user_weights.get(key, 1.0))
        for key in weight_keys
    }


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
    from app.models.question_knowledge_point import (
        QuestionKnowledgePoint,  # noqa: F401 - preserve entry import boundary
    )
    from app.models.user_knowledge_state import (
        UserKnowledgeState,  # noqa: F401 - preserve entry import boundary
    )
    from app.models.user_question_state import (
        UserQuestionState,  # noqa: F401 - preserve entry import boundary
    )

    now = utcnow()
    metadata: dict[int, dict] = {}
    fallback_level = 0

    scored_runtime = await _load_scored_runtime_config(db)
    system_weights = scored_runtime.get("weights") or {}
    graph_runtime = scored_runtime.get("graph") or {}

    candidate_limit = max(count * 5, 50)
    (
        candidates,
        active_candidate_conditions,
        scope_ids,
        excluded_sub,
        fallback_level,
    ) = await _load_smart_scored_candidates(
        db,
        user_id,
        subject_code,
        subject_ids,
        candidate_limit,
        exclude_answered,
        no_repeat_days,
        count,
        now,
    )
    subject_cond = Question.subject_id.in_(scope_ids)

    if not candidates:
        logger.warning(
            "[smart_scored] 候选题池为空 uid=%s subject=%s", user_id, subject_code
        )
        return [], metadata

    (
        kp_mastery,
        kp_observations,
        graph_context,
    ) = await _load_knowledge_and_graph_context(
        db,
        user_id,
        scope_ids,
        candidates,
        active_candidate_conditions,
        graph_runtime,
        count,
    )

    cand_ids = {q.id for q in candidates}
    q_state_map, recent_kp_ids, q_kp_map = await _load_candidate_states(
        db,
        user_id,
        cand_ids,
        scope_ids,
    )
    blocked_kps, graph_candidates, prerequisites_by_target = _extract_graph_context(
        graph_context
    )
    kp_names = await _load_kp_names(db, q_kp_map, scope_ids)
    rec_weights = await _compute_recommendation_weights(
        db,
        user_id,
        system_weights,
    )

    scored = score_and_rank_candidates(
        candidates,
        q_state_map,
        q_kp_map,
        kp_mastery,
        recent_kp_ids,
        now,
        kp_observations=kp_observations,
        blocked_kps=blocked_kps,
        graph_candidates=graph_candidates,
        prerequisites_by_target=prerequisites_by_target,
        weights=rec_weights,
        graph_config=graph_runtime,
        calculate_score=calculate_smart_score,
    )

    # 调试日志
    if scored:
        top = scored[:5]
        logger.info(
            "[smart_scored] top5 uid=%s: %s",
            user_id,
            [(q.id, round(s, 1), r) for q, s, r in top],
        )

    def scored_metadata(score: float, reasons: list[str], kp_ids: list[int]) -> dict:
        return _build_scored_metadata(
            score,
            reasons,
            kp_ids,
            kp_names,
            graph_candidates=graph_candidates,
            blocked_kps=blocked_kps,
            kp_mastery=kp_mastery,
            kp_observations=kp_observations,
            strategy_config_id=scored_runtime.get("strategy_config_id"),
        )

    selected, selected_ids, relaxed_diversity = select_scored_candidates(
        scored,
        count,
        q_kp_map,
        metadata,
        scored_metadata,
    )
    if relaxed_diversity:
        fallback_level = max(fallback_level, 2)

    fallback = await run_scored_fallback(
        ScoredFallbackRequest(
            db=db,
            selected=selected,
            selected_ids=selected_ids,
            metadata=metadata,
            count=count,
            fallback_level=fallback_level,
            base_conditions=[Question.is_active],
            subject_condition=subject_cond,
            candidate_ids=cand_ids,
            excluded_subquery=excluded_sub,
            scope_ids=scope_ids,
            revision_condition=_practice_revision_scope_condition,
            random_fill=load_random_fill_questions,
            repeat_fill=load_repeat_fill_questions,
            sample_query=_random_sample_query,
            merge_fill=merge_fill_questions,
            metadata_factory=_build_fallback_metadata,
        )
    )
    selected = fallback.questions
    fallback_level = fallback.fallback_level

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
        select(
            PracticeRecord.is_correct,
            func.coalesce(SyllabusKnowledgePoint.name_snapshot, KnowledgePoint.name),
        )
        .join(
            QuestionVersionKnowledgePoint,
            QuestionVersionKnowledgePoint.question_version_id
            == PracticeRecord.question_version_id,
        )
        .join(
            KnowledgePoint,
            KnowledgePoint.id == QuestionVersionKnowledgePoint.knowledge_point_id,
        )
        .outerjoin(
            SyllabusKnowledgePoint,
            SyllabusKnowledgePoint.id
            == QuestionVersionKnowledgePoint.syllabus_knowledge_point_id,
        )
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= cutoff,
            subject_cond,
        )
    )
    rows = result.all()

    if not rows:
        return []

    # 历史统计按作答时 immutable revision 的知识点归因。这里只读取真正
    # 需要的列，避免任何 PracticeRecord ORM 全量加载重新引入已废弃批次字段。
    kp_stats: dict[str, dict] = {}
    for is_correct, kp_name in rows:
        kp = str(kp_name)
        if kp not in kp_stats:
            kp_stats[kp] = {"total": 0, "correct": 0}
        kp_stats[kp]["total"] += 1
        if bool(is_correct):
            kp_stats[kp]["correct"] += 1

    # 筛选薄弱知识点
    weak = []
    for kp_name, stats in kp_stats.items():
        total = stats["total"]
        correct = stats["correct"]
        if total >= 2:
            accuracy = correct / total
            if accuracy < 0.65:
                weak.append(
                    {
                        "name": kp_name,
                        "total": total,
                        "correct": correct,
                        "accuracy": round(accuracy, 4),
                    }
                )

    # 按 accuracy 升序、total 降序
    weak.sort(key=lambda x: (x["accuracy"], -x["total"]))
    return weak[:5]


async def _create_answer_projection_outbox(
    db: AsyncSession,
    *,
    practice_record_id: int,
    request_id: str | None,
) -> None:
    """Persist one immutable-revision projection event with the answer row."""
    from app.services.outbox_service import create_outbox

    await create_outbox(
        db,
        task_id=f"answer_projection:{practice_record_id}",
        task_type="answer_projection",
        payload={
            "practice_record_id": int(practice_record_id),
            "request_id": _normalize_practice_request_id(request_id),
        },
        schema_version=ANSWER_PROJECTION_TASK_SCHEMA_VERSION,
    )


def _raise_practice_submission_conflict(message: str) -> None:
    raise PracticeSubmissionConflictError(message)


def _replay_committed_submission(existing: PracticeSession, payload_hash: str) -> dict:
    if existing.submission_payload_hash != payload_hash:
        _raise_practice_submission_conflict(
            "session.request_id 已用于另一组提交（答案或会话内容不一致）"
        )
    if not isinstance(existing.submission_response, dict):
        _raise_practice_submission_conflict(
            "session.request_id 对应的 canonical response 缺失，提交状态不可恢复"
        )
    return dict(existing.submission_response)


async def batch_submit_answers(
    db: AsyncSession,
    user_id: int,
    answers: list[dict],
    session_meta: dict,
    skipped_question_ids: list[int],
    batch_token: str,
) -> dict:
    """Atomically persist one signed practice batch against immutable revisions.

    The signed batch binds every question to a concrete ``QuestionVersion.id``.
    Grading, review payloads, wrong-book entries and asynchronous projections all
    reference that revision; current Question rows are never consulted to decide
    what the user saw.
    """
    from app.services.practice.batch_submission import (
        build_response_by_question,
        build_session_consistency_error,
        evaluate_batch_answers,
        validate_answer_duration,
        validate_batch_submission_inputs,
    )

    if not batch_token:
        raise PracticeBatchTokenError("batch_token 不能为空，请重新获取题目")
    if not session_meta:
        raise PracticeBatchTokenError("session 不能为空，请重新获取题目")
    if skipped_question_ids is None:
        raise PracticeBatchTokenError("skipped_question_ids 必须显式提交")
    if len(answers) > PRACTICE_BATCH_MAX_QUESTIONS:
        raise ValueError(f"answers 最多允许 {PRACTICE_BATCH_MAX_QUESTIONS} 题")
    if len(skipped_question_ids) > PRACTICE_BATCH_MAX_QUESTIONS:
        raise ValueError(
            f"skipped_question_ids 最多允许 {PRACTICE_BATCH_MAX_QUESTIONS} 题"
        )

    answer_question_ids, skipped_ids, all_question_ids = validate_batch_submission_inputs(
        answers=answers,
        skipped_question_ids=skipped_question_ids,
        max_questions=PRACTICE_BATCH_MAX_QUESTIONS,
    )

    payload_hash = _practice_submission_fingerprint(
        answers=answers,
        skipped_question_ids=skipped_ids,
        session_meta=session_meta,
        batch_token=batch_token,
    )
    request_id = _normalize_practice_request_id(session_meta.get("request_id"))
    if not request_id:
        raise ValueError("session.request_id 不能为空")

    # Fast idempotent replay does not depend on token expiry or current question
    # state. Once a submission is committed, request_id + payload hash is enough.
    existing = await db.scalar(
        select(PracticeSession).where(
            PracticeSession.user_id == user_id,
            PracticeSession.request_id == request_id,
        )
    )
    if existing is not None:
        return _replay_committed_submission(existing, payload_hash)

    issued_revisions, issued_order, batch_payload = _validate_practice_batch_token(
        batch_token,
        user_id=user_id,
        question_ids=all_question_ids,
        session_meta=session_meta,
        answers=answers,
    )

    from app.services.question_revision_service import (
        load_revision_kp_names,
        load_revision_views,
    )

    revision_views = await load_revision_views(db, issued_revisions.values())
    if len(revision_views) != len(issued_revisions):
        raise PracticeBatchTokenError("练习批次引用的题目 revision 不完整")

    questions: dict[int, object] = {}
    for qid, revision_id in issued_revisions.items():
        view = revision_views.get(int(revision_id))
        if view is None or int(view.question_id) != int(qid):
            raise PracticeBatchTokenError("练习批次题目与 revision 绑定关系无效")
        if not view.is_active:
            # A valid issued practice batch can only originate from an active
            # revision. This catches corrupted/manual token state, not later edits.
            raise PracticeBatchTokenError("练习批次包含不可用题目 revision")
        questions[int(qid)] = view

    evaluated_answers, answer_request_ids, total_correct, total_wrong = (
        evaluate_batch_answers(answers=answers, questions=questions)
    )
    skipped_questions = [questions[qid] for qid in skipped_ids]

    session_values = _normalize_practice_session(
        session_meta,
        user_id=user_id,
        answered_count=len(evaluated_answers),
        total_correct=total_correct,
        total_wrong=total_wrong,
    )
    consistency_error = build_session_consistency_error(
        session_values=session_values,
        request_id=request_id,
        total_question_count=len(all_question_ids),
        batch_payload=batch_payload,
    )
    if consistency_error:
        if "request_id" in consistency_error or "question_count" in consistency_error:
            raise ValueError(consistency_error)
        raise PracticeBatchTokenError(consistency_error)

    duration_error = validate_answer_duration(
        evaluated_answers=evaluated_answers,
        duration_sec=int(session_values.get("duration_sec") or 0),
        tolerance_sec=PRACTICE_ANSWER_DURATION_TOLERANCE_SEC,
    )
    if duration_error:
        raise ValueError(duration_error)

    from app.services.practice.session_scope import build_practice_session_scope

    scope_snapshot = build_practice_session_scope(
        batch_payload.get("knowledge_context"),
        fallback_subject_id=int(session_values.get("subject_id") or 0),
    )
    if scope_snapshot is not None:
        signed_scope_subject_id = int(scope_snapshot.get("subject_id") or 0)
        if signed_scope_subject_id and signed_scope_subject_id != int(
            session_values.get("subject_id") or 0
        ):
            raise PracticeBatchTokenError("知识练习范围与练习科目不一致")

    session_obj = PracticeSession(
        **session_values,
        submission_payload_hash=payload_hash,
        scope_type=(
            str(scope_snapshot["practice_mode"]) if scope_snapshot is not None else None
        ),
        scope_root_knowledge_point_id=(
            int(scope_snapshot["root_knowledge_point_id"])
            if scope_snapshot is not None
            else None
        ),
        scope_snapshot=scope_snapshot,
    )
    await _start_explicit_transaction(db)
    try:
        # Claim the request id in a savepoint. A concurrent winner must not
        # poison the caller's transaction before we replay its committed result.
        async with db.begin_nested():
            db.add(session_obj)
            await db.flush()
    except IntegrityError as exc:
        if not _is_unique_violation(exc):
            await db.rollback()
            raise
        winner = await db.scalar(
            select(PracticeSession).where(
                PracticeSession.user_id == user_id,
                PracticeSession.request_id == request_id,
            )
        )
        if winner is None:
            await db.rollback()
            raise
        return _replay_committed_submission(winner, payload_hash)

    try:
        now = utcnow()
        records: list[tuple[PracticeRecord, object, bool, str, int | None]] = []
        for q, is_correct, user_answer, used_time in evaluated_answers:
            record = PracticeRecord(
                user_id=user_id,
                question_id=int(q.id),
                question_version_id=int(q.question_version_id),
                subject_id=int(q.subject_id),
                question_type=q.question_type,
                user_answer=user_answer,
                is_correct=is_correct,
                used_time=used_time,
                answered_at=now,
                mode=session_values["mode"],
                projection_state="pending",
            )
            db.add(record)
            records.append((record, q, is_correct, user_answer, used_time))
        if records:
            await db.flush()

        from app.services.wrong_question_service import record_wrong

        prewarm_wrong_questions = []
        wrong_question_ids: dict[int, int] = {}
        for record, q, is_correct, user_answer, _used_time in records:
            if not is_correct:
                wrong = await record_wrong(
                    db,
                    user_id,
                    int(q.id),
                    user_answer,
                    question_version_id=int(q.question_version_id),
                    commit=False,
                )
                diagnosis_payload = await persist_wrong_answer(
                    db,
                    user_id=user_id,
                    record=record,
                    question=q,
                    wrong=wrong,
                    now=now,
                )
                prewarm_wrong_questions.append(wrong)
                wrong_question_ids[int(q.id)] = int(wrong.id)
                setattr(record, "_error_diagnosis_payload", diagnosis_payload)
            await _create_answer_projection_outbox(
                db,
                practice_record_id=int(record.id),
                request_id=answer_request_ids.get(int(q.id)),
            )

        revision_kps = await load_revision_kp_names(db, issued_revisions.values())
        response_by_question = build_response_by_question(
            records=records,
            skipped_questions=skipped_questions,
            revision_kps=revision_kps,
            wrong_question_ids=wrong_question_ids,
        )

        from app.services.practice.knowledge_session_summary import (
            persisted_knowledge_session,
        )

        response_payload = jsonable_encoder(
            {
                "results": [response_by_question[qid] for qid in issued_order],
                "total_correct": total_correct,
                "total_wrong": total_wrong,
                "total_skipped": len(skipped_questions),
                "knowledge_session": persisted_knowledge_session(
                    batch_payload.get("knowledge_context")
                ),
                "entry_context": (
                    dict(batch_payload.get("entry_context"))
                    if isinstance(batch_payload.get("entry_context"), dict)
                    else None
                ),
            }
        )
        # submission_response is a SQL JSON column and is also the source used
        # for idempotent replay. Nested diagnostics may contain datetime values,
        # so normalize the entire payload once before persistence and response.
        session_obj.submission_response = response_payload
        sequential_reservation_request_id = batch_payload.get(
            "seq_reservation_request_id"
        )
        if (
            sequential_reservation_request_id
            and str(batch_payload.get("mode")) == "sequential"
        ):
            await db.execute(
                delete(SequentialReservation).where(
                    SequentialReservation.user_id == user_id,
                    SequentialReservation.subject_id
                    == int(batch_payload.get("sid") or 0),
                    SequentialReservation.start_request_id
                    == str(sequential_reservation_request_id),
                    SequentialReservation.question_id.in_(all_question_ids),
                )
            )
        await db.commit()
    except BaseException:
        # Once the session claim is accepted this service owns the whole outer
        # transaction. Roll back before propagating so no partial state remains.
        await db.rollback()
        raise

    if prewarm_wrong_questions:
        try:
            from app.ai.prewarm_revision import build_prewarm_revision
            from app.services.ai_prewarm_worker import enqueue_prewarm

            await enqueue_wrong_answer_prewarm(
                prewarm_wrong_questions,
                user_id,
                build_revision=build_prewarm_revision,
                enqueue=enqueue_prewarm,
            )
        except Exception:
            logger.warning(
                "AI prewarm enqueue failed after practice batch", exc_info=True
            )

    return response_payload



async def get_practice_stats(
    db: AsyncSession,
    user_id: int,
    days: int = 7,
) -> dict:
    total_answered, total_correct = await load_practice_totals(db, user_id)
    by_subject = await load_subject_breakdown(db, user_id)
    daily_stats = await load_daily_breakdown(db, user_id, days, _china_date_expr)
    streak = await _calc_streak(db, user_id)

    return {
        "total_answered": total_answered,
        "total_correct": total_correct,
        "accuracy": _practice_accuracy(total_correct, total_answered),
        "by_subject": by_subject,
        "daily_stats": daily_stats,
        "current_streak": streak,
    }


async def _calc_streak(db: AsyncSession, user_id: int) -> int:
    today = shanghai_today()
    since = shanghai_date_utc_range(today - timedelta(days=364))[0]
    day_expr = await _china_date_expr(db, PracticeRecord.answered_at)
    result = await db.execute(
        select(day_expr)
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= since,
        )
        .distinct()
        .order_by(day_expr.desc())
    )
    dates = {
        date.fromisoformat(row[0]) if isinstance(row[0], str) else row[0]
        for row in result.all()
    }

    streak = 0
    for i in range(365):
        d = today - timedelta(days=i)
        if d in dates:
            streak += 1
        else:
            break
    return streak

import base64
import hashlib
import hmac
import json
import logging
import random
import time
from datetime import date, datetime, timedelta
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import Date as SQLDate
from sqlalchemy import and_, case, cast, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.subject_scope import (
    EXAM408_CORE_CODES,
    EXAM408_DISPLAY_ORDER,
    canonical_408_code,
    is_study_subject_enabled,
    select_study_subject_records,
    selected_study_subject_ids,
    study_subject_display_name,
)
from app.core.time_utils import (
    normalize_to_naive_utc,
    shanghai_date_utc_range,
    shanghai_today,
    utcnow,
)
from app.features.question_type import (
    QT_MULTI_BLANK_CHOICE,
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
from app.models.syllabus import SyllabusKnowledgePoint
from app.services.admin_subject_service import resolve_subject_ids
from app.services.knowledge_point_service import (
    kp_any_condition,
    kp_exact_conditions,
    load_question_kps,
)
from app.services.practice.answer_projection_contract import (
    ANSWER_PROJECTION_TASK_SCHEMA_VERSION,
)
from app.services.practice.recommendation_pipeline import (
    merge_recommendation_results,
    normalize_smart_strategy,
)
from app.services.practice.sequential_service import (
    SEQUENTIAL_MODE,
    get_sequential_practice_questions,
    reset_sequential_progress,  # noqa: F401 — re-exported for the practice API
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
from app.utils.answer_normalizer import (
    extract_multi_blank_slot_ids,
    is_answer_correct,
)

logger = logging.getLogger(__name__)


class PracticeSubmissionConflictError(ValueError):
    """The idempotency key belongs to a different semantic submission."""


class PracticeBatchTokenError(ValueError):
    """The signed practice batch token is invalid, expired, or mismatched."""


# 单次刷题会话时长上限（秒）。自由计时番茄钟上限 5h，刷题会话留余量到 6h；
# 用于防御异常客户端上报 duration_sec=999999999。
PRACTICE_SESSION_MAX_DURATION_SEC = 6 * 60 * 60
PRACTICE_ANSWER_MAX_USED_TIME_SEC = PRACTICE_SESSION_MAX_DURATION_SEC
PRACTICE_BATCH_MAX_QUESTIONS = 50
PRACTICE_BATCH_TOKEN_TTL_SEC = 24 * 60 * 60
PRACTICE_ANSWER_DURATION_TOLERANCE_SEC = 5
PRACTICE_BATCH_CLOCK_SKEW_SEC = 5 * 60
PRACTICE_ALLOWED_MODES = {"random", "smart", "similar", "sequential"}
# The current mini-program runner only provides interactive controls for these
# question types.  Text/free-response revisions must not be issued into a batch
# until the runner has an input path for them, otherwise the user can never mark
# the question answered and is forced to submit it as skipped.
PRACTICE_ANSWERABLE_QUESTION_TYPES = frozenset({
    QT_SINGLE_CHOICE,
    QT_MULTIPLE_CHOICE,
    QT_TRUE_FALSE,
    QT_MULTI_BLANK_CHOICE,
})
_PRACTICE_BATCH_TOKEN_VERSION = 2


def _practice_batch_signing_key() -> bytes:
    return hmac.new(
        settings.APP_SECRET.encode("utf-8"),
        b"memograd:practice-batch:v2",
        hashlib.sha256,
    ).digest()


def _urlsafe_b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _urlsafe_b64decode(text_value: str) -> bytes:
    padding = "=" * (-len(text_value) % 4)
    return base64.urlsafe_b64decode((text_value + padding).encode("ascii"))


def create_practice_batch_token(
    *,
    user_id: int,
    subject_id: int,
    mode: str,
    questions: list[Question],
    revision_ids: dict[int, int],
    recommendation_request_id: str | None = None,
) -> tuple[str | None, dict[int, int], str | None]:
    """Create a signed batch bound to immutable QuestionVersion ids.

    ``revision_ids`` must come from the newest immutable revision resolver; do
    not fall back to ``Question.current_version_id`` because that projection
    pointer is precisely the field that can lag behind revision history.  The
    token does not embed answers or mutable
    fingerprints, and submission never re-resolves against the mutable
    ``questions`` row.
    """
    if not questions:
        return None, {}, None
    normalized_mode = str(mode or "random")
    if normalized_mode not in PRACTICE_ALLOWED_MODES:
        raise PracticeBatchTokenError("练习模式无效")

    revisions: dict[int, int] = {}
    for question in questions:
        question_id = int(question.id)
        if question_id in revisions:
            # A token containing the same qid twice can be issued successfully but
            # is intentionally rejected by the submit-side duplicate guard.  Fail
            # closed here so future callers can never create an un-submittable batch.
            raise PracticeBatchTokenError("练习批次包含重复题目")
        version_id = revision_ids.get(question_id)
        if not version_id:
            raise RuntimeError(
                f"题目 {question.id} 缺少可用 question_version，题目版本数据不完整"
            )
        revisions[question_id] = int(version_id)

    now = int(time.time())
    submission_request_id = f"practice_{uuid4().hex}"
    payload = {
        "v": _PRACTICE_BATCH_TOKEN_VERSION,
        "uid": int(user_id),
        "rid": submission_request_id,
        "rec_rid": _normalize_practice_request_id(recommendation_request_id),
        "sid": int(subject_id),
        "mode": normalized_mode,
        "iat": now,
        "exp": now + PRACTICE_BATCH_TOKEN_TTL_SEC,
        # Preserve issued order. Each pair is [question_id, immutable revision_id].
        "questions": [[int(q.id), revisions[int(q.id)]] for q in questions],
    }
    body = _urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = _urlsafe_b64encode(
        hmac.new(_practice_batch_signing_key(), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{signature}", revisions, submission_request_id


def _decode_practice_batch_token(token: str) -> dict:
    try:
        body, signature = str(token or "").split(".", 1)
        expected = _urlsafe_b64encode(
            hmac.new(_practice_batch_signing_key(), body.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise PracticeBatchTokenError("练习批次签名无效")
        payload = json.loads(_urlsafe_b64decode(body).decode("utf-8"))
    except PracticeBatchTokenError:
        raise
    except Exception as exc:
        raise PracticeBatchTokenError("练习批次 token 格式无效") from exc
    if not isinstance(payload, dict) or payload.get("v") != _PRACTICE_BATCH_TOKEN_VERSION:
        raise PracticeBatchTokenError("练习批次 token 版本无效")
    if int(payload.get("exp") or 0) < int(time.time()):
        raise PracticeBatchTokenError("练习批次已过期，请重新获取题目")
    return payload


def _validate_practice_batch_token(
    token: str,
    *,
    user_id: int,
    question_ids: list[int],
    session_meta: dict,
    answers: list[dict],
) -> tuple[dict[int, int], list[int], dict]:
    payload = _decode_practice_batch_token(token)
    if int(payload.get("uid") or 0) != int(user_id):
        raise PracticeBatchTokenError("练习批次不属于当前用户")

    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions or len(raw_questions) > PRACTICE_BATCH_MAX_QUESTIONS:
        raise PracticeBatchTokenError("练习批次题目列表无效")
    revisions: dict[int, int] = {}
    issued_order: list[int] = []
    try:
        for item in raw_questions:
            if not isinstance(item, list) or len(item) != 2:
                raise ValueError
            qid = int(item[0])
            revision_id = int(item[1])
            if qid <= 0 or revision_id <= 0 or qid in revisions:
                raise ValueError
            revisions[qid] = revision_id
            issued_order.append(qid)
    except (TypeError, ValueError) as exc:
        raise PracticeBatchTokenError("练习批次题目列表无效") from exc

    submitted_ids = [int(qid) for qid in question_ids]
    if len(submitted_ids) != len(issued_order) or set(submitted_ids) != set(issued_order):
        raise PracticeBatchTokenError("提交题目与服务器下发批次不一致")

    try:
        subject_id = int(session_meta.get("subject_id"))
    except (TypeError, ValueError) as exc:
        raise PracticeBatchTokenError("练习批次缺少有效科目") from exc
    if int(payload.get("sid") or 0) != subject_id:
        raise PracticeBatchTokenError("提交科目与服务器下发批次不一致")

    mode = str(session_meta.get("mode") or "random")
    if mode not in PRACTICE_ALLOWED_MODES or str(payload.get("mode") or "") != mode:
        raise PracticeBatchTokenError("提交模式与服务器下发批次不一致")

    token_request_id = str(payload.get("rid") or "").strip()
    session_request_id = _normalize_practice_request_id(session_meta.get("request_id"))
    if not token_request_id or token_request_id != session_request_id:
        raise PracticeBatchTokenError("提交 request_id 与服务器下发批次不一致")

    expected_rec_rid = _normalize_practice_request_id(payload.get("rec_rid"))
    for answer in answers:
        actual_rec_rid = _normalize_practice_request_id(answer.get("request_id"))
        if actual_rec_rid != expected_rec_rid:
            raise PracticeBatchTokenError("推荐反馈 request_id 与服务器下发批次不一致")

    issued_at = int(payload.get("iat") or 0)
    started_at = _parse_session_datetime(session_meta.get("started_at"))
    finished_at = _parse_session_datetime(session_meta.get("finished_at"))
    if issued_at and started_at is not None:
        issued_dt = datetime.utcfromtimestamp(issued_at)
        if started_at < issued_dt - timedelta(seconds=PRACTICE_BATCH_CLOCK_SKEW_SEC):
            raise PracticeBatchTokenError("练习开始时间早于题目下发时间")
    if finished_at is not None and finished_at > utcnow() + timedelta(seconds=PRACTICE_BATCH_CLOCK_SKEW_SEC):
        raise PracticeBatchTokenError("练习结束时间明显晚于服务器时间")

    return revisions, issued_order, payload


def _normalize_answer_used_time(value) -> int | None:
    if value is None:
        return None
    try:
        used_time = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("answers.used_time 必须为整数") from exc
    if used_time < 0 or used_time > PRACTICE_ANSWER_MAX_USED_TIME_SEC:
        raise ValueError(
            f"answers.used_time 必须在 0~{PRACTICE_ANSWER_MAX_USED_TIME_SEC} 秒之间"
        )
    return used_time


async def _china_date_expr(db: AsyncSession, column):
    bind = await db.connection()
    if bind.sync_connection.dialect.name == "sqlite":
        return func.date(column, "+8 hours")
    return cast(column + text("INTERVAL '8 hours'"), SQLDate)
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


def _normalize_practice_request_id(value) -> str | None:
    request_id = str(value or "").strip() or None
    if request_id is not None and len(request_id) > 128:
        raise ValueError("request_id 长度不得超过 128")
    return request_id


def _normalize_practice_session(
    session_meta: dict,
    *,
    user_id: int,
    answered_count: int,
    total_correct: int,
    total_wrong: int,
) -> dict:
    """Validate the mandatory server-issued practice session metadata."""
    if not session_meta:
        raise ValueError("session 不能为空")

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
    # 不允许明显超过墙钟（保留少量取整误差），异常值直接拒绝，避免
    # fingerprint 与最终落库 duration 不一致。
    if duration_sec > wall_sec + _PRACTICE_DURATION_ROUNDING_TOLERANCE:
        raise ValueError("session.duration_sec 不得超过 started_at/finished_at 墙钟时长")
    if duration_sec > PRACTICE_SESSION_MAX_DURATION_SEC:
        raise ValueError("session.duration_sec 超过允许上限")

    # 数据库列 String(256)：超长 request_id 使用稳定 hash，避免截断碰撞。
    request_id = _normalize_practice_request_id(session_meta.get("request_id"))
    subject_id = session_meta.get("subject_id")
    try:
        subject_id = int(subject_id) if subject_id is not None else None
    except (TypeError, ValueError):
        raise ValueError("session.subject_id 必须为整数")

    mode = str(session_meta.get("mode") or "random")
    if mode not in PRACTICE_ALLOWED_MODES:
        raise ValueError("session.mode 无效")

    reported_answered_count = session_meta.get("answered_count")
    try:
        reported_answered_count = int(reported_answered_count)
    except (TypeError, ValueError) as exc:
        raise ValueError("session.answered_count 必须为整数") from exc
    if reported_answered_count != answered_count:
        raise ValueError("session.answered_count 与 answers 数量不一致")

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
    return query.order_by(id_col.asc() if id_col else func.random()).offset(offset).limit(need)


async def get_practice_subject_tree(db: AsyncSession) -> list[dict]:
    """返回当前产品可练习的 408 科目树。

    ``subjects.id`` 是唯一业务 ID；运行时仅接受规范化后的 canonical code。
    若 408 根科目缺失、重复或被停用，公共入口直接关闭，不再按名称/旧编码
    进行兼容回退。
    """
    from app.models.admin import Subject

    result = await db.execute(
        select(Subject).order_by(Subject.level.asc(), Subject.sort_order.asc(), Subject.id.asc())
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
    return roots


async def resolve_subject_id_to_code(db: AsyncSession, subject_id: int) -> tuple[str, str] | None:
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


_TRUE_FALSE_TRUE = {"a", "true", "对", "是", "正确", "t", "yes", "1"}
_TRUE_FALSE_FALSE = {"b", "false", "错", "否", "错误", "f", "no", "0"}


def _normalize_true_false_answer(value: str) -> str:
    v = str(value or "").strip().lower()
    if v in _TRUE_FALSE_TRUE:
        return "A"
    if v in _TRUE_FALSE_FALSE:
        return "B"
    return v.upper()


# High-confidence, discipline-specific anchors used only as a safety net for
# already-published 408 questions whose subject_id was historically assigned to
# the wrong discipline.  The guard is intentionally conservative: a mismatch is
# reported only when another discipline has several independent signals and a
# clear lead over the stored subject.  Normal cross-discipline terminology must
# not make a valid question disappear from practice.
_408_CONTENT_ANCHORS: dict[str, tuple[str, ...]] = {
    "data_structure": (
        "二叉树", "二叉排序树", "平衡二叉树", "红黑树", "b树", "b+树",
        "线索二叉树", "哈夫曼树", "链表", "顺序表", "邻接表", "邻接矩阵",
        "最小生成树", "拓扑排序", "关键路径", "散列表", "哈希表", "散列",
        "二分查找", "折半查找", "快速排序", "归并排序", "堆排序", "希尔排序",
        "插入排序", "冒泡排序", "深度优先", "广度优先", "dfs", "bfs",
    ),
    "operating_system": (
        "进程", "线程", "死锁", "信号量", "临界区", "管程", "银行家算法",
        "页面置换", "缺页", "页表", "页框", "页号", "虚拟内存", "虚拟页",
        "分段存储", "段表", "段号", "段内地址", "工作集", "驻留集", "抖动",
        "文件系统", "磁盘调度", "时间片", "pv操作",
    ),
    "computer_organization": (
        "cpu", "alu", "cache", "高速缓存", "主存", "存储器层次", "指令周期",
        "指令字", "微指令", "微程序", "流水线", "控制器", "运算器", "总线",
        "dma", "中断向量", "寻址方式", "补码", "原码", "浮点数", "ieee754",
        "ieee 754", "机器字长", "存储字长",
    ),
    "computer_network": (
        "tcp", "udp", "ipv4", "ipv6", "ip地址", "子网掩码", "路由表", "路由协议",
        "ospf", "rip", "bgp", "arp", "dns", "http", "以太网", "csma", "mac地址",
        "数据链路层", "网络层", "传输层", "应用层", "拥塞窗口", "三次握手",
        "四次挥手",
    ),
}


def _canonical_408_subject(code: str | None, name: str | None = None) -> str | None:
    # Runtime subject identity is code-only. ``name`` is intentionally ignored so
    # a stale/incorrect code cannot be masked by a matching display name.
    value = str(code or "").strip().lower()
    return value if value in EXAM408_CORE_CODES else None


def _question_stem_for_subject_guard(content: dict | None) -> str:
    if not isinstance(content, dict):
        return ""
    # Do not use analysis/knowledge-point text here: those fields can themselves
    # be wrong after a historical subject misclassification and would hide the
    # very mismatch this guard is meant to catch.
    value = content.get("text") or content.get("stem") or ""
    return str(value).strip().lower()


def _detect_408_subject_mismatch(
    *,
    subject_code: str | None,
    subject_name: str | None,
    stem: str,
) -> tuple[str | None, dict[str, int]]:
    """Return an inferred conflicting 408 discipline only at high confidence."""
    expected = _canonical_408_subject(subject_code, subject_name)
    if expected is None or not stem:
        return None, {}

    compact = stem.replace(" ", "")
    scores: dict[str, int] = {}
    for discipline, anchors in _408_CONTENT_ANCHORS.items():
        matched = 0
        for anchor in anchors:
            candidate = anchor.lower()
            haystack = compact if " " not in candidate else stem
            needle = candidate.replace(" ", "") if " " not in candidate else candidate
            if needle and needle in haystack:
                matched += 1
        scores[discipline] = matched

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked:
        return None, scores
    best_subject, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0
    expected_score = scores.get(expected, 0)

    # At least two independent anchors, a two-signal advantage over the stored
    # discipline, and a clear overall lead.  This catches e.g. "进程 + 段表 +
    # 段号 + 段内地址" stored as 数据结构, while leaving interdisciplinary or
    # ambiguous stems untouched.
    if (
        best_subject != expected
        and best_score >= 2
        and best_score - expected_score >= 2
        and best_score - second_score >= 1
    ):
        return best_subject, scores
    return None, scores


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
    if not questions:
        return []
    scope = {int(sid) for sid in subject_ids or []}
    resolved_revision_ids = revision_ids or await load_latest_question_revision_ids(
        db, [int(q.id) for q in questions]
    )
    version_ids = {int(version_id) for version_id in resolved_revision_ids.values() if version_id}
    if not scope or not version_ids:
        if questions:
            logger.error(
                "[PRACTICE_REVISION_SCOPE] empty scope/version set scope=%s question_ids=%s",
                sorted(scope), [int(q.id) for q in questions],
            )
        return []

    rows = await db.execute(
        select(
            QuestionVersion.id,
            QuestionVersion.question_id,
            QuestionVersion.subject_id,
            QuestionVersion.question_type,
            QuestionVersion.is_active,
            QuestionVersion.content,
        ).where(QuestionVersion.id.in_(version_ids))
    )
    revisions = {int(row.id): row for row in rows.all()}

    # Subject ids/codes are dynamic; never assume the historical numeric ids for
    # 数据结构/操作系统/组成原理/计网.  Resolve the live rows once so the semantic
    # guard also works after subject migrations or custom deployments.
    from app.models.admin import Subject
    revision_subject_ids = {
        int(row.subject_id) for row in revisions.values() if row.subject_id is not None
    }
    subject_rows = await db.execute(
        select(Subject.id, Subject.code, Subject.name).where(
            Subject.id.in_(scope | revision_subject_ids)
        )
    )
    subjects = {
        int(row.id): (str(row.code or ""), str(row.name or ""))
        for row in subject_rows.all()
    }

    kept: list[Question] = []
    rejected: list[dict] = []
    for question in questions:
        qid = int(question.id)
        q_subject_id = int(question.subject_id) if question.subject_id is not None else None
        version_id = resolved_revision_ids.get(qid)
        revision = revisions.get(version_id) if version_id else None
        revision_subject_id = (
            int(revision.subject_id)
            if revision is not None and revision.subject_id is not None
            else None
        )
        q_question_type = str(getattr(question, "question_type", "") or "")
        revision_question_type = str(getattr(revision, "question_type", "") or "")
        structural_valid = bool(
            q_subject_id in scope
            and revision is not None
            and int(revision.question_id) == qid
            and revision_subject_id == q_subject_id
            and revision_subject_id in scope
            and revision_question_type == q_question_type
            and revision_question_type in PRACTICE_ANSWERABLE_QUESTION_TYPES
            and bool(getattr(question, "is_active", False))
            and str(getattr(question, "review_status", "") or "") == "approved"
            and revision.is_active is True
        )

        semantic_mismatch = None
        semantic_scores: dict[str, int] = {}
        if structural_valid and revision_subject_id is not None:
            subject_code, subject_name = subjects.get(revision_subject_id, ("", ""))
            semantic_mismatch, semantic_scores = _detect_408_subject_mismatch(
                subject_code=subject_code,
                subject_name=subject_name,
                stem=_question_stem_for_subject_guard(revision.content),
            )

        if structural_valid and semantic_mismatch is None:
            kept.append(question)
        else:
            rejected.append({
                "question_id": qid,
                "question_subject_id": q_subject_id,
                "current_version_id": (
                    int(question.current_version_id)
                    if getattr(question, "current_version_id", None)
                    else None
                ),
                "issued_latest_version_id": version_id,
                "revision_subject_id": revision_subject_id,
                "question_type": q_question_type,
                "revision_question_type": revision_question_type,
                "answerable_type": revision_question_type in PRACTICE_ANSWERABLE_QUESTION_TYPES,
                "question_active": getattr(question, "is_active", None),
                "review_status": getattr(question, "review_status", None),
                "revision_active": getattr(revision, "is_active", None),
                "semantic_mismatch": semantic_mismatch,
                "semantic_scores": semantic_scores or None,
            })

    if rejected:
        logger.error(
            "[PRACTICE_REVISION_SCOPE] rejected=%d scope_ids=%s rows=%s",
            len(rejected), sorted(scope), rejected,
        )
    return kept


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
    if subj is None or not is_study_subject_enabled(subj):
        return False, []

    # 获取当前学生端可用科目以构建树。额外开放的四个科目即使曾被旧迁移
    # 标记为 inactive，也应在学生端继续可练习。
    all_result = await db.execute(
        select(Subject).order_by(Subject.level.asc(), Subject.sort_order.asc(), Subject.id.asc())
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
        conds = [
            Question.is_active,
            Question.subject_id == sid,
            _practice_revision_scope_condition([sid]),
        ]
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
            # Each bucket is already randomized inside its own Leitner/V1 query,
            # while the list order still encodes fallback priority (fresh/due
            # questions first, relaxed repeat-window candidates last).  Shuffling
            # the whole bucket here used to destroy that priority and could surface
            # a just-practiced fallback question even when a fresh candidate from
            # the same subject was available.  Only randomize bucket start order in
            # the round-robin merge below.
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
            subject_ids=[sid],
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
            total = int((await db.scalar(select(func.count()).select_from(count_base))) or 0)
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
    subject_ids: list[int] | None = None,
) -> tuple[list[Question], dict[int, dict]]:
    """similar 模式：基于源题的向量相似题召回，不足时用规则 + 随机补齐。

    返回: (questions_list, metadata_dict)
        metadata_dict: {question_id: {"recommend_reason": ..., "recommend_score": ..., "strategy": ..., "similarity": ...}}
    """
    # TODO(V3): use_leitner 参数当前未使用。向量召回后应通过
    # question_review_service.get_due_question_ids() 做二次过滤，
    # 过滤掉 next_review_at > now 的题目，不足时用 Leitner fallback 补齐。
    metadata: dict[int, dict] = {}
    scope_ids = subject_ids if subject_ids is not None else await resolve_subject_ids(db, subject_code)

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
    smart_strategy = normalize_smart_strategy(smart_strategy)
    scope_ids = subject_ids if subject_ids is not None else await resolve_subject_ids(db, subject_code)

    # V4: 综合打分策略
    if smart_strategy == "scored":
        try:
            scored_qs, scored_meta = await get_smart_scored_questions(
                db=db, user_id=user_id, subject_code=subject_code, count=count,
                exclude_answered=exclude_answered,
                no_repeat_days=no_repeat_days,
                request_id=request_id,
                subject_ids=scope_ids,
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
                subject_ids=scope_ids,
            )
            merged_qs, merged_meta = merge_recommendation_results(
                scored_qs, scored_meta, fallback_qs, fallback_meta, count=count,
            )
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
                # 获取题目。知识路径服务本身会尽量排除已做题，但最终刷题
                # 接口仍需在当前 PracticeRecord 快照上强制执行 repeat-window，
                # 防止缓存/并发写入导致已刚做过的题再次下发。
                path_candidate_ids = list(dict.fromkeys(
                    int(qid) for qid in path_qids if qid is not None
                ))
                path_conditions = [
                    Question.id.in_(path_candidate_ids),
                    Question.is_active,
                    Question.subject_id.in_(scope_ids),
                    _practice_revision_scope_condition(scope_ids),
                ]
                path_excluded_sub = _build_excluded_question_subquery(
                    user_id=user_id,
                    exclude_answered=exclude_answered,
                    no_repeat_days=no_repeat_days,
                )
                if path_excluded_sub is not None:
                    path_conditions.append(Question.id.notin_(path_excluded_sub))
                q_result = await db.execute(
                    select(Question)
                    .where(and_(*path_conditions))
                    .options(selectinload(Question.subject_ref))
                )
                q_map = {q.id: q for q in q_result.scalars().all()}
                # 保持 path_qids 的顺序（按优先级排序）
                # 先过滤再截断，避免前 count 个推荐中恰有近期已做题时，
                # 后面的合法 path 候选明明存在却被无谓丢掉。
                path_questions = [
                    q_map[qid] for qid in path_candidate_ids if qid in q_map
                ][:count]

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
                    use_leitner=use_leitner,
                    exclude_ids={q.id for q in path_questions},
                    subject_ids=scope_ids,
                )
                path_questions, metadata = merge_recommendation_results(
                    path_questions, metadata, fallback_questions, fallback_meta, count=count,
                )
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
            scope_ids,
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
            use_leitner=use_leitner,
            subject_ids=scope_ids,
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
                Question.subject_id.in_(scope_ids),
                _practice_revision_scope_condition(scope_ids),
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
    exclude_ids = exclude_ids or set()
    metadata: dict[int, dict] = {}
    scope_ids = subject_ids if subject_ids is not None else await resolve_subject_ids(db, subject_code)

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
            scope_ids,
        )

    if not weak_kps:
        # 退化为随机
        # ``exclude_ids`` is used when this helper supplements path/scored
        # results. Over-fetch by exactly that many so filtering an already
        # selected question does not unnecessarily reduce the final batch size.
        fallback_fetch_count = count + len(exclude_ids)
        questions = await get_practice_questions(
            db=db, user_id=user_id, subject_code=subject_code, count=fallback_fetch_count,
            mode="random", exclude_answered=exclude_answered,
            no_repeat_days=no_repeat_days,
            use_leitner=use_leitner,
            subject_ids=scope_ids,
        )
        for q in questions:
            if q.id not in exclude_ids:
                metadata[q.id] = {
                    "recommend_reason": "随机推荐（薄弱知识点数据不足）",
                    "recommend_score": None,
                    "strategy": "random_fallback",
                    "similarity": None,
                }
        return [q for q in questions if q.id not in exclude_ids][:count], metadata

    kp_names = [kp["name"] for kp in weak_kps[:5]]
    query_text = (
        f"科目：{subject_code}。请推荐这些薄弱知识点的练习题："
        f"{'、'.join(kp_names)}。要求题目适合查漏补缺和变式训练。"
    )

    result_questions: list[Question] = []
    vector_excluded_sub = _build_excluded_question_subquery(
        user_id=user_id,
        exclude_answered=exclude_answered,
        no_repeat_days=no_repeat_days,
    )
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
                vector_conditions = [
                    Question.id.in_(rec_ids),
                    Question.is_active,
                    Question.subject_id.in_(scope_ids),
                    _practice_revision_scope_condition(scope_ids),
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
    recent_q_sub = select(PracticeRecord.question_id).where(
        PracticeRecord.user_id == user_id,
        PracticeRecord.answered_at >= recent_cutoff,
    ).distinct()
    conditions.append(Question.id.notin_(recent_q_sub))

    candidate_total = int((await db.scalar(
        select(func.count()).select_from(
            select(Question.id).where(and_(*conditions)).subquery()
        )
    )) or 0)
    cand_query = (
        select(Question)
        .where(and_(*conditions))
        .options(selectinload(Question.subject_ref))
    )
    cand_query = _random_sample_query(
        cand_query, candidate_total, min(candidate_limit, candidate_total), Question.id
    )
    cand_result = await db.execute(cand_query)
    candidates: list[Question] = list(cand_result.scalars().all())
    active_candidate_conditions = conditions

    # 24h 过滤后不足 → 放宽（降级 1）
    if len(candidates) < count:
        fallback_level = 1
        relaxed = [c for c in conditions if c is not conditions[-1]]
        active_candidate_conditions = relaxed
        relaxed_total = int((await db.scalar(
            select(func.count()).select_from(
                select(Question.id).where(and_(*relaxed)).subquery()
            )
        )) or 0)
        relaxed_query = (
            select(Question)
            .where(and_(*relaxed))
            .options(selectinload(Question.subject_ref))
        )
        relaxed_query = _random_sample_query(
            relaxed_query, relaxed_total, min(candidate_limit, relaxed_total), Question.id
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
    knowledge_states = list(ks_result.scalars().all())
    kp_mastery: dict[int, tuple] = {
        s.knowledge_point_id: (s.mastery_score, s.confidence)
        for s in knowledge_states
    }
    kp_observations: dict[int, tuple[int, int]] = {
        s.knowledge_point_id: (s.attempt_count, s.wrong_count)
        for s in knowledge_states
    }

    graph_context: dict = {
        "blocked_targets": {},
        "prerequisite_candidates": {},
        "prerequisites_by_target": {},
    }
    try:
        from app.core.config import settings as _settings
        if _settings.ADAPTIVE_LEARNING_ENABLED and _settings.ADAPTIVE_PATH_ENABLED:
            # 图谱扩展属于可选增强能力。使用 SAVEPOINT 隔离其数据库错误，
            # 避免 PostgreSQL 在任一图谱查询失败后把整个请求事务标记为 aborted。
            async with db.begin_nested():
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
        select(QuestionVersionKnowledgePoint.knowledge_point_id)
        .join(
            PracticeRecord,
            PracticeRecord.question_version_id == QuestionVersionKnowledgePoint.question_version_id,
        )
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
            kp_observations=kp_observations,
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
                kp_mastery=kp_mastery,
                kp_observations=kp_observations,
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
                    kp_mastery=kp_mastery,
                    kp_observations=kp_observations,
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
            _practice_revision_scope_condition(scope_ids),
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
            _practice_revision_scope_condition(scope_ids),
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
        select(
            PracticeRecord.is_correct,
            func.coalesce(SyllabusKnowledgePoint.name_snapshot, KnowledgePoint.name),
        )
        .join(
            QuestionVersionKnowledgePoint,
            QuestionVersionKnowledgePoint.question_version_id == PracticeRecord.question_version_id,
        )
        .join(KnowledgePoint, KnowledgePoint.id == QuestionVersionKnowledgePoint.knowledge_point_id)
        .outerjoin(
            SyllabusKnowledgePoint,
            SyllabusKnowledgePoint.id == QuestionVersionKnowledgePoint.syllabus_knowledge_point_id,
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
                weak.append({
                    "name": kp_name,
                    "total": total,
                    "correct": correct,
                    "accuracy": round(accuracy, 4),
                })

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


def _practice_submission_fingerprint(
    *,
    answers: list[dict],
    skipped_question_ids: list[int],
    session_meta: dict,
    batch_token: str,
) -> str:
    """Hash the exact immutable submission represented by one request_id."""
    normalized_answers = []
    for answer in answers:
        normalized_answers.append({
            "question_id": int(answer.get("question_id")),
            "user_answer": str(answer.get("user_answer", answer.get("answer", "")) or "").strip(),
            "used_time": (
                None if answer.get("used_time") is None else int(answer.get("used_time"))
            ),
            "request_id": _normalize_practice_request_id(answer.get("request_id")),
        })
    normalized_answers.sort(key=lambda item: item["question_id"])
    payload = {
        "v": 3,
        "answers": normalized_answers,
        "skipped_question_ids": sorted(int(qid) for qid in skipped_question_ids),
        "session": {
            "request_id": _normalize_practice_request_id(session_meta.get("request_id")),
            "subject_id": int(session_meta.get("subject_id")),
            "mode": str(session_meta.get("mode") or "random"),
            "started_at": str(session_meta.get("started_at") or ""),
            "finished_at": str(session_meta.get("finished_at") or ""),
            "duration_sec": int(session_meta.get("duration_sec") or 0),
            "question_count": int(session_meta.get("question_count") or 0),
            "answered_count": int(session_meta.get("answered_count") or 0),
        },
        "batch_token": str(batch_token),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    if not batch_token:
        raise PracticeBatchTokenError("batch_token 不能为空，请重新获取题目")
    if not session_meta:
        raise PracticeBatchTokenError("session 不能为空，请重新获取题目")
    if skipped_question_ids is None:
        raise PracticeBatchTokenError("skipped_question_ids 必须显式提交")
    if len(answers) > PRACTICE_BATCH_MAX_QUESTIONS:
        raise ValueError(f"answers 最多允许 {PRACTICE_BATCH_MAX_QUESTIONS} 题")
    if len(skipped_question_ids) > PRACTICE_BATCH_MAX_QUESTIONS:
        raise ValueError(f"skipped_question_ids 最多允许 {PRACTICE_BATCH_MAX_QUESTIONS} 题")

    answer_question_ids = [int(a["question_id"]) for a in answers]
    if len(answer_question_ids) != len(set(answer_question_ids)):
        raise ValueError("answers 中存在重复 question_id")
    skipped_ids = [int(qid) for qid in skipped_question_ids]
    if len(skipped_ids) != len(set(skipped_ids)):
        raise ValueError("skipped_question_ids 中存在重复 question_id")
    overlap = set(answer_question_ids) & set(skipped_ids)
    if overlap:
        raise ValueError(f"题目不能同时提交答案并标记跳过: {sorted(overlap)}")
    all_question_ids = answer_question_ids + skipped_ids
    if not all_question_ids:
        raise ValueError("practice batch 至少需要包含 1 道题")
    if len(all_question_ids) > PRACTICE_BATCH_MAX_QUESTIONS:
        raise ValueError(f"单次练习最多允许 {PRACTICE_BATCH_MAX_QUESTIONS} 题")

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

    evaluated_answers: list[tuple[object, bool, str, int | None]] = []
    answer_request_ids: dict[int, str | None] = {}
    total_correct = 0
    total_wrong = 0
    for answer in answers:
        q = questions[int(answer["question_id"])]
        user_answer = str(answer.get("user_answer", answer.get("answer", "")) or "").strip()
        if not user_answer:
            # Empty strings used to be graded as a normal wrong answer, which lets
            # stale/malformed clients inflate answered_count and wrong-question
            # statistics.  Unattempted questions belong in skipped_question_ids.
            raise ValueError(
                f"question_id={int(q.id)} 的 user_answer 不能为空；未作答题请放入 skipped_question_ids"
            )
        used_time = _normalize_answer_used_time(answer.get("used_time"))
        answer_request_ids[int(q.id)] = _normalize_practice_request_id(answer.get("request_id"))
        slot_ids = extract_multi_blank_slot_ids(
            getattr(q, "content", None),
            getattr(q, "options", None),
        )
        is_correct = is_answer_correct(
            user_answer,
            q.answer or "",
            q.question_type or "",
            slot_ids=slot_ids,
        )
        evaluated_answers.append((q, is_correct, user_answer, used_time))
        if is_correct:
            total_correct += 1
        else:
            total_wrong += 1
    skipped_questions = [questions[qid] for qid in skipped_ids]

    session_values = _normalize_practice_session(
        session_meta,
        user_id=user_id,
        answered_count=len(evaluated_answers),
        total_correct=total_correct,
        total_wrong=total_wrong,
    )
    if session_values.get("request_id") != request_id:
        raise ValueError("session.request_id 归一化结果不一致")
    if int(session_values.get("question_count") or 0) != len(all_question_ids):
        raise ValueError("session.question_count 与本次批次题数不一致")

    # The batch token snapshots subject/mode semantics at issue time. Do not
    # re-resolve today's mutable subject tree during submit.
    if int(session_values.get("subject_id") or 0) != int(batch_payload.get("sid") or 0):
        raise PracticeBatchTokenError("session.subject_id 与练习批次不一致")
    if str(session_values.get("mode")) != str(batch_payload.get("mode")):
        raise PracticeBatchTokenError("session.mode 与练习批次不一致")

    duration_sec = int(session_values.get("duration_sec") or 0)
    answered_used_times = [
        int(used_time)
        for _q, _correct, _answer, used_time in evaluated_answers
        if used_time is not None
    ]
    max_allowed_answer_time = duration_sec + PRACTICE_ANSWER_DURATION_TOLERANCE_SEC
    if any(used_time > max_allowed_answer_time for used_time in answered_used_times):
        raise ValueError("answers.used_time 不得明显超过本次练习总时长")
    if sum(answered_used_times) > max_allowed_answer_time:
        raise ValueError("answers.used_time 合计不得明显超过本次练习总时长")

    session_obj = PracticeSession(
        **session_values,
        submission_payload_hash=payload_hash,
    )
    try:
        async with db.begin_nested():
            db.add(session_obj)
            await db.flush()
    except IntegrityError as exc:
        if not _is_unique_violation(exc):
            raise
        winner = await db.scalar(
            select(PracticeSession).where(
                PracticeSession.user_id == user_id,
                PracticeSession.request_id == request_id,
            )
        )
        if winner is None:
            raise
        return _replay_committed_submission(winner, payload_hash)

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
            from app.services import error_diagnosis_service

            diagnosis = await error_diagnosis_service.record_error_event(
                db,
                user_id=user_id,
                wrong_question_id=int(wrong.id),
                question_id=int(q.id),
                question_version_id=int(q.question_version_id),
                practice_record_id=int(record.id),
                source_context="practice",
                user_answer=record.user_answer,
                occurred_at=record.answered_at or now,
                queue_ai=False,
            )
            prewarm_wrong_questions.append(wrong)
            wrong_question_ids[int(q.id)] = int(wrong.id)
            setattr(record, "_error_diagnosis_payload", error_diagnosis_service.serialize_diagnosis(diagnosis))
        await _create_answer_projection_outbox(
            db,
            practice_record_id=int(record.id),
            request_id=answer_request_ids.get(int(q.id)),
        )

    revision_kps = await load_revision_kp_names(db, issued_revisions.values())
    response_by_question: dict[int, dict] = {}
    for record, q, is_correct, _user_answer, _used_time in records:
        response_by_question[int(q.id)] = {
            "record_id": int(record.id),
            "question_id": int(q.id),
            "is_correct": bool(is_correct),
            "correct_answer": q.answer,
            "status": "correct" if is_correct else "wrong",
            "analysis": q.analysis,
            "knowledge_points": revision_kps.get(int(q.question_version_id), []),
            "is_wrong_added": int(q.id) in wrong_question_ids,
            "wrong_question_id": wrong_question_ids.get(int(q.id)),
            "error_diagnosis": getattr(record, "_error_diagnosis_payload", None),
        }
    for q in skipped_questions:
        response_by_question[int(q.id)] = {
            "question_id": int(q.id),
            "is_correct": False,
            "correct_answer": q.answer,
            "status": "skipped",
            "analysis": q.analysis,
            "knowledge_points": revision_kps.get(int(q.question_version_id), []),
            "is_wrong_added": False,
            "wrong_question_id": None,
        }

    response_payload = jsonable_encoder({
        "results": [response_by_question[qid] for qid in issued_order],
        "total_correct": total_correct,
        "total_wrong": total_wrong,
        "total_skipped": len(skipped_questions),
    })
    # submission_response is a SQL JSON column and is also the source used for
    # idempotent replay.  Nested diagnostics may contain datetime values, so
    # normalize the entire payload once before both persistence and response.
    session_obj.submission_response = response_payload
    await db.commit()

    if prewarm_wrong_questions:
        try:
            from app.services.ai_prewarm_worker import (
                build_prewarm_revision,
                enqueue_prewarm,
            )

            for wrong in prewarm_wrong_questions:
                revision = build_prewarm_revision(
                    review_count=wrong.review_count,
                    wrong_answer=wrong.wrong_answer,
                )
                await enqueue_prewarm(wrong.id, user_id, revision=revision)
        except Exception:
            logger.warning("AI prewarm enqueue failed after practice batch", exc_info=True)

    return response_payload


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

    # Daily stats — bucket UTC DB timestamps by China calendar day.
    today = shanghai_today()
    since = shanghai_date_utc_range(today - timedelta(days=days - 1))[0]
    day_expr = await _china_date_expr(db, PracticeRecord.answered_at)
    daily_result = await db.execute(
        select(
            day_expr,
            func.count(PracticeRecord.id),
            func.coalesce(
                func.sum(case((PracticeRecord.is_correct, 1), else_=0)), 0
            ),
        )
        .where(
            PracticeRecord.user_id == user_id,
            PracticeRecord.answered_at >= since,
        )
        .group_by(day_expr)
        .order_by(day_expr)
    )
    daily_map = {str(r[0]): {"answered": r[1], "correct": r[2]} for r in daily_result.all()}

    daily_stats = []
    for i in range(days):
        d = (today - timedelta(days=days - 1 - i)).isoformat()
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
    dates = {date.fromisoformat(row[0]) if isinstance(row[0], str) else row[0] for row in result.all()}

    streak = 0
    for i in range(365):
        d = today - timedelta(days=i)
        if d in dates:
            streak += 1
        else:
            break
    return streak

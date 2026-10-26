"""Pure validation and normalization helpers for practice requests.

Extracted from practice_service.py to keep the main service focused on
DB orchestration. These functions take plain dicts/primitives and return
plain dicts/primitives with no side effects.
"""

from __future__ import annotations

import builtins as _builtins
import logging
from datetime import datetime

from app.core.subject_scope import EXAM408_CORE_CODES
from app.core.time_utils import normalize_to_naive_utc
from app.services.practice import session_normalization as _session

logger = logging.getLogger(__name__)

PRACTICE_SESSION_MAX_DURATION_SEC = 6 * 60 * 60
PRACTICE_ANSWER_MAX_USED_TIME_SEC = PRACTICE_SESSION_MAX_DURATION_SEC
PRACTICE_ALLOWED_MODES = {"random", "smart", "similar", "sequential"}

_PRACTICE_DURATION_ROUNDING_TOLERANCE = 2

_TRUE_FALSE_TRUE = {"a", "true", "对", "是", "正确", "t", "yes", "1"}
_TRUE_FALSE_FALSE = {"b", "false", "错", "否", "错误", "f", "no", "0"}

# High-confidence, discipline-specific anchors used only as a safety net for
# already-published 408 questions whose subject_id was historically assigned to
# the wrong discipline. The guard is intentionally conservative.
_408_CONTENT_ANCHORS: dict[str, tuple[str, ...]] = {
    "data_structure": (
        "二叉树",
        "二叉排序树",
        "平衡二叉树",
        "红黑树",
        "b树",
        "b+树",
        "线索二叉树",
        "哈夫曼树",
        "链表",
        "顺序表",
        "邻接表",
        "邻接矩阵",
        "最小生成树",
        "拓扑排序",
        "关键路径",
        "散列表",
        "哈希表",
        "散列",
        "二分查找",
        "折半查找",
        "快速排序",
        "归并排序",
        "堆排序",
        "希尔排序",
        "插入排序",
        "冒泡排序",
        "深度优先",
        "广度优先",
        "dfs",
        "bfs",
    ),
    "operating_system": (
        "进程",
        "线程",
        "死锁",
        "信号量",
        "临界区",
        "管程",
        "银行家算法",
        "页面置换",
        "缺页",
        "页表",
        "页框",
        "页号",
        "虚拟内存",
        "虚拟页",
        "分段存储",
        "段表",
        "段号",
        "段内地址",
        "工作集",
        "驻留集",
        "抖动",
        "文件系统",
        "磁盘调度",
        "时间片",
        "pv操作",
    ),
    "computer_organization": (
        "cpu",
        "alu",
        "cache",
        "高速缓存",
        "主存",
        "存储器层次",
        "指令周期",
        "指令字",
        "微指令",
        "微程序",
        "流水线",
        "控制器",
        "运算器",
        "总线",
        "dma",
        "中断向量",
        "寻址方式",
        "补码",
        "原码",
        "浮点数",
        "ieee754",
        "ieee 754",
        "机器字长",
        "存储字长",
    ),
    "computer_network": (
        "tcp",
        "udp",
        "ipv4",
        "ipv6",
        "ip地址",
        "子网掩码",
        "路由表",
        "路由协议",
        "ospf",
        "rip",
        "bgp",
        "arp",
        "dns",
        "http",
        "以太网",
        "csma",
        "mac地址",
        "数据链路层",
        "网络层",
        "传输层",
        "应用层",
        "拥塞窗口",
        "三次握手",
        "四次挥手",
    ),
}


def normalize_answer_used_time(value) -> int | None:
    """Validate and normalize the per-answer used_time field."""
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


def parse_session_datetime(value) -> datetime | None:
    """Parse an ISO-8601 datetime (may carry Z / +00:00) into naive UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            logger.warning(
                "practice session datetime 缺少时区信息，按 UTC 处理: %s", value
            )
        return normalize_to_naive_utc(value)
    text_val = str(value).strip()
    if not text_val:
        return None
    try:
        parsed = datetime.fromisoformat(text_val.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        logger.warning(
            "practice session datetime 缺少时区信息，按 UTC 处理（若为北京时间将偏移 8h）: %s",
            text_val,
        )
    return normalize_to_naive_utc(parsed)


def normalize_practice_request_id(value) -> str | None:
    """Validate and normalize the request_id string."""
    request_id = str(value or "").strip() or None
    if request_id is not None and len(request_id) > 128:
        raise ValueError("request_id 长度不得超过 128")
    return request_id


def _normalization_port(name: str):
    """Resolve moved lookups against the historical module at each use."""
    namespace = globals()
    if name in namespace:
        return namespace[name]
    builtin_namespace = vars(_builtins)
    if name in builtin_namespace:
        return builtin_namespace[name]
    raise NameError(f"name '{name}' is not defined", name=name)


def normalize_practice_session(
    session_meta: dict,
    *,
    user_id: int,
    answered_count: int,
    total_correct: int,
    total_wrong: int,
) -> dict:
    """Validate the mandatory server-issued practice session metadata."""
    return _session.normalize_session_values(
        session_meta,
        user_id=user_id,
        answered_count=answered_count,
        total_correct=total_correct,
        total_wrong=total_wrong,
        ports=_normalization_port,
    )


def normalize_true_false_answer(value: str) -> str:
    """Normalize a true/false answer string to A (true) or B (false)."""
    v = str(value or "").strip().lower()
    if v in _TRUE_FALSE_TRUE:
        return "A"
    if v in _TRUE_FALSE_FALSE:
        return "B"
    return v.upper()


def canonical_408_subject(code: str | None, name: str | None = None) -> str | None:
    """Return the canonical 408 discipline code, or None if not recognized.

    Runtime subject identity is code-only. ``name`` is intentionally ignored so
    a stale/incorrect code cannot be masked by a matching display name.
    """
    value = str(code or "").strip().lower()
    return value if value in EXAM408_CORE_CODES else None


def question_stem_for_subject_guard(content: dict | None) -> str:
    """Extract the question stem text for subject-mismatch guard."""
    if not isinstance(content, dict):
        return ""
    value = content.get("text") or content.get("stem") or ""
    return str(value).strip().lower()


def detect_408_subject_mismatch(
    *,
    subject_code: str | None,
    subject_name: str | None,
    stem: str,
) -> tuple[str | None, dict[str, int]]:
    """Return an inferred conflicting 408 discipline only at high confidence."""
    expected = canonical_408_subject(subject_code, subject_name)
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

    if (
        best_subject != expected
        and best_score >= 2
        and best_score - expected_score >= 2
        and best_score - second_score >= 1
    ):
        return best_subject, scores
    return None, scores

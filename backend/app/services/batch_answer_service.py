"""审核池"快速补充答案"服务——答案串解析、标准化、预览校验、事务写入。"""

import hashlib
import json
import logging
import re
import secrets
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal
from app.core.cache import cache
from app.core.time_utils import serialize_utc_datetime, utcnow
from app.features.question_type import (
    QT_MULTIPLE_CHOICE,
    QT_SINGLE_CHOICE,
    QT_TRUE_FALSE,
    normalize_question_type,
)
from app.models.question_import import QuestionImport
from app.services.admin_audit_service import write_admin_audit

logger = logging.getLogger(__name__)

# ── 稳定业务错误码 ──
BATCH_NOT_EDITABLE = "BATCH_NOT_EDITABLE"
TOO_MANY_ANSWERS = "TOO_MANY_ANSWERS"
NO_ANSWERS_PARSED = "NO_ANSWERS_PARSED"
ORDER_INDEX_MISSING = "ORDER_INDEX_MISSING"
ORDER_INDEX_DUPLICATED = "ORDER_INDEX_DUPLICATED"
INVALID_ANSWER_TOKEN = "INVALID_ANSWER_TOKEN"
PREVIEW_EXPIRED = "PREVIEW_EXPIRED"
PREVIEW_STALE = "PREVIEW_STALE"
PREVIEW_ALREADY_APPLIED = "PREVIEW_ALREADY_APPLIED"
NO_WRITABLE_ITEMS = "NO_WRITABLE_ITEMS"


class BusinessError(Exception):
    """业务异常，携带稳定错误码。"""

    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


# ── 单选题合法选项 ──
_SINGLE_CHOICE_OPTIONS = frozenset({"A", "B", "C", "D"})

# ── 判断题归一化 ──
_TRUE_VALUES = frozenset({"T", "TRUE", "正确", "对", "√", "1"})
_FALSE_VALUES = frozenset({"F", "FALSE", "错误", "错", "×", "0"})

# ── 支持批量答案补录的题型 ──
_SUPPORTED_TYPES = frozenset({"single_choice", "multiple_choice", "true_false"})

# ── Token 缓存前缀与过期时间 ──
_PREVIEW_TOKEN_PREFIX = "batch_answer:preview:"
_PREVIEW_TOKEN_TTL = 900  # 15 分钟

# ── operation_id 去重缓存 ──
_OPID_PREFIX = "batch_answer:opid:"
_OPID_TTL = 3600  # 1 小时


def _is_answer_empty(val: str | None) -> bool:
    """统一空答案判定。NULL/空字符串/仅空白字符视为空。
    "未知"/"待定"/"暂无" 等非空文本不视为空。
    """
    if val is None:
        return True
    return val.strip() == ""


class AnswerParseMode(StrEnum):
    """答案输入解析模式。"""

    MULTI_CHOICE_DELIMITED = "multi_choice_delimited"  # 多选题显式分隔格式
    SINGLE_CHOICE_PLAIN = "single_choice_plain"  # 连续的单选题答案串


class PreviewStatus(StrEnum):
    """预览中每道题的处理状态。"""

    WILL_UPDATE = "will_update"  # 将写入
    SKIP_EXISTING = "skip_existing"  # 已有答案，跳过
    SKIP_EXISTING_SAME = "skip_existing_same"  # 输入与已有答案相同，跳过
    INVALID_ANSWER = "invalid_answer"  # 非法答案
    UNSUPPORTED_TYPE = "unsupported_type"  # 题型不支持
    ORDER_ANOMALY = "order_anomaly"  # 题目顺序异常

    def __str__(self) -> str:
        return self.value


@dataclass
class PreviewItem:
    """单道题的预览结果。"""

    import_id: int
    source_order_index: int | None
    source_question_no: str | None
    stem_excerpt: str  # 题干摘要（前 120 字）
    question_type: str | None
    original_answer: str | None  # 数据库中已有答案
    input_answer: str | None  # 用户输入的原始答案
    normalized_answer: str | None  # 标准化后的答案
    status: PreviewStatus
    status_message: str = ""
    will_update: bool = False
    validation_errors: list[str] = field(default_factory=list)


@dataclass
class PreviewSummary:
    """预览汇总统计。"""

    batch_total: int = 0
    parsed_answer_count: int = 0
    target_question_count: int = 0
    remaining_question_count: int = 0
    writable_count: int = 0
    skipped_existing_count: int = 0
    skipped_existing_same_count: int = 0
    unsupported_count: int = 0
    invalid_count: int = 0
    warning_count: int = 0
    order_anomaly_count: int = 0


# ══════════════════════════════════════════════════════════
# 步骤 1：答案串解析
# ══════════════════════════════════════════════════════════


def parse_answer_string(raw_text: str) -> list[str]:
    """将用户输入的答案串解析为单个答案列表。

    支持格式：
    - "abcda" → ["A", "B", "C", "D", "A"]
    - "A,B,C,D,A" → ["A", "B", "C", "D", "A"]
    - "A B C D A" → ["A", "B", "C", "D", "A"]
    - "A|B|C|D|A" → ["A", "B", "C", "D", "A"]
    - "A,AC,B,BCD,D" → ["A", "AC", "B", "BCD", "D"]  （多选题分隔格式）
    """
    text = raw_text.strip() if raw_text else ""

    if not text:
        return []

    # 检测是否包含显式分隔符（逗号、中文逗号、竖线、分号、空格、换行）
    separator_pattern = re.compile(r"[\s,，;；、|]+")
    if separator_pattern.search(text):
        return _split_by_separator(text, separator_pattern)

    # 无分隔符：单字母连续串模式（仅适用于 A-D 单选答案）
    # 去掉所有空白、换行后再匹配
    compact = re.sub(r"\s+", "", text).upper()
    if re.fullmatch(r"[A-D]+", compact):
        return list(compact)

    # 多行模式：每行一个答案
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if lines:
        return lines

    return [text.upper()]


def _split_by_separator(text: str, pattern: re.Pattern) -> list[str]:
    """按分隔符拆分答案串。"""
    parts = pattern.split(text)
    return [p.strip().upper() for p in parts if p.strip()]


# ══════════════════════════════════════════════════════════
# 步骤 2：答案标准化
# ══════════════════════════════════════════════════════════


def normalize_single_answer(
    answer: str, question_type: str | None, parsed_options: dict | None = None
) -> tuple[str | None, list[str]]:
    """标准化单个答案，返回 (normalized, errors)。

    对于 single_choice：要求单个字母 A-D
    对于 multi_choice：去重、按字母排序
    对于 true_false/judge：归一化为 T/F
    其他题型：不处理
    """
    errors: list[str] = []
    normalized = answer.strip().upper()

    if not normalized:
        return None, ["答案为空"]

    # 先规范化题型（兼容别名）
    qt, _warnings = normalize_question_type(question_type)
    if qt is None:
        return None, [f"不支持的题型: {question_type}"]

    # ── 判断题 ──
    if qt == QT_TRUE_FALSE:
        if normalized in _TRUE_VALUES:
            return "T", []
        if normalized in _FALSE_VALUES:
            return "F", []
        errors.append(f"无法识别的判断题答案: {answer}")
        return None, errors

    # ── 单选题 ──
    if qt == QT_SINGLE_CHOICE:
        return _normalize_single_choice(normalized, parsed_options, errors)

    # ── 多选题 ──
    if qt == QT_MULTIPLE_CHOICE:
        return _normalize_multi_choice(normalized, parsed_options, errors)

    # ── 不支持题型 ──
    return None, [f"不支持的题型: {question_type}"]


def _normalize_single_choice(
    normalized: str, parsed_options: dict | None, errors: list[str]
) -> tuple[str | None, list[str]]:
    """标准化单选题答案。"""
    # 去除标点符号和空格
    clean = re.sub(r"[.．、，,]", "", normalized)

    if len(clean) != 1 or not clean.isalpha():
        errors.append(f"单选题答案格式错误: {normalized}（应为单个字母）")
        return None, errors

    letter = clean.upper()
    valid_options = _get_valid_option_keys(parsed_options)

    if letter not in valid_options:
        errors.append(f"答案 {letter} 不在题目选项范围内（{sorted(valid_options)}）")
        return None, errors

    return letter, []


def _normalize_multi_choice(
    normalized: str, parsed_options: dict | None, errors: list[str]
) -> tuple[str | None, list[str]]:
    """标准化多选题答案（去重、排序）。"""
    # 去除无用字符，提取字母
    letters = re.findall(r"[A-Z]", normalized)
    if not letters:
        errors.append(f"多选题答案格式错误: {normalized}")
        return None, errors

    # 去重 + 排序
    unique = sorted(set(letters))
    result = "".join(unique)

    # 检查是否超出选项范围
    valid_options = _get_valid_option_keys(parsed_options)
    invalid = [k for k in unique if k not in valid_options]
    if invalid:
        errors.append(
            f"答案 {''.join(invalid)} 超出题目选项范围（{sorted(valid_options)}）"
        )
        return None, errors

    return result, []


def _get_valid_option_keys(parsed_options: dict | None) -> set[str]:
    """从 parsed_options 中提取合法选项字母。"""
    if not parsed_options:
        return _SINGLE_CHOICE_OPTIONS

    if isinstance(parsed_options, list):
        keys = {
            str(o.get("key", "")).upper()
            for o in parsed_options
            if isinstance(o, dict) and o.get("key")
        }
    elif isinstance(parsed_options, dict):
        keys = set(parsed_options.keys())
    else:
        return _SINGLE_CHOICE_OPTIONS

    return (
        {k for k in keys if re.match(r"^[A-Z]$", k)} if keys else _SINGLE_CHOICE_OPTIONS
    )


# ══════════════════════════════════════════════════════════
# 步骤 3：批次题目锁定与排序
# ══════════════════════════════════════════════════════════


async def _check_batch_editable(db: AsyncSession, batch_id: str) -> None:
    """检查批次内所有题目是否均为可编辑状态（status == pending）。"""
    result = await db.execute(
        select(func.count())
        .select_from(QuestionImport)
        .where(QuestionImport.batch_id == batch_id, QuestionImport.status != "pending")
    )
    non_pending = result.scalar() or 0
    if non_pending > 0:
        raise BusinessError(
            BATCH_NOT_EDITABLE,
            f"批次含有 {non_pending} 条已处理记录，不可编辑",
        )


async def _lock_batch_questions(
    db: AsyncSession, batch_id: str
) -> list[QuestionImport]:
    """按 source_order_index 升序获取批次内所有题目。

    校验：
    - source_order_index 必须存在（不允许为空）
    - source_order_index 必须唯一（不允许重复）
    - 存在不连续但唯一的索引时允许继续
    """
    result = await db.execute(
        select(QuestionImport)
        .where(QuestionImport.batch_id == batch_id)
        .order_by(
            QuestionImport.source_order_index.asc().nullslast(), QuestionImport.id.asc()
        )
    )
    questions = list(result.scalars().all())

    if not questions:
        raise ValueError("导入批次不存在")

    # 检查 source_order_index 是否为空
    null_indices = [q.id for q in questions if q.source_order_index is None]
    if null_indices:
        raise BusinessError(
            ORDER_INDEX_MISSING,
            f"{len(null_indices)} 道题缺少 source_order_index（ID: {null_indices}）",
        )

    # 检查 source_order_index 是否重复
    seen: dict[int, list[int]] = {}
    for q in questions:
        seen.setdefault(q.source_order_index, []).append(q.id)
    duplicate_indices = {idx: ids for idx, ids in seen.items() if len(ids) > 1}
    if duplicate_indices:
        raise BusinessError(
            ORDER_INDEX_DUPLICATED,
            f"存在重复的 source_order_index: {duplicate_indices}",
        )

    return questions


# ══════════════════════════════════════════════════════════
# 步骤 4：预览生成
# ══════════════════════════════════════════════════════════


def _stem_excerpt(question: QuestionImport) -> str:
    """提取题干摘要（前 120 字）。"""
    text = ""
    if question.raw_text_preview:
        text = question.raw_text_preview
    elif question.parsed_content and isinstance(question.parsed_content, dict):
        text = (
            question.parsed_content.get("stem")
            or question.parsed_content.get("text")
            or question.parsed_content.get("question")
            or ""
        )
    elif question.raw_data and isinstance(question.raw_data, dict):
        text = (
            question.raw_data.get("stem")
            or question.raw_data.get("text")
            or question.raw_data.get("raw_text")
            or ""
        )

    text = re.sub(r"\s+", " ", str(text)).strip()
    return text[:120] + ("…" if len(text) > 120 else "")


def _options_hash(question: QuestionImport) -> str:
    """计算题目选项的哈希值，用于 apply 时的一致性校验。"""
    opts = question.parsed_options
    if not opts:
        return ""
    return hashlib.sha256(json.dumps(opts, sort_keys=True).encode()).hexdigest()[:16]


def _generate_operation_id() -> str:
    """生成全局唯一 operation_id。"""
    return hashlib.sha256(secrets.token_hex(16).encode()).hexdigest()[:24]


async def _get_batch_pending_count(db: AsyncSession, batch_id: str) -> int:
    """获取批次内 pending 状态的题目数量。"""
    result = await db.execute(
        select(func.count())
        .select_from(QuestionImport)
        .where(QuestionImport.batch_id == batch_id, QuestionImport.status == "pending")
    )
    return result.scalar() or 0


async def _get_answer_stats(db: AsyncSession, batch_id: str) -> dict:
    """获取批次答案相关统计。"""
    total = await db.execute(
        select(func.count())
        .select_from(QuestionImport)
        .where(QuestionImport.batch_id == batch_id)
    )
    total_count = total.scalar() or 0

    missing = await db.execute(
        select(func.count())
        .select_from(QuestionImport)
        .where(
            QuestionImport.batch_id == batch_id,
            func.coalesce(QuestionImport.parsed_answer, "") == "",
        )
    )
    missing_answer_count = missing.scalar() or 0

    manual_filled = await db.execute(
        select(func.count())
        .select_from(QuestionImport)
        .where(
            QuestionImport.batch_id == batch_id,
            QuestionImport.answer_source == "manual_batch_input",
        )
    )
    manual_filled_count = manual_filled.scalar() or 0

    pending = await _get_batch_pending_count(db, batch_id)

    return {
        "total_count": total_count,
        "pending_count": pending,
        "missing_answer_count": missing_answer_count,
        "manual_filled_count": manual_filled_count,
    }


async def generate_preview(
    db: AsyncSession,
    batch_id: str,
    raw_text: str,
    admin_id: int | None = None,
) -> dict:
    """生成答案解析预览，返回预览结果和 token。

    此步骤不写入数据库。
    """
    # 0. 校验批次可编辑性
    await _check_batch_editable(db, batch_id)

    # 1. 解析答案串
    parsed_answers = parse_answer_string(raw_text)
    if not parsed_answers:
        raise BusinessError(NO_ANSWERS_PARSED, "未识别到任何答案，请检查输入格式")

    # 2. 锁定题目（含 source_order_index 校验）
    questions = await _lock_batch_questions(db, batch_id)

    # 3. 检查答案数量不能超过题目总数
    if len(parsed_answers) > len(questions):
        raise BusinessError(
            TOO_MANY_ANSWERS,
            f"答案数量（{len(parsed_answers)}）超过当前批次题目总数（{len(questions)}），请检查输入",
        )

    # 4. 逐题映射
    items: list[dict] = []
    summary = PreviewSummary(
        batch_total=len(questions),
        parsed_answer_count=len(parsed_answers),
        target_question_count=len(parsed_answers),
        remaining_question_count=len(questions) - len(parsed_answers),
    )

    for i, question in enumerate(questions[: len(parsed_answers)]):
        input_ans = parsed_answers[i]
        qt = question.question_type

        # 检测是否支持该题型
        if qt and qt.lower() not in _SUPPORTED_TYPES:
            item = PreviewItem(
                import_id=question.id,
                source_order_index=question.source_order_index,
                source_question_no=question.source_question_no,
                stem_excerpt=_stem_excerpt(question),
                question_type=qt,
                original_answer=question.parsed_answer,
                input_answer=input_ans,
                normalized_answer=None,
                status=PreviewStatus.UNSUPPORTED_TYPE,
                status_message=f"题型不支持批量补录: {qt}",
                will_update=False,
            )
            items.append(asdict(item))
            summary.unsupported_count += 1
            continue

        # 已有答案检查（复用统一空答案判定）
        existing = (
            question.parsed_answer
            if not _is_answer_empty(question.parsed_answer)
            else ""
        )
        if existing:
            normalized_input, _ = normalize_single_answer(
                input_ans, qt, question.parsed_options
            )
            if normalized_input and normalized_input == existing.upper():
                item = PreviewItem(
                    import_id=question.id,
                    source_order_index=question.source_order_index,
                    source_question_no=question.source_question_no,
                    stem_excerpt=_stem_excerpt(question),
                    question_type=qt,
                    original_answer=existing,
                    input_answer=input_ans,
                    normalized_answer=existing.upper(),
                    status=PreviewStatus.SKIP_EXISTING_SAME,
                    status_message="输入答案与已有答案相同，跳过",
                    will_update=False,
                )
                items.append(asdict(item))
                summary.skipped_existing_same_count += 1
                summary.skipped_existing_count += 1
                continue
            else:
                item = PreviewItem(
                    import_id=question.id,
                    source_order_index=question.source_order_index,
                    source_question_no=question.source_question_no,
                    stem_excerpt=_stem_excerpt(question),
                    question_type=qt,
                    original_answer=existing,
                    input_answer=input_ans,
                    normalized_answer=input_ans,
                    status=PreviewStatus.SKIP_EXISTING,
                    status_message=f"已有答案 {existing}，跳过",
                    will_update=False,
                )
                items.append(asdict(item))
                summary.skipped_existing_count += 1
                continue

        # 标准化答案
        parsed_opts = question.parsed_options or {}
        normalized, errors = normalize_single_answer(input_ans, qt, parsed_opts)

        if errors:
            item = PreviewItem(
                import_id=question.id,
                source_order_index=question.source_order_index,
                source_question_no=question.source_question_no,
                stem_excerpt=_stem_excerpt(question),
                question_type=qt,
                original_answer=existing,
                input_answer=input_ans,
                normalized_answer=None,
                status=PreviewStatus.INVALID_ANSWER,
                status_message="; ".join(errors),
                will_update=False,
                validation_errors=errors,
            )
            items.append(asdict(item))
            summary.invalid_count += 1
            continue

        # 可以写入
        item = PreviewItem(
            import_id=question.id,
            source_order_index=question.source_order_index,
            source_question_no=question.source_question_no,
            stem_excerpt=_stem_excerpt(question),
            question_type=qt,
            original_answer=existing,
            input_answer=input_ans,
            normalized_answer=normalized,
            status=PreviewStatus.WILL_UPDATE,
            status_message="将写入",
            will_update=True,
        )
        items.append(asdict(item))
        summary.writable_count += 1

    warnings: list[str] = []

    # 生成 preview_token + operation_id
    operation_id = _generate_operation_id()
    preview_data = {
        "batch_id": batch_id,
        "admin_id": admin_id,
        "operation_id": operation_id,
        "raw_text_sha256": hashlib.sha256(raw_text.encode()).hexdigest()[:16],
        "parsed_answer_count": len(parsed_answers),
        "writable_count": summary.writable_count,
        "batch_question_count": len(questions),
        "batch_version": _batch_version(questions),
        "items": _make_preview_items(items, questions[: len(parsed_answers)]),
        "created_at": serialize_utc_datetime(utcnow()),
    }
    token = _generate_token(preview_data)
    await cache.set(
        f"{_PREVIEW_TOKEN_PREFIX}{token}",
        preview_data,
        ttl=_PREVIEW_TOKEN_TTL,
    )

    return {
        "batch_id": batch_id,
        "preview_token": token,
        "operation_id": operation_id,
        "summary": asdict(summary),
        "items": items,
        "warnings": warnings,
    }


def _make_preview_items(
    items: list[dict], questions: list[QuestionImport]
) -> list[dict]:
    """为预览项附加一致性快照字段，供 apply 时校验。"""
    q_map = {q.id: q for q in questions}
    enriched = []
    for item in items:
        q = q_map.get(item.get("import_id"))
        enriched.append(
            {
                "import_id": item["import_id"],
                "source_order_index": item.get("source_order_index"),
                "normalized_answer": item.get("normalized_answer"),
                "will_update": item.get("will_update", False),
                "question_type": item.get("question_type"),
                "options_hash": _options_hash(q) if q else "",
                "updated_at": serialize_utc_datetime(q.updated_at)
                if q and q.updated_at
                else "",
            }
        )
    return enriched


def _batch_version(questions: list[QuestionImport]) -> str:
    """生成批次版本哈希，用于在 apply 时检测顺序/数据变化。"""
    sig_parts = []
    for q in questions:
        sig_parts.append(
            f"{q.id}:{q.source_order_index}:{q.parsed_answer}:{serialize_utc_datetime(q.updated_at) if q.updated_at else ''}"
        )
    return hashlib.sha256("\n".join(sig_parts).encode()).hexdigest()[:32]


def _generate_token(data: dict) -> str:
    """生成预览 token。"""
    import secrets

    h = hashlib.sha256(
        json.dumps(data, sort_keys=True).encode() + secrets.token_hex(8).encode()
    ).hexdigest()[:24]
    return h


# ══════════════════════════════════════════════════════════
# 步骤 5：确认写入 (apply)
# ══════════════════════════════════════════════════════════


async def apply_preview(
    db: AsyncSession,
    batch_id: str,
    preview_token: str,
    current_admin: AdminPrincipal,
    request: Any = None,
) -> dict:
    """根据预览结果确认写入答案。

    幂等性：
    - operation_id 去重：已处理的 operation_id 返回首次执行结果
    - 一致性校验：缓存快照与当前数据库逐字段比对
    - SQL 更新二次限定：WHERE + batch_id + import_id + 答案仍为空 + 可编辑
    """
    # 1. 校验批次可编辑性
    await _check_batch_editable(db, batch_id)

    # 2. 验证 token
    cache_key = f"{_PREVIEW_TOKEN_PREFIX}{preview_token}"
    preview_data = await cache.get(cache_key)
    if not preview_data:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "error_code": PREVIEW_EXPIRED,
                "detail": "预览已过期或无效，请重新预览",
            },
        )

    # 反序列化（缓存存储的是 dict 或 json 字符串）
    if isinstance(preview_data, str):
        preview_data = json.loads(preview_data)
        await cache.set(cache_key, preview_data, ttl=_PREVIEW_TOKEN_TTL)

    # 3. operation_id 幂等检查（仅当 operation_id 非空时生效）
    operation_id = preview_data.get("operation_id", "")
    if operation_id:
        opid_cache_key = f"{_OPID_PREFIX}{operation_id}"
        existing_result = await cache.get(opid_cache_key)
        if existing_result:
            # 已处理过的 operation_id，返回首次结果
            if isinstance(existing_result, str):
                existing_result = json.loads(existing_result)
            return existing_result

    # 幂等性：已使用的 token 直接返回
    if preview_data.get("used"):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "error_code": PREVIEW_ALREADY_APPLIED,
                "detail": "预览 token 已使用，不可重复提交",
            },
        )

    # 4. 校验 token 归属
    if preview_data.get("batch_id") != batch_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INVALID_TOKEN",
                "detail": "预览 token 与当前批次不匹配",
            },
        )
    if (
        preview_data.get("admin_id") is not None
        and preview_data["admin_id"] != current_admin.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "TOKEN_OWNER_MISMATCH",
                "detail": "预览 token 不属于当前管理员",
            },
        )

    # 5. 重新锁定题目，检验一致性
    questions = await _lock_batch_questions(db, batch_id)
    current_version = _batch_version(questions)
    if current_version != preview_data.get("batch_version"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": PREVIEW_STALE,
                "detail": "批次题目顺序或答案已发生变化，请重新预览",
            },
        )

    # 逐项一致性校验
    target_count = preview_data.get("parsed_answer_count", 0)
    target_questions = questions[:target_count]
    preview_items = preview_data.get("items", [])

    for item in preview_items:
        if not item.get("will_update"):
            continue
        import_id = item["import_id"]
        q = next((q for q in target_questions if q.id == import_id), None)
        if not q:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": PREVIEW_STALE,
                    "detail": f"import_id {import_id} 不存在",
                },
            )
        # 校验 source_order_index
        if str(q.source_order_index) != str(item.get("source_order_index", "")):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": PREVIEW_STALE,
                    "detail": f"题目 {import_id} 的 source_order_index 已变化",
                },
            )
        # 校验 question_type
        if q.question_type != item.get("question_type"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": PREVIEW_STALE,
                    "detail": f"题目 {import_id} 的题型已变化",
                },
            )
        # 校验 options_hash
        cached_hash = item.get("options_hash", "")
        if cached_hash and _options_hash(q) != cached_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": PREVIEW_STALE,
                    "detail": f"题目 {import_id} 的选项已变化",
                },
            )
        # 校验答案仍为空（统一判定）
        if not _is_answer_empty(q.parsed_answer):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": PREVIEW_STALE,
                    "detail": f"题目 {import_id} 已有答案，不可再写入",
                },
            )

    # 6. writable_count 检查
    writable_count = preview_data.get("writable_count", 0)
    if writable_count == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": NO_WRITABLE_ITEMS, "detail": "本次没有可写入的题目"},
        )

    # 7. 提取 will_update 记录
    will_update_data = _extract_will_update_items(preview_data, target_questions)

    if not will_update_data:
        return {
            "operation_id": operation_id,
            "updated_count": 0,
            "skipped_existing_count": 0,
            "remaining_count": len(questions) - target_count,
            "batch_stats": await _get_answer_stats(db, batch_id),
        }

    # 8. 逐条 SQL 更新（二次限定条件）
    import_ids_written = []
    try:
        for import_id, normalized_answer in will_update_data:
            stmt = (
                update(QuestionImport)
                .where(
                    QuestionImport.id == import_id,
                    QuestionImport.batch_id == batch_id,
                    QuestionImport.status == "pending",
                )
                .values(
                    parsed_answer=normalized_answer,
                    answer_status="manual_filled",
                    answer_source="manual_batch_input",
                )
            )
            result = await db.execute(stmt)
            if result.rowcount == 1:
                import_ids_written.append(import_id)
            else:
                logger.warning(
                    "Batch answer SQL update rowcount=%d for import_id=%s, expected 1",
                    result.rowcount,
                    import_id,
                )

        await db.flush()
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    updated_count = len(import_ids_written)

    # 9. 记录审计日志并提交
    skipped = writable_count - updated_count
    try:
        await write_admin_audit(
            db,
            current_admin,
            "import.batch_answer_fill",
            "question_import",
            batch_id,
            severity="important",
            detail={
                "batch_id": batch_id,
                "operation_id": operation_id,
                "parsed_answer_count": preview_data.get("parsed_answer_count", 0),
                "target_question_count": target_count,
                "written_count": updated_count,
                "skipped_existing_count": skipped,
                "invalid_count": preview_data.get("invalid_count", 0),
                "unsupported_count": preview_data.get("unsupported_count", 0),
            },
            request=request,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception(
            "Failed to write audit log for batch answer fill (answers already saved)"
        )

    # 10. 标记 token 已使用 + 缓存 operation_id 结果
    batch_stats = await _get_answer_stats(db, batch_id)
    result_payload = {
        "operation_id": operation_id,
        "updated_count": updated_count,
        "skipped_existing_count": skipped,
        "remaining_count": len(questions) - target_count,
        "batch_stats": batch_stats,
    }

    # 缓存 operation_id 结果（幂等）
    if operation_id:
        await cache.set(
            f"{_OPID_PREFIX}{operation_id}",
            result_payload,
            ttl=_OPID_TTL,
        )

    # 保留 token 防重放
    await cache.set(
        cache_key,
        {**preview_data, "used": True, "updated_count": updated_count},
        ttl=300,
    )

    return result_payload


def _extract_will_update_items(
    preview_data: dict, target_questions: list[QuestionImport]
) -> list[tuple[int, str]]:
    """从预览数据中提取需要更新的 (import_id, normalized_answer) 列表。"""
    result: list[tuple[int, str]] = []
    items = preview_data.get("items", [])
    for item in items:
        if not item.get("will_update"):
            continue
        import_id = item.get("import_id")
        normalized = item.get("normalized_answer")
        if import_id and normalized:
            result.append((import_id, normalized))
    return result


# ══════════════════════════════════════════════════════════
# 步骤 6：解析并直接预览（单函数便捷入口）
# ══════════════════════════════════════════════════════════


async def preview_answers(
    db: AsyncSession,
    batch_id: str,
    raw_text: str,
    admin_id: int | None = None,
) -> dict:
    """解析答案串并生成预览。

    这是 generate_preview 的别名，提供给外部模块使用。
    """
    return await generate_preview(db, batch_id, raw_text, admin_id=admin_id)


async def apply_answers(
    db: AsyncSession,
    batch_id: str,
    preview_token: str,
    current_admin: AdminPrincipal,
    request: Any = None,
) -> dict:
    """确认写入预览的答案。

    这是 apply_preview 的别名，提供给外部模块使用。
    """
    return await apply_preview(
        db, batch_id, preview_token, current_admin, request=request
    )

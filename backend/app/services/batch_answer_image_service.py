"""Phase 2: 快速补充答案 — 答案/解析图片导入服务。

从上传的答案页/解析页图片中 OCR 提取答案和解析，
按题号匹配当前批次，支持预览/确认写入。

复用 Phase 1 的设计模式：
- BusinessError + 稳定错误码
- preview_token（15 分钟 TTL）+ operation_id（1 小时幂等）
- _check_batch_editable / _is_answer_empty
- 缓存快照一致性校验
- 逐条 SQL UPDATE（二次限定）
- 审计日志
"""

import hashlib
import json
import logging
import re
import secrets
from enum import Enum
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal
from app.core.cache import cache
from app.core.time_utils import utcnow
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
NO_ANSWERS_PARSED = "NO_ANSWERS_PARSED"
ORDER_INDEX_MISSING = "ORDER_INDEX_MISSING"
ORDER_INDEX_DUPLICATED = "ORDER_INDEX_DUPLICATED"
PREVIEW_EXPIRED = "PREVIEW_EXPIRED"
PREVIEW_STALE = "PREVIEW_STALE"
PREVIEW_ALREADY_APPLIED = "PREVIEW_ALREADY_APPLIED"
NO_WRITABLE_ITEMS = "NO_WRITABLE_ITEMS"

# ── Token 缓存前缀与过期时间 ──
_PREVIEW_TOKEN_PREFIX = "batch_answer_image:preview:"
_PREVIEW_TOKEN_TTL = 900  # 15 分钟
_OPID_PREFIX = "batch_answer_image:opid:"
_OPID_TTL = 3600  # 1 小时

# ── 支持题型 ──
_SUPPORTED_TYPES = frozenset({"single_choice", "multiple_choice", "true_false"})

# ── 编号答案模式：匹配 "01. A"、"1、B"、"2) C" 等 ──
_NUMBERED_ANSWER_PATTERN = re.compile(
    r"(?:^|\n)\s*(\d+)\s*[.、)）]\s*([A-Da-d068TFtf])\b"
)


class ImagePreviewMode(str, Enum):
    """图片导入模式。"""
    ANSWER_ONLY = "answer_only"
    ANSWER_ANALYSIS = "answer_analysis"


class BusinessError(Exception):
    """业务异常，携带稳定错误码。"""
    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


# ══════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════


def _is_answer_empty(val: str | None) -> bool:
    """统一空答案判定。"""
    if val is None:
        return True
    return val.strip() == ""


def _normalize_question_no(raw: str | None) -> str:
    """归一化题号用于匹配。

    - 去前后空白
    - 去前导零
    - 去尾部句号、顿号、括号
    - 转大写
    """
    if not raw:
        return ""
    raw = raw.strip()
    # 去尾部标点
    raw = re.sub(r"[.、)）\s]+$", "", raw)
    # 去前导零
    raw = raw.lstrip("0")
    return raw.upper()


def _extract_entries(text: str, mode: str) -> list[dict]:
    """从 OCR 文本中提取编号答案条目。

    Args:
        text: OCR 输出的文本
        mode: answer_only 或 answer_analysis

    Returns:
        [{"question_no": str, "answer": str, "analysis": str | None, "raw_match": str}, ...]
        按在原文中出现顺序排列。
    """
    if not text.strip():
        return []

    entries: list[dict] = []
    matches = list(_NUMBERED_ANSWER_PATTERN.finditer(text))

    if not matches:
        return entries

    for i, m in enumerate(matches):
        question_no = m.group(1)
        answer = m.group(2).upper()
        full_line = m.group(0).strip()

        entry = {
            "question_no": question_no,
            "answer": answer,
            "raw_match": full_line,
        }

        if mode == ImagePreviewMode.ANSWER_ANALYSIS:
            # 提取当前条目与下一条目之间的文本作为解析
            analysis_start = m.end()
            if i + 1 < len(matches):
                analysis_end = matches[i + 1].start()
            else:
                analysis_end = len(text)

            analysis = text[analysis_start:analysis_end].strip()
            # 清理：去掉开头的换行和空白
            analysis = re.sub(r"^[\s\n]+", "", analysis).rstrip()
            entry["analysis"] = analysis if analysis else None
        else:
            entry["analysis"] = None

        entries.append(entry)

    return entries


def _normalize_single_answer(answer: str, question_type: str | None) -> tuple[str | None, list[str]]:
    """标准化单个答案（复用 Phase 1 逻辑的简化版）。"""
    normalized = answer.strip().upper()
    if not normalized:
        return None, ["答案为空"]

    # 先规范化题型（兼容别名）
    qt, _ = normalize_question_type(question_type)
    if qt is None:
        return None, [f"不支持的题型: {question_type}"]

    # true_false
    if qt == QT_TRUE_FALSE:
        true_vals = {"T", "TRUE", "正确", "对", "√", "1"}
        false_vals = {"F", "FALSE", "错误", "错", "×", "0"}
        if normalized in true_vals:
            return "T", []
        if normalized in false_vals:
            return "F", []
        return None, [f"无法识别的判断题答案: {answer}"]

    # single_choice
    if qt == QT_SINGLE_CHOICE:
        if normalized in {"A", "B", "C", "D"}:
            return normalized, []
        return None, [f"单选题答案格式错误: {answer}"]

    # multi_choice
    if qt == QT_MULTIPLE_CHOICE:
        letters = re.findall(r"[A-D]", normalized)
        if not letters:
            return None, [f"多选题答案格式错误: {answer}"]
        result = "".join(sorted(set(letters)))
        return result, []

    return None, [f"不支持的题型: {question_type}"]


# ══════════════════════════════════════════════════════════
# 批次可编辑性检查
# ══════════════════════════════════════════════════════════


async def _check_batch_editable(db: AsyncSession, batch_id: str) -> None:
    """检查批次内所有题目是否均为可编辑状态。"""
    result = await db.execute(
        select(func.count()).select_from(QuestionImport)
        .where(QuestionImport.batch_id == batch_id, QuestionImport.status != "pending")
    )
    non_pending = result.scalar() or 0
    if non_pending > 0:
        raise BusinessError(
            BATCH_NOT_EDITABLE,
            f"批次含有 {non_pending} 条已处理记录，不可编辑",
        )


async def _lock_batch_questions(db: AsyncSession, batch_id: str) -> list[QuestionImport]:
    """锁定批次题目，校验 source_order_index，按索引升序返回。"""
    result = await db.execute(
        select(QuestionImport)
        .where(QuestionImport.batch_id == batch_id)
        .order_by(QuestionImport.source_order_index.asc().nullslast(), QuestionImport.id.asc())
    )
    questions = list(result.scalars().all())
    if not questions:
        raise ValueError("导入批次不存在")

    null_indices = [q.id for q in questions if q.source_order_index is None]
    if null_indices:
        raise BusinessError(ORDER_INDEX_MISSING, f"{len(null_indices)} 道题缺少 source_order_index")

    seen: dict[int, list[int]] = {}
    for q in questions:
        seen.setdefault(q.source_order_index, []).append(q.id)
    duplicate_indices = {idx: ids for idx, ids in seen.items() if len(ids) > 1}
    if duplicate_indices:
        raise BusinessError(ORDER_INDEX_DUPLICATED, f"存在重复的 source_order_index: {duplicate_indices}")

    return questions


# ══════════════════════════════════════════════════════════
# 匹配逻辑
# ══════════════════════════════════════════════════════════


def _build_question_no_map(questions: list[QuestionImport]) -> dict[str, list[QuestionImport]]:
    """按归一化题号建立 QuestionImport 映射。"""
    q_map: dict[str, list[QuestionImport]] = {}
    for q in questions:
        normalized = _normalize_question_no(q.source_question_no)
        if normalized:
            q_map.setdefault(normalized, []).append(q)
    return q_map


# ══════════════════════════════════════════════════════════
# Token 与 operation_id
# ══════════════════════════════════════════════════════════


def _generate_token(data: dict) -> str:
    h = hashlib.sha256(
        json.dumps(data, sort_keys=True).encode() + secrets.token_hex(8).encode()
    ).hexdigest()[:24]
    return h


def _generate_operation_id() -> str:
    return hashlib.sha256(secrets.token_hex(16).encode()).hexdigest()[:24]


# ══════════════════════════════════════════════════════════
# 预览生成
# ══════════════════════════════════════════════════════════


def _stem_excerpt(question: QuestionImport) -> str:
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
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text[:120] + ("…" if len(text) > 120 else "")


async def _get_answer_stats(db: AsyncSession, batch_id: str) -> dict:
    """获取批次答案相关统计。"""
    total = await db.execute(
        select(func.count()).select_from(QuestionImport)
        .where(QuestionImport.batch_id == batch_id)
    )
    total_count = total.scalar() or 0

    missing_answer = await db.execute(
        select(func.count()).select_from(QuestionImport)
        .where(QuestionImport.batch_id == batch_id, func.coalesce(QuestionImport.parsed_answer, "") == "")
    )
    missing_answer_count = missing_answer.scalar() or 0

    missing_analysis = await db.execute(
        select(func.count()).select_from(QuestionImport)
        .where(QuestionImport.batch_id == batch_id, func.coalesce(QuestionImport.parsed_analysis, "") == "")
    )
    missing_analysis_count = missing_analysis.scalar() or 0

    manual_filled = await db.execute(
        select(func.count()).select_from(QuestionImport)
        .where(QuestionImport.batch_id == batch_id, QuestionImport.answer_source == "manual_batch_input")
    )
    manual_filled_count = manual_filled.scalar() or 0

    return {
        "total_count": total_count,
        "missing_answer_count": missing_answer_count,
        "missing_analysis_count": missing_analysis_count,
        "manual_filled_count": manual_filled_count,
    }


async def generate_image_preview(
    db: AsyncSession,
    batch_id: str,
    images_data: list[dict],
    mode: str,
    admin_id: int | None = None,
) -> dict:
    """上传答案/解析图片，OCR 提取，按题号匹配，生成预览。

    Args:
        db: 数据库会话
        batch_id: 批次 ID
        images_data: 图片数据列表，每项 {"filename": str, "bytes": bytes}
        mode: answer_only | answer_analysis
        admin_id: 当前管理员 ID

    Returns:
        预览响应字典
    """
    # 1. 校验批次可编辑性
    await _check_batch_editable(db, batch_id)

    # 2. OCR 所有图片
    ocr_results: list[dict] = []
    from app.services.ocr_executor_service import ocr_executor

    for img in images_data:
        try:
            text = await ocr_executor.run_ocr(img["bytes"])
            # 简单估算置信度：有文本则 0.8，否则 0
            confidence = 0.8 if text.strip() else 0.0
        except Exception as e:
            logger.warning("图片 OCR 失败: %s, filename=%s", e, img.get("filename", ""))
            text = ""
            confidence = 0.0
        ocr_results.append({
            "filename": img.get("filename", ""),
            "text": text,
            "confidence": confidence,
        })

    # 3. 从所有 OCR 文本中提取条目
    all_entries: list[dict] = []
    warnings: list[str] = []
    for result in ocr_results:
        entries = _extract_entries(result["text"], mode)
        for entry in entries:
            entry["source_filename"] = result["filename"]
            entry["ocr_confidence"] = result["confidence"]
        all_entries.extend(entries)
        if not entries and result["text"].strip():
            warnings.append(
                f"图片 {result['filename']} 中未识别到编号答案格式，请检查图片内容"
            )

    if not all_entries:
        raise BusinessError(NO_ANSWERS_PARSED, "所有图片中均未识别到题号+答案格式的条目")

    # 4. 锁定并加载批次题目
    questions = await _lock_batch_questions(db, batch_id)

    # 5. 建立题号映射
    q_map = _build_question_no_map(questions)

    # 6. 逐条匹配
    summary = {
        "total_images": len(ocr_results),
        "extracted_entries": len(all_entries),
        "matched_count": 0,
        "unmatched_count": 0,
        "ambiguous_count": 0,
        "writable_answer_count": 0,
        "writable_analysis_count": 0,
        "skipped_existing_answer_count": 0,
        "skipped_existing_analysis_count": 0,
    }
    preview_items: list[dict] = []
    matched_q_ids: set[int] = set()

    for entry in all_entries:
        normalized_no = _normalize_question_no(entry["question_no"])
        candidates = q_map.get(normalized_no, [])

        # 过滤掉已匹配的题目（避免同一题被多个条目重复匹配）
        available = [q for q in candidates if q.id not in matched_q_ids]

        if len(candidates) == 0:
            # 无候选 → 未匹配
            preview_items.append({
                "import_id": None,
                "source_order_index": None,
                "source_question_no": entry["question_no"],
                "stem_excerpt": "",
                "question_type": None,
                "original_answer": None,
                "original_analysis": None,
                "extracted_answer": entry["answer"],
                "extracted_analysis": entry.get("analysis"),
                "status": "unmatched",
                "status_message": f"未匹配到题号 {normalized_no} 的题目",
                "will_update_answer": False,
                "will_update_analysis": False,
                "validation_errors": [],
                "source_filename": entry.get("source_filename", ""),
                "image_index": None,
                "ocr_confidence": entry.get("ocr_confidence"),
                "extract_method": "rule",
                "raw_text_excerpt": entry.get("raw_match", "")[:200],
            })
            summary["unmatched_count"] += 1
            continue

        if len(available) == 0 and len(candidates) > 0:
            # 所有候选均已匹配过 → 视为 ambiguous（或 redundant）
            preview_items.append({
                "import_id": None,
                "source_order_index": None,
                "source_question_no": entry["question_no"],
                "stem_excerpt": "",
                "question_type": None,
                "original_answer": None,
                "original_analysis": None,
                "extracted_answer": entry["answer"],
                "extracted_analysis": entry.get("analysis"),
                "status": "ambiguous",
                "status_message": f"题号 {normalized_no} 已匹配过其他条目",
                "will_update_answer": False,
                "will_update_analysis": False,
                "validation_errors": [],
                "source_filename": entry.get("source_filename", ""),
                "image_index": None,
                "ocr_confidence": entry.get("ocr_confidence"),
                "extract_method": "rule",
                "raw_text_excerpt": entry.get("raw_match", "")[:200],
            })
            summary["ambiguous_count"] += 1
            continue

        if len(candidates) > 1:
            # 多个候选 → ambiguous
            preview_items.append({
                "import_id": None,
                "source_order_index": None,
                "source_question_no": entry["question_no"],
                "stem_excerpt": "",
                "question_type": None,
                "original_answer": None,
                "original_analysis": None,
                "extracted_answer": entry["answer"],
                "extracted_analysis": entry.get("analysis"),
                "status": "ambiguous",
                "status_message": f"题号 {normalized_no} 匹配到 {len(candidates)} 道题，无法自动确定",
                "will_update_answer": False,
                "will_update_analysis": False,
                "validation_errors": [],
                "source_filename": entry.get("source_filename", ""),
                "image_index": None,
                "ocr_confidence": entry.get("ocr_confidence"),
                "extract_method": "rule",
                "raw_text_excerpt": entry.get("raw_match", "")[:200],
            })
            summary["ambiguous_count"] += 1
            continue

        # 精确匹配 1 道题
        q = available[0]
        matched_q_ids.add(q.id)
        qt = q.question_type or ""

        # 检查题型是否支持
        if qt.lower() not in _SUPPORTED_TYPES:
            preview_items.append({
                "import_id": q.id,
                "source_order_index": q.source_order_index,
                "source_question_no": q.source_question_no,
                "stem_excerpt": _stem_excerpt(q),
                "question_type": qt,
                "original_answer": q.parsed_answer,
                "original_analysis": q.parsed_analysis,
                "extracted_answer": entry["answer"],
                "extracted_analysis": entry.get("analysis"),
                "status": "unsupported_type",
                "status_message": f"题型不支持批量补录: {qt}",
                "will_update_answer": False,
                "will_update_analysis": False,
                "validation_errors": [],
                "source_filename": entry.get("source_filename", ""),
                "image_index": None,
                "ocr_confidence": entry.get("ocr_confidence"),
                "extract_method": "rule",
                "raw_text_excerpt": entry.get("raw_match", "")[:200],
            })
            continue

        # 标准化答案
        normalized_ans, norm_errors = _normalize_single_answer(entry["answer"], qt)

        # 检查答案是否可写入
        has_existing_answer = not _is_answer_empty(q.parsed_answer)
        will_update_answer = bool(
            not has_existing_answer
            and normalized_ans is not None
            and not norm_errors
        )
        # 检查解析是否可写入
        has_existing_analysis = not _is_answer_empty(q.parsed_analysis)
        will_update_analysis = bool(
            mode == ImagePreviewMode.ANSWER_ANALYSIS
            and not has_existing_analysis
            and entry.get("analysis")
        )

        if has_existing_answer:
            summary["skipped_existing_answer_count"] += 1
        if has_existing_analysis:
            summary["skipped_existing_analysis_count"] += 1
        if will_update_answer:
            summary["writable_answer_count"] += 1
        if will_update_analysis:
            summary["writable_analysis_count"] += 1

        summary["matched_count"] += 1

        status_str = "matched"
        status_msg_parts = []
        if will_update_answer:
            status_msg_parts.append(f"将写入答案 {normalized_ans}")
        if will_update_analysis:
            status_msg_parts.append("将写入解析")
        if has_existing_answer:
            status_msg_parts.append(f"已有答案 {q.parsed_answer}，跳过")
        if has_existing_analysis:
            status_msg_parts.append("已有解析，跳过")
        if not will_update_answer and not will_update_analysis:
            status_str = "skipped"
            status_msg_parts.append("无需更新")

        preview_items.append({
            "import_id": q.id,
            "source_order_index": q.source_order_index,
            "source_question_no": q.source_question_no,
            "stem_excerpt": _stem_excerpt(q),
            "question_type": qt,
            "original_answer": q.parsed_answer,
            "original_analysis": q.parsed_analysis,
            "extracted_answer": normalized_ans if normalized_ans else entry["answer"],
            "extracted_analysis": entry.get("analysis"),
            "status": status_str,
            "status_message": "；".join(status_msg_parts),
            "will_update_answer": will_update_answer,
            "will_update_analysis": will_update_analysis,
            "validation_errors": norm_errors,
            "source_filename": entry.get("source_filename", ""),
            "image_index": None,
            "ocr_confidence": entry.get("ocr_confidence"),
            "extract_method": "rule",
            "raw_text_excerpt": entry.get("raw_match", "")[:200],
        })

    # 7. 生成 preview_token 和 operation_id
    operation_id = _generate_operation_id()

    # 构建一致性快照
    snapshot_items = [
        {
            "import_id": it["import_id"],
            "source_order_index": it["source_order_index"],
            "normalized_answer": it["extracted_answer"],
            "extracted_analysis": it["extracted_analysis"],
            "will_update_answer": it["will_update_answer"],
            "will_update_analysis": it["will_update_analysis"],
            "question_type": it["question_type"],
            "original_answer": it["original_answer"],
            "original_analysis": it["original_analysis"],
        }
        for it in preview_items
        if it["import_id"] is not None
    ]

    preview_data = {
        "batch_id": batch_id,
        "admin_id": admin_id,
        "operation_id": operation_id,
        "mode": mode,
        "extracted_count": len(all_entries),
        "matched_count": summary["matched_count"],
        "writable_answer_count": summary["writable_answer_count"],
        "writable_analysis_count": summary["writable_analysis_count"],
        "items": snapshot_items,
        "created_at": utcnow().isoformat(),
    }
    token = _generate_token(preview_data)
    await cache.set(f"{_PREVIEW_TOKEN_PREFIX}{token}", preview_data, ttl=_PREVIEW_TOKEN_TTL)

    return {
        "batch_id": batch_id,
        "preview_token": token,
        "operation_id": operation_id,
        "summary": summary,
        "items": preview_items,
        "warnings": warnings,
    }


# ══════════════════════════════════════════════════════════
# 确认写入 (apply)
# ══════════════════════════════════════════════════════════


async def apply_image_preview(
    db: AsyncSession,
    batch_id: str,
    preview_token: str,
    current_admin: AdminPrincipal,
    request: Any = None,
) -> dict:
    """确认写入答案/解析。

    幂等性：operation_id 去重（1 小时）、token 防重放。
    一致性：逐项校验 import_id、source_order_index、答案仍为空等。
    """
    # 1. 校验批次可编辑性
    await _check_batch_editable(db, batch_id)

    # 2. 验证 token
    cache_key = f"{_PREVIEW_TOKEN_PREFIX}{preview_token}"
    preview_data = await cache.get(cache_key)
    if not preview_data:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"error_code": PREVIEW_EXPIRED, "detail": "预览已过期或无效，请重新预览"},
        )
    if isinstance(preview_data, str):
        preview_data = json.loads(preview_data)
        await cache.set(cache_key, preview_data, ttl=_PREVIEW_TOKEN_TTL)

    # 3. operation_id 幂等检查
    operation_id = preview_data.get("operation_id", "")
    if operation_id:
        opid_cache_key = f"{_OPID_PREFIX}{operation_id}"
        existing_result = await cache.get(opid_cache_key)
        if existing_result:
            if isinstance(existing_result, str):
                existing_result = json.loads(existing_result)
            return existing_result

    # 4. token 已使用检查
    if preview_data.get("used"):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"error_code": PREVIEW_ALREADY_APPLIED, "detail": "预览 token 已使用"},
        )

    # 5. token 归属校验
    if preview_data.get("batch_id") != batch_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "INVALID_TOKEN", "detail": "预览 token 与当前批次不匹配"},
        )
    if preview_data.get("admin_id") is not None and preview_data["admin_id"] != current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "TOKEN_OWNER_MISMATCH", "detail": "预览 token 不属于当前管理员"},
        )

    # 6. 重新加载题目，逐项一致性校验
    questions = await _lock_batch_questions(db, batch_id)
    q_dict = {q.id: q for q in questions}
    items = preview_data.get("items", [])

    writable_answer_count = preview_data.get("writable_answer_count", 0)
    writable_analysis_count = preview_data.get("writable_analysis_count", 0)
    if writable_answer_count == 0 and writable_analysis_count == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": NO_WRITABLE_ITEMS, "detail": "本次没有可写入的题目"},
        )

    # 提取需要更新的记录
    will_update_answer_ids: list[int] = []
    will_update_analysis_ids: list[int] = []

    for item in items:
        import_id = item.get("import_id")
        if import_id is None:
            continue
        q = q_dict.get(import_id)
        if not q:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error_code": PREVIEW_STALE, "detail": f"import_id {import_id} 不存在"},
            )

        # 校验 source_order_index
        if str(q.source_order_index) != str(item.get("source_order_index", "")):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error_code": PREVIEW_STALE, "detail": f"题目 {import_id} 的 source_order_index 已变化"},
            )
        # 校验 question_type
        if q.question_type != item.get("question_type"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error_code": PREVIEW_STALE, "detail": f"题目 {import_id} 的题型已变化"},
            )

        # 校验答案仍为空
        if item.get("will_update_answer"):
            if item.get("extracted_answer") != item.get("normalized_answer"):
                # 兼容字段名差异
                pass
            if not _is_answer_empty(q.parsed_answer):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error_code": PREVIEW_STALE, "detail": f"题目 {import_id} 已有答案，不可再写入"},
                )
            will_update_answer_ids.append(import_id)

        # 校验解析仍为空
        if item.get("will_update_analysis"):
            if not _is_answer_empty(q.parsed_analysis):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error_code": PREVIEW_STALE, "detail": f"题目 {import_id} 已有解析，不可再写入"},
                )
            will_update_analysis_ids.append(import_id)

    if not will_update_answer_ids and not will_update_analysis_ids:
        result_payload = {
            "operation_id": operation_id,
            "updated_answer_count": 0,
            "updated_analysis_count": 0,
            "skipped_existing_answer_count": 0,
            "skipped_existing_analysis_count": 0,
            "remaining_count": 0,
            "batch_stats": await _get_answer_stats(db, batch_id),
        }
        if operation_id:
            await cache.set(f"{_OPID_PREFIX}{operation_id}", result_payload, ttl=_OPID_TTL)
        return result_payload

    # 7. 构建答案/解析值的映射
    answer_values: dict[int, str] = {}
    analysis_values: dict[int, str] = {}
    for item in items:
        import_id = item.get("import_id")
        if import_id is None:
            continue
        if import_id in will_update_answer_ids and item.get("extracted_answer"):
            answer_values[import_id] = item["extracted_answer"]
        if import_id in will_update_analysis_ids and item.get("extracted_analysis"):
            analysis_values[import_id] = item["extracted_analysis"]

    # 8. 逐条 SQL 更新（二次限定条件）
    updated_answer_count = 0
    updated_analysis_count = 0

    try:
        # 更新答案
        for import_id, normalized_answer in answer_values.items():
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
                updated_answer_count += 1

        # 更新解析
        for import_id, analysis in analysis_values.items():
            stmt = (
                update(QuestionImport)
                .where(
                    QuestionImport.id == import_id,
                    QuestionImport.batch_id == batch_id,
                    QuestionImport.status == "pending",
                )
                .values(
                    parsed_analysis=analysis,
                )
            )
            result = await db.execute(stmt)
            if result.rowcount == 1:
                updated_analysis_count += 1

        await db.flush()
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    # 9. 审计日志
    try:
        await write_admin_audit(
            db,
            current_admin,
            "import.batch_answer_image_fill",
            "question_import",
            batch_id,
            severity="important",
            detail={
                "batch_id": batch_id,
                "operation_id": operation_id,
                "mode": preview_data.get("mode", ""),
                "extracted_count": preview_data.get("extracted_count", 0),
                "updated_answer_count": updated_answer_count,
                "updated_analysis_count": updated_analysis_count,
            },
            request=request,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Failed to write audit log for batch answer image fill")

    # 10. 标记 token 已使用 + 缓存 operation_id
    batch_stats = await _get_answer_stats(db, batch_id)
    result_payload = {
        "operation_id": operation_id,
        "updated_answer_count": updated_answer_count,
        "updated_analysis_count": updated_analysis_count,
        "skipped_existing_answer_count": writable_answer_count - updated_answer_count,
        "skipped_existing_analysis_count": writable_analysis_count - updated_analysis_count,
        "remaining_count": len(questions) - len(items),
        "batch_stats": batch_stats,
    }

    if operation_id:
        await cache.set(f"{_OPID_PREFIX}{operation_id}", result_payload, ttl=_OPID_TTL)
    await cache.set(cache_key, {**preview_data, "used": True}, ttl=300)

    return result_payload

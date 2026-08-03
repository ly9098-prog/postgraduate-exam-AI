import logging
import re
from math import ceil
from uuid import uuid4

from fastapi import Request
from sqlalchemy import String, case, cast, delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal
from app.core.cache import cache
from app.core.time_utils import utcnow
from app.features import question_pipeline
from app.models.question_import import QuestionImport
from app.schemas.admin_imports import (
    AdminImportBatchDetail,
    AdminImportEnrichResponse,
    AdminImportQuestionItem,
    AdminImportQuestionItemBrief,
    AdminImportQuestionUpdateRequest,
)
from app.services.admin_ai_settings_service import ensure_ai_parse_allowed
from app.services.admin_audit_service import write_admin_audit
from app.services.visual_region_types import contains_visual_reference

logger = logging.getLogger(__name__)

_TASK_TTL_SECONDS = 86400

# ── 历史数据兜底：从 raw_data 中提取 source_question_no ──
_SOURCE_NO_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^\s*(\d+)\s*[.．、)）]"), r"\1"),
    (re.compile(r"^\s*第\s*(\d+)\s*题"), r"\1"),
    (re.compile(r"^\s*[（(]\s*(\d+)\s*[）)]"), r"\1"),
]


def resolve_source_page(raw_data: dict | None) -> int | None:
    """从 raw_data 中按优先级提取页码。

    优先级：
    1. raw_data["source"]["source_page_start"]
    2. raw_data["source"]["page_start"]
    3. raw_data["source"]["page"]
    4. raw_data["page_start"]
    5. raw_data["source_page"]
    6. raw_data["page"]

    返回 int 或 None。
    """
    if not raw_data or not isinstance(raw_data, dict):
        return None

    source = raw_data.get("source")
    if isinstance(source, dict):
        for key in ("source_page_start", "page_start", "page"):
            val = source.get(key)
            if val is not None:
                try:
                    return int(val)
                except (TypeError, ValueError):
                    continue

    for key in ("page_start", "source_page", "page"):
        val = raw_data.get(key)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                continue

    return None


def resolve_source_page_end(raw_data: dict | None) -> int | None:
    """从 raw_data 中提取结束页码。优先级：
    1. raw_data["source"]["source_page_end"]
    2. raw_data["source"]["page_end"]
    3. raw_data["page_end"]
    """
    if not raw_data or not isinstance(raw_data, dict):
        return None

    source = raw_data.get("source")
    if isinstance(source, dict):
        for key in ("source_page_end", "page_end"):
            val = source.get(key)
            if val is not None:
                try:
                    return int(val)
                except (TypeError, ValueError):
                    continue

    val = raw_data.get("page_end")
    if val is not None:
        try:
            return int(val)
        except (TypeError, ValueError):
            pass

    return None


def build_source_locator(
    source_image_seq: int | None = None,
    source_image_name: str | None = None,
    source_file: str | None = None,
    source_page_start: int | None = None,
    source_page_end: int | None = None,
) -> str | None:
    """统一生成 source_locator 字符串。"""
    parts: list[str] = []
    if source_image_seq is not None:
        parts.append(f"图{source_image_seq}")
    if source_image_name:
        parts.append(source_image_name)
    elif source_file:
        parts.append(source_file)
    if source_page_start is not None and source_page_end is not None and source_page_end != source_page_start:
        parts.append(f"第{source_page_start}-{source_page_end}页")
    elif source_page_start is not None:
        parts.append(f"第{source_page_start}页")
    return " · ".join(parts) if parts else None


def _fallback_source_question_no(raw_data: dict | str | None) -> str | None:
    """从 raw_data 中尝试提取原题号（用于历史数据兼容）。

    先查 raw_data.raw_text，再查 raw_data.raw_question_text，再查 text/stem。
    匹配成功返回题号字符串，失败返回 None。
    """
    if not raw_data:
        return None
    text = None
    if isinstance(raw_data, dict):
        text = (
            raw_data.get("raw_text")
            or raw_data.get("raw_question_text")
            or raw_data.get("text")
            or raw_data.get("stem")
        )
    elif isinstance(raw_data, str):
        text = raw_data
    if not text or not isinstance(text, str):
        return None
    first_line = text.split("\n")[0].strip()
    for pat, repl in _SOURCE_NO_PATTERNS:
        m = pat.match(first_line)
        if m:
            return m.group(1)
    return None


def derive_import_risk(
    ai_metadata: dict | None,
    *,
    ai_answer_flag: bool | None = None,
    parsed_answer: str | None = None,
    answer_status: str | None = None,
    parsed_content: dict | None = None,
) -> dict:
    """从导入题目元数据推导风险等级。

    Args:
        ai_metadata: 来自管线的 ai_metadata 字典
        ai_answer_flag: 答案是否 AI 生成
        parsed_answer: 解析后的答案字符串
        answer_status: 答案状态标签
        parsed_content: 解析后的内容（用于视觉引用检测）

    Returns:
        {"risk_flags": [...], "risk_level": "high"|"medium"|"low", "risk_reasons": [...]}
    """
    risk_flags: list[str] = []
    meta = ai_metadata or {}

    # 1. 从 ai_metadata.risk_flags 提取已有的风险标记
    meta_risk_flags = meta.get("risk_flags")
    if isinstance(meta_risk_flags, list):
        risk_flags.extend(meta_risk_flags)

    # 2. 答案 AI 生成
    if ai_answer_flag and "answer_ai_generated" not in risk_flags:
        risk_flags.append("answer_ai_generated")

    # 3. 答案缺失（pending 状态且无答案）
    has_answer = bool(parsed_answer and parsed_answer.strip())
    if not has_answer and "answer_missing" not in risk_flags:
        risk_flags.append("answer_missing")

    # 3b. answer_status 补充判断（不会重复添加，因为上面已检查）
    if answer_status == "missing" and "answer_missing" not in risk_flags:
        risk_flags.append("answer_missing")
    elif answer_status == "ai_filled" and "answer_ai_generated" not in risk_flags:
        risk_flags.append("answer_ai_generated")
    elif answer_status == "abnormal" and "options_anomaly" not in risk_flags:
        risk_flags.append("options_anomaly")

    # 4. AI 修复/补全来源
    ai_source = meta.get("ai_source") or ""
    if ai_source in ("repair", "complete", "enrich"):
        flag = f"ai_{ai_source}"
        if flag not in risk_flags:
            risk_flags.append(flag)

    # 5. 置信度过低
    confidence = meta.get("confidence") or meta.get("confidence_score")
    if confidence is not None and isinstance(confidence, (int, float)):
        if confidence < 0.5:
            risk_flags.append("low_confidence")

    # 6. 视觉引用检测：题干提及图片但没有对应视觉 segment
    if parsed_content and isinstance(parsed_content, dict):
        stem_text = parsed_content.get("text", "")
        segments = parsed_content.get("segments")
        if stem_text and contains_visual_reference(stem_text):
            if "visual_reference_detected" not in risk_flags:
                risk_flags.append("visual_reference_detected")
            # Check if there's actually a visual segment
            has_visual_segment = False
            if segments and isinstance(segments, list):
                has_visual_segment = any(
                    s.get("type") in ("image", "math_image", "table_image", "code_image", "diagram", "chart")
                    for s in segments
                    if isinstance(s, dict) and s.get("url")
                )
            if not has_visual_segment and "visual_reference_but_image_missing" not in risk_flags:
                risk_flags.append("visual_reference_but_image_missing")

    risk_reasons = _build_risk_reasons(risk_flags)
    risk_level = _compute_risk_level(risk_flags)

    return {
        "risk_flags": risk_flags,
        "risk_level": risk_level,
        "risk_reasons": risk_reasons,
    }


def _compute_risk_level(risk_flags: list[str]) -> str:
    flag_set = set(risk_flags)
    high_flags = {
        "answer_ai_generated", "code_uncertain", "formula_uncertain",
        "options_anomaly", "answer_missing", "ai_major_edit",
        "math_image_crop_failed", "math_image_upload_failed",
        "source_image_upload_failed",
        "table_low_confidence", "complex_formula_requires_review",
        # Visual content blocking flags
        "visual_reference_but_image_missing",
        "visual_region_bbox_missing",
        "visual_crop_failed",
        "visual_region_ambiguous",
        "visual_region_unassigned",
        "math_image_bbox_missing",
        "option_image_requires_review",
    }
    medium_flags = {
        "ai_repair", "ai_complete", "ai_enrich",
        "low_confidence", "contains_code", "contains_formula",
        "answer_uncertain",
        "math_region_detected", "math_image_attached",
        "table_detected", "table_requires_review",
        "source_region_available",
        # Visual content medium flags
        "visual_reference_detected",
        "visual_region_detected",
        "visual_insert_position_uncertain",
        "source_snapshot_failed",
    }
    if flag_set & high_flags:
        return "high"
    if flag_set & medium_flags:
        return "medium"
    return "low"


def _build_risk_reasons(risk_flags: list[str]) -> list[str]:
    flag_to_reason = {
        "answer_ai_generated": "答案由 AI 补全，请核对原题",
        "code_uncertain": "代码部分 AI 无法确认，请人工核对",
        "formula_uncertain": "公式可能识别不准确，请人工核对",
        "options_anomaly": "选项数量异常，请检查",
        "answer_missing": "答案缺失，需人工确认",
        "ai_major_edit": "AI 大幅修改了题目内容，请仔细核对",
        "ai_repair": "AI 修复了题目结构",
        "ai_complete": "AI 补全了缺失字段",
        "ai_enrich": "AI 丰富了题目信息",
        "low_confidence": "OCR 置信度偏低，请仔细核对",
        "contains_code": "题目包含代码，请注意缩进和符号",
        "contains_formula": "题目包含数学公式，请核对",
        "answer_uncertain": "答案不确定，需人工确认",
        "non_question_like": "内容可能不是标准题目格式",
        "no_exercise_regions": "未检测到习题区域",
        "ocr_garbled_code": "检测到 OCR 乱码",
        # P1: 公式截图与表格风险
        "math_region_detected": "检测到数学公式区域",
        "math_low_confidence": "公式 OCR 置信度偏低，请核对",
        "complex_formula_requires_review": "检测到复杂公式，需人工核对",
        "math_image_attached": "已生成公式截图",
        "math_image_crop_failed": "公式截图裁剪失败",
        "math_image_upload_failed": "公式截图上传失败",
        "math_image_bbox_missing": "公式区域缺少位置信息，无法自动裁剪",
        "table_detected": "检测到表格内容",
        "table_requires_review": "表格内容需核对",
        "table_low_confidence": "表格置信度偏低，请核对",
        "source_region_available": "原题区域截图可用",
        "source_image_upload_failed": "原题截图上传失败",
        # Visual content risk flags
        "visual_reference_detected": "题干引用了图片/图表，请检查是否完整",
        "visual_reference_but_image_missing": "题干预设有图片但缺少对应图像",
        "visual_region_detected": "检测到图形/图表区域",
        "visual_region_bbox_missing": "图形区域缺少位置信息",
        "visual_crop_failed": "图形裁剪失败",
        "visual_region_ambiguous": "图形归属题目不确定",
        "visual_insert_position_uncertain": "图形在题干中的插入位置不确定",
        "visual_region_unassigned": "存在未归属到任何题目的图形",
        "option_image_requires_review": "选项包含图片，需人工确认",
        "source_snapshot_failed": "原题快照生成失败",
    }
    reasons: list[str] = []
    seen: set[str] = set()
    for flag in risk_flags:
        reason = flag_to_reason.get(flag)
        if reason and reason not in seen:
            reasons.append(reason)
            seen.add(reason)
    return reasons


# ── Visual option blocking check (re-computed from current DB state) ──

_OPTION_PLACEHOLDER_PATTERNS: list[re.Pattern] = [
    re.compile(r"图片\s*选项\s*[A-D]"),
    re.compile(r"原题图已内嵌"),
    re.compile(r"见原图"),
    re.compile(r"图略"),
    re.compile(r"\[.*?图片.*?\]"),
    re.compile(r"【.*?图片.*?】"),
    re.compile(r"option\s*image\s*placeholder", re.I),
    re.compile(r"图形\s*选项\s*[A-D]"),
    re.compile(r"[图片图形]\s*缺失"),
]

_VALID_OPTION_KEYS = frozenset({"A", "B", "C", "D", "E", "F"})

_OPTION_VISUAL_BLOCKING_FLAGS = frozenset({
    "placeholder_missing",
    "missing_option_image_asset",
    "invalid_option_count",
    "unreachable_image_url",
    "unresolved_option_mapping",
    "option_image_requires_review",
})


def _is_image_option_placeholder(text: object) -> bool:
    """Check if a value is a known Chinese image-option placeholder string."""
    if not isinstance(text, str):
        return False
    t = text.strip()
    if not t:
        return False
    return any(p.search(t) for p in _OPTION_PLACEHOLDER_PATTERNS)


def _check_option_visual_blocking(
    parsed_content: dict | None,
    parsed_options: dict | None,
) -> list[str]:
    """Re-compute visual option blocking issues from current data.

    Returns a list of blocking flags (empty = no block).  This is computed
    from the actual DB state, NOT from cached risk_flags.
    """
    blocking: list[str] = []
    if not parsed_options:
        return blocking

    segments = (parsed_content or {}).get("segments") or []

    # 1. Check for placeholder text in parsed_options
    has_placeholder = False
    for key in _VALID_OPTION_KEYS:
        val = parsed_options.get(key)
        if val is not None and _is_image_option_placeholder(val):
            has_placeholder = True
            break
    if has_placeholder:
        blocking.append("placeholder_missing")
        if "missing_option_image_asset" not in blocking:
            blocking.append("missing_option_image_asset")

    # 2. Check option_group region validity
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        rt = str(seg.get("region_type", ""))
        if rt == "option_group":
            expected = seg.get("expected_option_count")
            detected = seg.get("detected_option_count")
            if expected is None or detected is None or expected < 2 or expected > 6 or detected != expected:
                if "invalid_option_count" not in blocking:
                    blocking.append("invalid_option_count")
            url = str(seg.get("url", "") or "")
            if not url:
                if "unreachable_image_url" not in blocking:
                    blocking.append("unreachable_image_url")
        # Legacy region_id fallback
        rid = str(seg.get("region_id", ""))
        if rt != "option_group" and "option_group" in rid:
            if "unresolved_option_mapping" not in blocking:
                blocking.append("unresolved_option_mapping")
            if "option_image_requires_review" not in blocking:
                blocking.append("option_image_requires_review")

    # 3. All parsed_options empty but no option_group segment — only flag
    #    as placeholder_missing when we haven't already detected a legacy fallback
    has_legacy_fallback = "unresolved_option_mapping" in blocking or "option_image_requires_review" in blocking
    if not has_legacy_fallback:
        all_empty = all(
            isinstance(parsed_options.get(k), str) and not parsed_options[k].strip()
            for k in _VALID_OPTION_KEYS
            if k in parsed_options
        )
        if all_empty and parsed_options:
            has_option_group_seg = any(
                isinstance(s, dict) and str(s.get("region_type", "")) == "option_group"
                for s in segments
            )
            if not has_option_group_seg:
                if "placeholder_missing" not in blocking:
                    blocking.append("placeholder_missing")

    return blocking


async def _ensure_no_option_visual_blocking(qi: QuestionImport) -> None:
    """Raise ValueError if the QuestionImport has unresolved visual option issues."""
    blocking = _check_option_visual_blocking(qi.parsed_content, qi.parsed_options)
    if blocking:
        blocking_str = "、".join(blocking)
        raise ValueError(
            f"题目 #{qi.id} 存在未解决的图片选项问题，禁止审核通过：{blocking_str}。"
            f"请先修复选项图片或确认选项内容。"
        )


async def list_import_batches(
    db: AsyncSession,
    page: int,
    page_size: int,
    status: str | None = None,
    source_type: str | None = None,
    keyword: str | None = None,
) -> tuple[list[dict], int]:
    conditions = _batch_conditions(status, source_type, keyword)
    total_query = select(func.count()).select_from(select(QuestionImport.batch_id).where(*conditions).group_by(QuestionImport.batch_id).subquery())
    total = await db.scalar(total_query)

    result = await db.execute(
        _batch_summary_query(conditions)
        .order_by(desc("updated_at"), desc("created_at"), QuestionImport.batch_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return [_batch_row_to_dict(row) for row in result.all()], int(total or 0)


async def get_import_batch_detail(
    db: AsyncSession,
    batch_id: str,
    page: int,
    page_size: int,
    status: str | None = None,
) -> AdminImportBatchDetail:
    batch_conditions = [QuestionImport.batch_id == batch_id]
    summary_result = await db.execute(_batch_summary_query(batch_conditions))
    summary_row = summary_result.first()
    if not summary_row:
        raise ValueError("导入批次不存在")

    item_conditions = [QuestionImport.batch_id == batch_id]
    if status:
        item_conditions.append(QuestionImport.status == status)
    total = await db.scalar(select(func.count()).select_from(QuestionImport).where(*item_conditions))
    item_result = await db.execute(
        select(*_LIST_COLUMNS)
        .where(*item_conditions)
        .order_by(QuestionImport.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    item_rows = item_result.mappings().all()
    items = [_brief_from_row(row) for row in item_rows]
    summary = _batch_row_to_dict(summary_row)
    return AdminImportBatchDetail(
        **summary,
        items=items,
        page=page,
        page_size=page_size,
        total_pages=max(ceil(int(total or 0) / page_size), 1) if total else 0,
    )


def _apply_risk_to_item(item: AdminImportQuestionItem) -> AdminImportQuestionItem:
    """对单个 item 注入风险字段（risk_flags / risk_level / risk_reasons）。"""
    risk = derive_import_risk(
        item.ai_metadata,
        ai_answer_flag=item.ai_answer_flag,
        parsed_answer=item.parsed_answer,
        answer_status=item.answer_status,
    )
    # 用 model_config 允许额外字段
    item.risk_flags = risk["risk_flags"]
    item.risk_level = risk["risk_level"]
    item.risk_reasons = risk["risk_reasons"]
    return item


_LIST_COLUMNS = (
    QuestionImport.id,
    QuestionImport.batch_id,
    QuestionImport.source_type,
    QuestionImport.source_file,
    QuestionImport.subject_id,
    QuestionImport.question_type,
    QuestionImport.parsed_answer,
    QuestionImport.question_hash,
    QuestionImport.duplicate_status,
    QuestionImport.duplicate_of_question_id,
    QuestionImport.duplicate_of_import_id,
    QuestionImport.status,
    QuestionImport.review_note,
    QuestionImport.question_id,
    QuestionImport.reject_reason,
    QuestionImport.reviewed_by,
    QuestionImport.reviewed_at,
    QuestionImport.ai_generated,
    QuestionImport.ai_source,
    QuestionImport.ai_confidence,
    QuestionImport.ai_metadata,
    QuestionImport.ai_reviewed_at,
    QuestionImport.ai_answer_flag,
    QuestionImport.created_at,
    QuestionImport.updated_at,
    # ── 导入审核定位与答案状态字段 ──
    QuestionImport.source_question_no,
    QuestionImport.source_question_label,
    QuestionImport.source_image_seq,
    QuestionImport.source_image_name,
    QuestionImport.source_page_start,
    QuestionImport.source_page_end,
    QuestionImport.source_order_index,
    QuestionImport.raw_text_preview,
    QuestionImport.answer_status,
    QuestionImport.answer_source,
    QuestionImport.answer_confidence,
    QuestionImport.review_priority,
    # raw_data 用于历史数据兜底提取 source_question_no
    QuestionImport.raw_data,
    func.substr(
        func.coalesce(
            QuestionImport.parsed_content['text'].as_string(),
            QuestionImport.parsed_content.cast(String),
        ), 1, 160
    ).label("content_preview"),
)


def _brief_from_row(row) -> AdminImportQuestionItemBrief:
    """Convert a row mapping to AdminImportQuestionItemBrief with risk fields."""
    item = AdminImportQuestionItemBrief.model_validate(row)
    risk = derive_import_risk(
        item.ai_metadata,
        ai_answer_flag=item.ai_answer_flag,
        parsed_answer=item.parsed_answer,
        answer_status=item.answer_status,
    )
    item.risk_flags = risk["risk_flags"]
    item.risk_level = risk["risk_level"]
    item.risk_reasons = risk["risk_reasons"]
    # ── 历史数据兜底：从 raw_data 提取 source_question_no 和 raw_text_preview ──
    if not item.source_question_no or not item.raw_text_preview or item.source_image_seq is None or not item.source_locator:
        _raw_data = None
        if hasattr(row, "_mapping"):
            _raw_data = row._mapping.get("raw_data")
        if not _raw_data and isinstance(row, dict):
            _raw_data = row.get("raw_data")
        if _raw_data:
            if not item.source_question_no:
                fallback = _fallback_source_question_no(_raw_data)
                if fallback:
                    item.source_question_no = fallback
            if not item.raw_text_preview:
                _raw_text = (
                    _raw_data.get("raw_text")
                    or _raw_data.get("raw_question_text")
                    or _raw_data.get("text")
                )
                if _raw_text:
                    item.raw_text_preview = str(_raw_text)[:200]
            if item.source_image_seq is None:
                item.source_image_seq = _raw_data.get("source_image_seq") or _raw_data.get("seq")
            if not item.source_image_name:
                item.source_image_name = _raw_data.get("source_image_name") or _raw_data.get("source_file") or _raw_data.get("file_name")
            if item.source_page_start is None:
                item.source_page_start = (
                    resolve_source_page(_raw_data)
                    or _raw_data.get("page_start") or _raw_data.get("source_page") or _raw_data.get("page")
                )
            if item.source_page_end is None:
                item.source_page_end = (
                    resolve_source_page_end(_raw_data)
                    or _raw_data.get("page_end")
                )

    # ── source_locator 动态生成（无数据库字段时也保证返回） ──
    if not item.source_locator:
        item.source_locator = build_source_locator(
            source_image_seq=item.source_image_seq,
            source_image_name=item.source_image_name,
            source_file=getattr(item, "source_file", None),
            source_page_start=item.source_page_start,
            source_page_end=item.source_page_end,
        )
    return item


async def list_review_queue(
    db: AsyncSession,
    page: int,
    page_size: int,
    status: str | None = "pending",
    batch_id: str | None = None,
    subject: str | None = None,
    source_type: str | None = None,
    keyword: str | None = None,
    risk_level: str | None = None,
    subject_id: int | None = None,
    answer_status: str | None = None,
    question_type: str | None = None,
    sort: str | None = None,
) -> tuple[list[AdminImportQuestionItemBrief], int]:
    from app.models.admin import Subject
    from app.services.admin_subject_service import resolve_subject_id

    if subject and subject_id is None:
        resolved = await resolve_subject_id(db, subject)
        if resolved is not None:
            subject_id = resolved
    conditions = _question_conditions(status, batch_id, source_type, keyword, subject_id=subject_id)

    # answer_status 过滤
    if answer_status:
        conditions.append(QuestionImport.answer_status == answer_status)
    # question_type 过滤
    if question_type:
        conditions.append(QuestionImport.question_type == question_type)

    total = await db.scalar(select(func.count()).select_from(QuestionImport).where(*conditions))

    # 排序
    if sort == "source_order" or (sort is None and batch_id):
        # 按来源图片顺序 + 原题号排序
        order_by = (
            QuestionImport.source_image_seq.asc().nullslast(),
            QuestionImport.source_page_start.asc().nullslast(),
            QuestionImport.source_order_index.asc().nullslast(),
            QuestionImport.id.asc(),
        )
    elif sort == "risk_desc":
        order_by = (QuestionImport.review_priority.asc().nullslast(), QuestionImport.created_at.desc())
    elif sort == "answer_priority":
        # 答案缺失 / AI 补全优先
        order_by = (
            QuestionImport.review_priority.asc().nullslast(),
            QuestionImport.source_image_seq.asc().nullslast(),
            QuestionImport.source_order_index.asc().nullslast(),
            QuestionImport.id.asc(),
        )
    else:
        # 默认按创建时间倒序
        order_by = (QuestionImport.created_at.desc(), QuestionImport.id.desc())

    result = await db.execute(
        select(
            *_LIST_COLUMNS,
            Subject.code.label("subject_code"),
            Subject.name.label("subject_name"),
        )
        .outerjoin(Subject, QuestionImport.subject_id == Subject.id)
        .where(*conditions)
        .order_by(*order_by)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = result.mappings().all()
    items = [_brief_from_row(row) for row in rows]

    # 风险等级过滤（内存过滤，因为 risk_level 是动态计算的）
    if risk_level:
        items = [item for item in items if item.risk_level == risk_level]

    return items, int(total or 0)


async def update_import_question(
    db: AsyncSession,
    import_id: int,
    data: AdminImportQuestionUpdateRequest,
) -> AdminImportQuestionItem:
    qi = await _get_import_question(db, import_id)
    if qi.status == "published" or qi.question_id is not None:
        raise ValueError("已发布题目不可编辑")

    payload = data.model_dump(exclude_none=True)
    # Capture options before potential pop for multi_blank_choice handling
    _options_val = payload.get("options")
    if "stem" in payload:
        from app.services.pdf_text_normalizer import deduplicate_repeated_text
        content = dict(qi.parsed_content or {})
        stem_text = deduplicate_repeated_text(payload.pop("stem").strip())
        content["stem"] = stem_text
        content["text"] = stem_text
        qi.parsed_content = content
    if "options" in payload:
        options = payload.pop("options")
        if isinstance(options, list):
            parsed = {}
            for item in options:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or item.get("label"))
                # Preserve full rich format when segments exist
                segments = item.get("segments")
                text = item.get("text") or item.get("value") or ""
                if segments and isinstance(segments, list) and len(segments) > 0:
                    parsed[key] = {"text": text, "segments": segments}
                else:
                    parsed[key] = text
            qi.parsed_options = parsed
        else:
            qi.parsed_options = options
    if "answer" in payload:
        qi.parsed_answer = payload.pop("answer")
        qi.ai_answer_flag = False
        qi.answer_source = "manual"
        _new_ans = (qi.parsed_answer or "").strip()
        if _new_ans:
            # 人工保存答案 → 无论原状态如何，都设为 manual_filled
            # （manual_verified 也降级为 manual_filled，因为答案被修改了）
            qi.answer_status = "manual_filled"
        else:
            qi.answer_status = "missing"
    if "analysis" in payload:
        qi.parsed_analysis = payload.pop("analysis")

    # ── Multi-blank choice handling ──
    # When the question is or becomes multi_blank_choice:
    # - parsed_options must be None (blank groups live in parsed_content)
    # - If flat options were provided, rebuild blank_option_groups from them
    is_or_becomes_multi = (
        payload.get("question_type") == "multi_blank_choice"
        or qi.question_type == "multi_blank_choice"
    )
    if is_or_becomes_multi:
        qi.parsed_options = None
        # Rebuild blank_option_groups when options were provided in the payload
        if _options_val is not None:
            from app.features.multi_blank_choice import (
                build_blank_option_groups,
                extract_blank_slots,
            )
            stem = (qi.parsed_content or {}).get("text", "")
            slot_ids = extract_blank_slots(stem)
            if slot_ids and len(slot_ids) >= 2:
                content = dict(qi.parsed_content or {})
                groups = build_blank_option_groups(slot_ids, _options_val)
                if groups:
                    content["blank_option_groups"] = groups
                    qi.parsed_content = content

    # Legacy subject → subject_id conversion
    if "subject" in payload and "subject_id" not in payload:
        from app.services.admin_subject_service import resolve_subject_id
        resolved = await resolve_subject_id(db, payload.pop("subject"))
        if resolved is not None:
            payload["subject_id"] = resolved
    elif "subject" in payload:
        payload.pop("subject")  # discard legacy alias when subject_id also provided

    # ── 防误操作：答案为空时不可标记为已验证 ──
    if payload.get("answer_status") == "manual_verified":
        _current_answer = (qi.parsed_answer or "").strip()
        if not _current_answer:
            raise ValueError("答案为空，无法确认为正确")

    for field in (
        "subject_id",
        "question_type",
        "raw_data",
        "parsed_content",
        "parsed_options",
        "parsed_answer",
        "parsed_analysis",
        "review_note",
        # ── 导入审核定位与答案状态字段 ──
        "source_question_no",
        "source_question_label",
        "source_image_seq",
        "source_image_name",
        "source_page_start",
        "source_page_end",
        "source_order_index",
        "raw_text_preview",
        "answer_status",
        "answer_source",
        "answer_confidence",
        "review_priority",
    ):
        if field in payload:
            setattr(qi, field, payload[field])
    await db.flush()
    await db.refresh(qi)
    return AdminImportQuestionItem.model_validate(qi)


async def approve_import_question(db: AsyncSession, import_id: int, operator_id: int) -> AdminImportQuestionItem:
    # 行级锁：并发审核同一 import_id 时，第二个请求会阻塞到第一个提交，
    # 读到已发布的 question_id 后抛错，杜绝重复发布。
    result = await db.execute(
        select(QuestionImport)
        .where(QuestionImport.id == import_id)
        .with_for_update()
    )
    qi = result.scalar_one_or_none()
    if qi is None:
        raise ValueError("导入题目不存在")
    if qi.status == "published" or qi.question_id is not None:
        raise ValueError("已发布题目不可重复审核")

    # Re-compute visual option blocking from current DB state
    await _ensure_no_option_visual_blocking(qi)

    qi.status = "approved"
    qi.reject_reason = None
    qi.reviewed_by = operator_id
    qi.reviewed_at = utcnow()

    # 审核即发布：写入 questions 正式题库
    from app.features.question_publish_service import publish_single_question

    pub_result = await publish_single_question(db, qi)
    if pub_result["status"] == "duplicate":
        qi.status = "published"
        qi.question_id = pub_result["question_id"]
    elif pub_result["status"] == "failed":
        logger.warning(
            "Auto-publish failed for import %d: %s (rolling back approval)",
            import_id, pub_result.get("reason"),
        )
        qi.status = "pending"  # 回滚状态，保留在审核队列等待修复后重试
        qi.reviewed_by = None
        qi.reviewed_at = None
        raise ValueError(
            f"题目数据不完整，无法发布到题库：{pub_result.get('reason', '未知错误')}"
        )

    await db.flush()
    await db.refresh(qi)
    return AdminImportQuestionItem.model_validate(qi)


async def batch_complete_import_questions(
    db: AsyncSession,
    import_ids: list[int],
    fields: list[str],
    strategy: str,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> dict:
    """批量 AI 补全导入题目。"""
    if len(import_ids) > 50:
        raise ValueError("单次批量补全最多支持 50 条")
    if not fields:
        raise ValueError("请选择至少一个补全字段")
    if strategy not in ("fill_empty", "force_overwrite"):
        raise ValueError("strategy 仅支持 fill_empty 或 force_overwrite")

    await ensure_ai_parse_allowed(db, operator, request)
    from app.services.admin_ai_settings_service import is_super_admin
    _skip_budget = await is_super_admin(db, operator)
    result = await question_pipeline.batch_complete_questions(
        db, operator.id, import_ids, fields, strategy, skip_budget_check=_skip_budget,
    )

    await write_admin_audit(
        db,
        operator,
        "import.batch_complete",
        "question_import",
        f"ids={import_ids}",
        severity="important",
        detail={
            "import_ids": import_ids,
            "fields": fields,
            "strategy": strategy,
            "result": {k: result[k] for k in ("total", "succeeded", "failed", "skipped")},
        },
        request=request,
    )
    await db.commit()
    return result


async def reject_import_question(db: AsyncSession, import_id: int, operator_id: int, reason: str | None = None) -> AdminImportQuestionItem:
    qi = await _get_import_question(db, import_id)
    if qi.status == "published" or qi.question_id is not None:
        raise ValueError("已发布题目不可驳回")
    qi.status = "rejected"
    qi.reject_reason = reason
    qi.review_note = reason or qi.review_note
    qi.reviewed_by = operator_id
    qi.reviewed_at = utcnow()
    await db.flush()
    await db.refresh(qi)
    return AdminImportQuestionItem.model_validate(qi)


async def approve_import_batch(db: AsyncSession, batch_id: str, operator_id: int) -> int:
    records = await _get_batch_records(db, batch_id, statuses={"pending", "rejected"}, for_update=True)
    now = utcnow()
    from app.features.question_publish_service import publish_single_question

    count = 0
    for qi in records:
        if qi.question_id is None:
            # Skip items with visual option blocking (log, don't fail batch)
            visual_blocking = _check_option_visual_blocking(qi.parsed_content, qi.parsed_options)
            if visual_blocking:
                logger.info(
                    "Batch approve skipped import %d: visual option blocking %s",
                    qi.id, visual_blocking,
                )
                continue

            qi.status = "approved"
            qi.reject_reason = None
            qi.reviewed_by = operator_id
            qi.reviewed_at = now

            # 批量审核即批量发布
            try:
                pub = await publish_single_question(db, qi)
                if pub["status"] == "duplicate":
                    qi.status = "published"
                    qi.question_id = pub["question_id"]
                elif pub["status"] == "failed":
                    logger.warning(
                        "Batch auto-publish failed for import %d: %s (skipped)",
                        qi.id, pub.get("reason"),
                    )
                    qi.status = "pending"  # 回滚，留在审核队列
                    qi.reviewed_by = None
                    qi.reviewed_at = None
            except Exception as exc:
                logger.warning(
                    "Batch auto-publish error for import %d: %s", qi.id, exc,
                )
                qi.status = "pending"  # 异常也回滚
                qi.reviewed_by = None
                qi.reviewed_at = None

            count += 1

    await db.flush()
    return count


async def approve_low_risk_questions(db: AsyncSession, batch_id: str, operator_id: int) -> dict:
    """批量通过低风险题目：只通过 risk_level == "low" 且无高风险标记的待审核题。

    Returns:
        {"affected_count": int, "skipped_count": int, "skipped_reasons": list[str]}
    """
    from app.features.question_publish_service import publish_single_question

    records = await _get_batch_records(db, batch_id, statuses={"pending"}, for_update=True)
    now = utcnow()

    affected = 0
    skipped = 0
    skipped_reasons: list[str] = []

    for qi in records:
        risk = derive_import_risk(
            qi.ai_metadata,
            ai_answer_flag=qi.ai_answer_flag,
            parsed_answer=qi.parsed_answer,
        )
        rl = risk["risk_level"]
        flags = risk["risk_flags"]

        # 低风险条件
        is_low_risk = (
            rl == "low"
            and not qi.ai_answer_flag
            and bool(qi.parsed_answer and qi.parsed_answer.strip())
            and "math_low_confidence" not in flags
            and "complex_formula_requires_review" not in flags
            and "table_low_confidence" not in flags
            and "code_symbol_risk" not in flags
            and "option_structure_corruption" not in flags
        )

        # Visual option blocking — re-computed from current DB state
        visual_blocking = _check_option_visual_blocking(qi.parsed_content, qi.parsed_options)
        if visual_blocking:
            is_low_risk = False

        if not is_low_risk:
            skipped += 1
            if visual_blocking:
                skipped_reasons.append(f"#{qi.id}: 图片选项问题 ({'、'.join(visual_blocking)})")
            elif rl == "high":
                skipped_reasons.append(f"#{qi.id}: 高风险")
            elif qi.ai_answer_flag:
                skipped_reasons.append(f"#{qi.id}: AI 答案")
            elif not qi.parsed_answer or not qi.parsed_answer.strip():
                skipped_reasons.append(f"#{qi.id}: 答案缺失")
            else:
                skipped_reasons.append(f"#{qi.id}: 需检查")
            continue

        if qi.question_id is None:
            qi.status = "approved"
            qi.reject_reason = None
            qi.reviewed_by = operator_id
            qi.reviewed_at = now

            try:
                pub = await publish_single_question(db, qi)
                if pub["status"] == "duplicate":
                    qi.status = "published"
                    qi.question_id = pub["question_id"]
                elif pub["status"] == "failed":
                    logger.warning(
                        "Low-risk approve publish failed for import %d: %s (rolled back)",
                        qi.id, pub.get("reason"),
                    )
                    qi.status = "pending"
                    qi.reviewed_by = None
                    qi.reviewed_at = None
                    skipped += 1
                    skipped_reasons.append(f"#{qi.id}: 发布失败({pub.get('reason', '未知')})")
                    continue
            except Exception as exc:
                logger.warning(
                    "Low-risk approve publish error for import %d: %s", qi.id, exc,
                )
                qi.status = "pending"
                qi.reviewed_by = None
                qi.reviewed_at = None
                skipped += 1
                affected -= 1 if affected > 0 else 0
                skipped_reasons.append(f"#{qi.id}: 发布异常({exc})")
                continue

            affected += 1

    await db.flush()

    # 最多返回 20 条跳过原因，避免响应体过大
    if len(skipped_reasons) > 20:
        skipped_reasons = skipped_reasons[:20]
        skipped_reasons.append(f"... 及其他 {skipped - 20} 条跳过原因")

    return {
        "affected_count": affected,
        "skipped_count": skipped,
        "skipped_reasons": skipped_reasons,
    }


async def reject_import_batch(db: AsyncSession, batch_id: str, operator_id: int, reason: str | None = None) -> int:
    records = await _get_batch_records(db, batch_id, statuses={"pending", "approved"})
    now = utcnow()
    for qi in records:
        if qi.question_id is None:
            qi.status = "rejected"
            qi.reject_reason = reason
            qi.review_note = reason or qi.review_note
            qi.reviewed_by = operator_id
            qi.reviewed_at = now
    await db.flush()
    return len(records)


async def delete_import_question(db: AsyncSession, import_id: int) -> int:
    qi = await _get_import_question(db, import_id)
    if qi.status == "published" or qi.question_id is not None:
        raise ValueError("已发布题目不可删除")
    await db.delete(qi)
    await db.flush()
    return 1


async def delete_import_batch(db: AsyncSession, batch_id: str) -> int:
    records = await _get_batch_records(db, batch_id)
    if any(qi.status == "published" or qi.question_id is not None for qi in records):
        raise ValueError("已发布批次不可删除")
    result = await db.execute(delete(QuestionImport).where(QuestionImport.batch_id == batch_id))
    await db.flush()
    return int(result.rowcount or 0)


async def complete_import_question(
    db: AsyncSession,
    import_id: int,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> dict:
    qi = await _get_import_question(db, import_id)
    if qi.status != "pending":
        raise ValueError("仅支持对 pending 记录使用 AI 补全")
    await ensure_ai_parse_allowed(db, operator, request)

    result = await question_pipeline.complete_import(db, operator.id, import_id)
    refreshed = await _get_import_question(db, import_id)
    await write_admin_audit(
        db,
        operator,
        "import.complete",
        "question_import",
        str(import_id),
        severity="important",
        detail={
            "import_id": import_id,
            "batch_id": refreshed.batch_id,
            "missing": result.get("missing", []),
            "from_fallback": result.get("from_fallback", False),
        },
        request=request,
    )
    return {
        "missing": result.get("missing", []),
        "from_fallback": result.get("from_fallback", False),
        "ai_metadata": result.get("ai_metadata", {}),
        "tokens_used": result.get("tokens_used", 0),
        "duration_ms": result.get("duration_ms", 0),
        "item": AdminImportQuestionItem.model_validate(refreshed),
    }


async def create_enrich_task(
    db: AsyncSession,
    batch_id: str,
    operator: AdminPrincipal,
    request: Request | None = None,
) -> AdminImportEnrichResponse:
    summary_result = await db.execute(_batch_summary_query([QuestionImport.batch_id == batch_id]))
    summary_row = summary_result.first()
    if not summary_row:
        raise ValueError("导入批次不存在")
    await ensure_ai_parse_allowed(db, operator, request)

    task_id = f"admin-ai-{uuid4().hex}"
    now = utcnow()
    payload = {
        "task_id": task_id,
        "batch_id": batch_id,
        "status": "pending",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "total_count": int(summary_row.total_count or 0),
        "processed_count": 0,
        "error_message": None,
    }
    await cache.set(_task_key(task_id), payload, ttl=_TASK_TTL_SECONDS)
    await cache.set(_batch_task_key(batch_id), task_id, ttl=_TASK_TTL_SECONDS)
    await write_admin_audit(
        db,
        operator,
        "import.enrich",
        "import_batch",
        batch_id,
        severity="important",
        detail={"task_id": task_id, "batch_id": batch_id, "total_count": payload["total_count"]},
        request=request,
    )
    return AdminImportEnrichResponse(task_id=task_id, batch_id=batch_id, status="pending", created_at=now)


async def get_enrich_status(batch_id: str) -> dict:
    task_id = await cache.get(_batch_task_key(batch_id))
    if not task_id:
        raise ValueError("AI任务不存在")
    payload = await cache.get(_task_key(task_id))
    if not payload:
        raise ValueError("AI任务不存在")
    return payload


async def get_import_question_detail(
    db: AsyncSession,
    import_id: int,
) -> AdminImportQuestionItem:
    """Get full detail for a single import question (includes large fields)."""
    qi = await _get_import_question(db, import_id)
    item = AdminImportQuestionItem.model_validate(qi)
    _apply_risk_to_item(item)
    # ── 历史数据兜底 ──
    if not item.source_question_no and qi.raw_data:
        fallback = _fallback_source_question_no(qi.raw_data)
        if fallback:
            item.source_question_no = fallback
    if not item.raw_text_preview and qi.raw_data:
        _raw_text = (
            qi.raw_data.get("raw_text")
            or qi.raw_data.get("raw_question_text")
            or qi.raw_data.get("text")
        )
        if _raw_text:
            item.raw_text_preview = str(_raw_text)[:200]
    # source_locator 动态生成
    if not item.source_locator:
        source_page = getattr(qi, "source_page_start", None) or resolve_source_page(qi.raw_data)
        source_page_end = getattr(qi, "source_page_end", None) or resolve_source_page_end(qi.raw_data)
        item.source_locator = build_source_locator(
            source_image_seq=getattr(qi, "source_image_seq", None) or (qi.raw_data or {}).get("source_image_seq"),
            source_image_name=getattr(qi, "source_image_name", None) or qi.source_file,
            source_file=qi.source_file,
            source_page_start=source_page,
            source_page_end=source_page_end,
        )
    return item


def _question_conditions(
    status: str | None,
    batch_id: str | None,
    source_type: str | None,
    keyword: str | None,
    subject_id: int | None = None,
) -> list:
    conditions = []
    if status:
        conditions.append(QuestionImport.status == status)
    if batch_id:
        conditions.append(QuestionImport.batch_id == batch_id)
    if subject_id is not None:
        conditions.append(QuestionImport.subject_id == subject_id)
    if source_type:
        conditions.append(QuestionImport.source_type == source_type)
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(
            or_(
                QuestionImport.batch_id.ilike(pattern),
                QuestionImport.source_file.ilike(pattern),
                QuestionImport.source_question_no.ilike(pattern),
                QuestionImport.parsed_answer.ilike(pattern),
                QuestionImport.parsed_analysis.ilike(pattern),
                QuestionImport.parsed_content["text"].as_string().ilike(pattern),
                cast(QuestionImport.parsed_options, String).ilike(pattern),
            )
        )
    return conditions


async def _get_import_question(db: AsyncSession, import_id: int) -> QuestionImport:
    result = await db.execute(select(QuestionImport).where(QuestionImport.id == import_id))
    qi = result.scalar_one_or_none()
    if qi is None:
        raise ValueError("导入题目不存在")
    return qi


async def _get_batch_records(
    db: AsyncSession,
    batch_id: str,
    statuses: set[str] | None = None,
    for_update: bool = False,
) -> list[QuestionImport]:
    conditions = [QuestionImport.batch_id == batch_id]
    if statuses:
        conditions.append(QuestionImport.status.in_(statuses))
    query = select(QuestionImport).where(*conditions).order_by(QuestionImport.id.asc())
    if for_update:
        # 审核路径行锁：防止与单条 approve / 另一批量 approve 并发重复发布
        query = query.with_for_update()
    result = await db.execute(query)
    records = list(result.scalars().all())
    if not records:
        raise ValueError("导入批次不存在")
    return records
def _batch_conditions(status: str | None, source_type: str | None, keyword: str | None) -> list:
    conditions = []
    if status:
        conditions.append(QuestionImport.status == status)
    if source_type:
        conditions.append(QuestionImport.source_type == source_type)
    if keyword:
        pattern = f"%{keyword}%"
        conditions.append(or_(QuestionImport.batch_id.ilike(pattern), QuestionImport.source_file.ilike(pattern)))
    return conditions


def _batch_summary_query(conditions: list):
    return (
        select(
            QuestionImport.batch_id.label("batch_id"),
            func.min(QuestionImport.source_type).label("source_type"),
            func.min(QuestionImport.source_file).label("source_file"),
            func.count().label("total_count"),
            func.sum(case((QuestionImport.status == "pending", 1), else_=0)).label("pending_count"),
            func.sum(case((QuestionImport.status == "approved", 1), else_=0)).label("approved_count"),
            func.sum(case((QuestionImport.status == "rejected", 1), else_=0)).label("rejected_count"),
            func.sum(case((QuestionImport.status == "published", 1), else_=0)).label("published_count"),
            func.sum(case((QuestionImport.ai_generated.is_(True), 1), else_=0)).label("ai_count"),
            func.min(QuestionImport.created_at).label("created_at"),
            func.max(QuestionImport.updated_at).label("updated_at"),
        )
        .where(*conditions)
        .group_by(QuestionImport.batch_id)
    )


def _row_get(data, key: str):
    if isinstance(data, dict):
        return data[key]
    try:
        return data[key]
    except TypeError:
        return getattr(data, key)


def _batch_row_to_dict(row) -> dict:
    data = row._mapping if hasattr(row, "_mapping") else row
    return {
        "batch_id": _row_get(data, "batch_id"),
        "source_type": _row_get(data, "source_type"),
        "source_file": _row_get(data, "source_file"),
        "total_count": int(_row_get(data, "total_count") or 0),
        "pending_count": int(_row_get(data, "pending_count") or 0),
        "approved_count": int(_row_get(data, "approved_count") or 0),
        "rejected_count": int(_row_get(data, "rejected_count") or 0),
        "published_count": int(_row_get(data, "published_count") or 0),
        "ai_count": int(_row_get(data, "ai_count") or 0),
        "created_at": _row_get(data, "created_at"),
        "updated_at": _row_get(data, "updated_at"),
    }


def _task_key(task_id: str) -> str:
    return f"admin:ai:task:{task_id}"


def _batch_task_key(batch_id: str) -> str:
    return f"admin:ai:batch:{batch_id}:task"


async def list_subject_options(db: AsyncSession) -> list[dict]:
    """返回活跃科目列表 [{id, code, name, path, level, parent_id, has_children, is_leaf}]，供下拉框使用。"""
    from app.models.admin import Subject
    result = await db.execute(
        select(Subject.id, Subject.code, Subject.name, Subject.path, Subject.level, Subject.parent_id)
        .where(Subject.is_active.is_(True))
        .order_by(Subject.level.asc(), Subject.sort_order.asc(), Subject.id.asc())
    )
    rows = result.all()
    if rows:
        # 计算 parent_ids 集合（基于 parent_id 字段）
        parent_ids = {row.parent_id for row in rows if row.parent_id is not None}

        def _has_children_by_path(current_id: int) -> bool:
            current = str(current_id)
            for row in rows:
                if not row.path:
                    continue
                parts = [p for p in str(row.path).split("/") if p]
                if current in parts[:-1]:
                    return True
            return False

        result_list = []
        for row in rows:
            has_children = row.id in parent_ids or _has_children_by_path(row.id)
            result_list.append({
                "id": row.id,
                "code": row.code,
                "name": row.name,
                "path": row.path,
                "level": row.level,
                "parent_id": row.parent_id,
                "has_children": has_children,
                "is_leaf": not has_children,
            })
        return result_list

    # Fallback: extract distinct subject_ids from existing import data
    from app.models.admin import Subject
    from app.models.question_import import QuestionImport
    fb = await db.execute(
        select(Subject.id, Subject.code, Subject.name)
        .join(QuestionImport, QuestionImport.subject_id == Subject.id)
        .where(QuestionImport.subject_id.is_not(None))
        .distinct()
        .order_by(Subject.code.asc())
    )
    return [{"id": row[0], "code": row[1], "name": row[2], "path": row[1], "level": 1} for row in fb.all()]

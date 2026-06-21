"""失败样本导出 — 从 question_imports 生成 acceptance case 模板。

导出内容限制：
- 不导出完整 PDF、完整图片或完整 raw_data。
- raw_data 截断至 2000 字符。
- expected_template 所有字段为空（禁止 AI 生成答案）。
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

# Maximum length for raw_data field in exported case
_MAX_RAW_DATA_LENGTH = 2000

# Maximum length for parsed_content field
_MAX_PARSED_LENGTH = 3000


def export_failure_case(question_import: dict) -> dict:
    """Export a single question_import item as acceptance case template.

    Args:
        question_import: dict representation of a question_imports row,
                         typically from the review queue query.

    Returns:
        Case template dict with empty expected fields (must be filled manually).
    """
    import_id = question_import.get("id", 0)
    case_id = _build_case_id(import_id)

    # Truncate raw_data — extract only the question region, not full document
    raw_data = question_import.get("raw_data") or {}
    truncated_raw = _truncate_raw_data(raw_data)

    # Build parsed content summary
    parsed_content = _build_parsed_summary(question_import)

    # Collect risk flags
    risk_flags = list(question_import.get("risk_flags") or [])

    # Collect failure types if available
    failure_types = list(question_import.get("failure_types") or [])

    # Build expected_template — ALL fields MUST be empty
    expected_template: dict[str, Any] = {
        "stem": "",
        "options": {
            "A": "",
            "B": "",
            "C": "",
            "D": "",
        },
        "answer": "",
        "analysis": "",
        "_note": "请人工补充 expected 正确答案，禁止使用 AI 生成",
    }

    case: dict[str, Any] = {
        "case_id": case_id,
        "source_file": _safe_filename(question_import.get("source_file")),
        "source_page": question_import.get("source_page"),
        "subject": question_import.get("subject"),
        "question_type": question_import.get("question_type"),
        "import_id": import_id,
        "raw_data": truncated_raw,
        "parsed_content": parsed_content,
        "risk_flags": risk_flags,
        "failure_types": failure_types,
        "expected_template": expected_template,
        "exported_at": date.today().isoformat(),
    }

    return case


def export_failure_cases_batch(
    question_imports: list[dict],
    failure_type_filter: str | None = None,
) -> list[dict]:
    """Export multiple question_import items as acceptance case templates.

    Args:
        question_imports: list of question_import dicts.
        failure_type_filter: optional failure type to filter by.

    Returns:
        List of case template dicts.
    """
    cases: list[dict] = []
    for item in question_imports:
        if failure_type_filter:
            item_failures = list(item.get("failure_types") or [])
            if failure_type_filter not in item_failures:
                continue
        cases.append(export_failure_case(item))
    return cases


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_case_id(import_id: int) -> str:
    """Generate a unique case ID from date and import_id."""
    today = date.today().strftime("%Y%m%d")
    return f"failure_{today}_{import_id}"


def _safe_filename(source_file: str | None) -> str:
    """Extract only the filename from a path, never the full path."""
    if not source_file:
        return ""
    return os.path.basename(source_file)


def _truncate_raw_data(raw_data: dict) -> dict:
    """Truncate raw_data to safe length, removing any full-file fields."""
    truncated: dict[str, Any] = {}

    for key, value in raw_data.items():
        # Skip fields that contain full file content
        if key in (
            "file_bytes", "image_bytes", "full_text", "pdf_content",
            "source_bytes", "raw_file",
        ):
            truncated[key] = f"<{key}: stripped for export>"
        elif isinstance(value, str):
            truncated[key] = value[:_MAX_RAW_DATA_LENGTH]
            if len(value) > _MAX_RAW_DATA_LENGTH:
                truncated[f"{key}_truncated"] = True
        elif isinstance(value, list) and len(value) > 20:
            # Only keep first 20 items for lists
            truncated[key] = value[:20]
            truncated[f"{key}_truncated"] = True
        else:
            truncated[key] = value

    return truncated


def _build_parsed_summary(question_import: dict) -> dict:
    """Extract parsed content summary without exposing full file content."""
    summary: dict[str, Any] = {}

    for field in ("stem", "options", "answer", "analysis", "question_type"):
        val = question_import.get(field) or question_import.get(f"parsed_{field}")
        if val is not None:
            if isinstance(val, str) and len(val) > _MAX_PARSED_LENGTH:
                summary[field] = val[:_MAX_PARSED_LENGTH]
                summary[f"{field}_truncated"] = True
            else:
                summary[field] = val

    return summary

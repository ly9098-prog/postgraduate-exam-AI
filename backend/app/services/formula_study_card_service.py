from __future__ import annotations

from fastapi import HTTPException

STUDY_CARD_TYPES: tuple[str, ...] = (
    "formula",
    "definition",
    "complexity",
    "protocol_rule",
    "key_conclusion",
    "confusable",
    "trap",
    "comparison",
)

STUDY_CARD_TYPE_META: dict[str, dict[str, str]] = {
    "formula": {"name": "公式", "short_name": "公式", "template": "standard"},
    "definition": {"name": "定义", "short_name": "定义", "template": "memory"},
    "complexity": {"name": "算法复杂度", "short_name": "复杂度", "template": "rule"},
    "protocol_rule": {"name": "协议字段 / 规则", "short_name": "协议规则", "template": "rule"},
    "key_conclusion": {"name": "高频结论", "short_name": "结论", "template": "memory"},
    "confusable": {"name": "易混概念", "short_name": "易混", "template": "contrast"},
    "trap": {"name": "典型陷阱", "short_name": "陷阱", "template": "trap"},
    "comparison": {"name": "对比卡", "short_name": "对比", "template": "contrast"},
}

TEMPLATE_TYPES: tuple[str, ...] = ("standard", "memory", "rule", "contrast", "trap")
TEMPLATE_TYPE_META: dict[str, dict[str, str]] = {
    "standard": {"name": "标准卡", "description": "公式、结论等通用内容"},
    "memory": {"name": "记忆卡", "description": "定义、高频结论，突出一句话记忆"},
    "rule": {"name": "规则卡", "description": "复杂度、协议字段和规则条件"},
    "contrast": {"name": "对比卡", "description": "并列比较易混概念或机制"},
    "trap": {"name": "陷阱卡", "description": "突出错误直觉、边界和考试陷阱"},
}


def validate_study_card_type(value: str | None) -> str:
    normalized = str(value or "formula").strip().lower()
    if normalized not in STUDY_CARD_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"无效的 study_card_type: '{normalized}'",
        )
    return normalized


def validate_template_type(value: str | None) -> str:
    normalized = str(value or "standard").strip().lower()
    if normalized not in TEMPLATE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"无效的 template_type: '{normalized}'",
        )
    return normalized


def default_template_for(study_card_type: str) -> str:
    return STUDY_CARD_TYPE_META.get(study_card_type, {}).get("template", "standard")


def public_card_type_catalog() -> dict[str, list[dict[str, str]]]:
    return {
        "study_card_types": [
            {"key": key, **STUDY_CARD_TYPE_META[key]} for key in STUDY_CARD_TYPES
        ],
        "template_types": [
            {"key": key, **TEMPLATE_TYPE_META[key]} for key in TEMPLATE_TYPES
        ],
    }

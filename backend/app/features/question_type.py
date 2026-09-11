"""题型领域定义 — 后端唯一权威来源。

题型是领域枚举，与答案结构、选项结构、判题逻辑和导入流水线绑定，
不是运行时可配置字典。

使用方式
--------
- **标准值校验**（用于普通 API 创建/编辑）：调用 ``validate_question_type()``
- **导入/OCR/AI 值规范化**（用于 pipeline）：调用 ``normalize_question_type()``
- **元数据接口**（用于前端下拉）：``get_question_type_metadata()``

规则
----
- 枚举成员 = 数据库允许的唯一值
- 未知/无法识别值 → 不猜测、不回退，返回明确的 None/错误
- ``unknown`` 不是题型值
- ``choice``、``fill``、``judgement`` 等不是题型值（只是别名）
"""

from __future__ import annotations

import enum
from typing import Any

# ══════════════════════════════════════════════════════════════════════════════
# QuestionType 枚举
# ══════════════════════════════════════════════════════════════════════════════


class QuestionType(enum.StrEnum):
    """标准题型枚举。

    成员值是数据库存储的规范 code。
    不包含 ``unknown``、``choice``、``fill``、``judgement`` 等非标准值。
    """

    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    FILL_BLANK = "fill_blank"
    MULTI_BLANK_CHOICE = "multi_blank_choice"
    SUBJECTIVE = "subjective"


# 方便直接引用字符串常量（兼容现有代码风格）
QT_SINGLE_CHOICE = QuestionType.SINGLE_CHOICE.value
QT_MULTIPLE_CHOICE = QuestionType.MULTIPLE_CHOICE.value
QT_TRUE_FALSE = QuestionType.TRUE_FALSE.value
QT_FILL_BLANK = QuestionType.FILL_BLANK.value
QT_MULTI_BLANK_CHOICE = QuestionType.MULTI_BLANK_CHOICE.value
QT_SUBJECTIVE = QuestionType.SUBJECTIVE.value

# 规范 code 集合（用于快速检查）
CANONICAL_TYPES: frozenset[str] = frozenset(member.value for member in QuestionType)


# ══════════════════════════════════════════════════════════════════════════════
# 题型元数据
# ══════════════════════════════════════════════════════════════════════════════


QUESTION_TYPE_LABELS: dict[QuestionType, str] = {
    QuestionType.SINGLE_CHOICE: "单选题",
    QuestionType.MULTIPLE_CHOICE: "多选题",
    QuestionType.TRUE_FALSE: "判断题",
    QuestionType.FILL_BLANK: "填空题",
    QuestionType.MULTI_BLANK_CHOICE: "多空选择题",
    QuestionType.SUBJECTIVE: "问答题",
}

# 各题型的能力/特征（用于前端的条件渲染和校验逻辑）
QUESTION_TYPE_CAPABILITIES: dict[QuestionType, dict[str, Any]] = {
    QuestionType.SINGLE_CHOICE: {
        "has_options": True,
        "answer_mode": "single_letter",
        "allows_multi_blank": False,
        "allows_multiple_answers": False,
    },
    QuestionType.MULTIPLE_CHOICE: {
        "has_options": True,
        "answer_mode": "multiple_letters",
        "allows_multi_blank": False,
        "allows_multiple_answers": True,
    },
    QuestionType.TRUE_FALSE: {
        "has_options": False,
        "answer_mode": "true_false",
        "allows_multi_blank": False,
        "allows_multiple_answers": False,
    },
    QuestionType.FILL_BLANK: {
        "has_options": False,
        "answer_mode": "text",
        "allows_multi_blank": False,
        "allows_multiple_answers": False,
    },
    QuestionType.MULTI_BLANK_CHOICE: {
        "has_options": True,
        "answer_mode": "multi_blank",
        "allows_multi_blank": True,
        "allows_multiple_answers": True,
    },
    QuestionType.SUBJECTIVE: {
        "has_options": False,
        "answer_mode": "free_text",
        "allows_multi_blank": False,
        "allows_multiple_answers": False,
    },
}

# 排序值（用于元数据接口稳定排序）
QUESTION_TYPE_SORT_ORDER: dict[QuestionType, int] = {
    QuestionType.SINGLE_CHOICE: 10,
    QuestionType.MULTIPLE_CHOICE: 20,
    QuestionType.TRUE_FALSE: 30,
    QuestionType.FILL_BLANK: 40,
    QuestionType.MULTI_BLANK_CHOICE: 50,
    QuestionType.SUBJECTIVE: 60,
}


# ══════════════════════════════════════════════════════════════════════════════
# 导入/OCR/AI 别名映射
# ══════════════════════════════════════════════════════════════════════════════
# 只用于导入端（pipeline、text import、AI 返回值、OCR），
# 不用于普通 API 校验。
# 规范化规则：trim → lowercase → hyphen-to-underscore → collapse-whitespace


def _normalize_alias_key(input: str) -> str:
    """标准化别名键用于查找。"""
    return (
        input.strip()
        .lower()
        .replace("-", "_")
        .replace("/", "_")
        .replace(" ", "")
        .replace("　", "")
    )


_RAW_ALIAS_MAP: dict[str, str] = {
    # 中文别名（与 QuestionNormalizer._TYPE_ALIAS_MAP 对齐）
    "单选": QT_SINGLE_CHOICE,
    "单选题": QT_SINGLE_CHOICE,
    "单项选择": QT_SINGLE_CHOICE,
    "单项选择题": QT_SINGLE_CHOICE,
    "多选": QT_MULTIPLE_CHOICE,
    "多选题": QT_MULTIPLE_CHOICE,
    "多项选择": QT_MULTIPLE_CHOICE,
    "多项选择题": QT_MULTIPLE_CHOICE,
    "判断": QT_TRUE_FALSE,
    "判断题": QT_TRUE_FALSE,
    "对错": QT_TRUE_FALSE,
    "对错题": QT_TRUE_FALSE,
    "是非题": QT_TRUE_FALSE,
    "填空": QT_FILL_BLANK,
    "填空题": QT_FILL_BLANK,
    "多空选择": QT_MULTI_BLANK_CHOICE,
    "多空选择题": QT_MULTI_BLANK_CHOICE,
    "主观": QT_SUBJECTIVE,
    "主观题": QT_SUBJECTIVE,
    "简答": QT_SUBJECTIVE,
    "简答题": QT_SUBJECTIVE,
    "论述": QT_SUBJECTIVE,
    "计算": QT_SUBJECTIVE,
    # 英文别名
    "choice": QT_SINGLE_CHOICE,
    "single": QT_SINGLE_CHOICE,
    "singlechoice": QT_SINGLE_CHOICE,
    "multiple": QT_MULTIPLE_CHOICE,
    "multi_choice": QT_MULTIPLE_CHOICE,
    "multiplechoice": QT_MULTIPLE_CHOICE,
    "judge": QT_TRUE_FALSE,
    "judgement": QT_TRUE_FALSE,
    "judgment": QT_TRUE_FALSE,
    "truefalse": QT_TRUE_FALSE,
    "tf": QT_TRUE_FALSE,
    "t_f": QT_TRUE_FALSE,
    "true_false": QT_TRUE_FALSE,
    "fill": QT_FILL_BLANK,
    "blank": QT_FILL_BLANK,
    "fillblank": QT_FILL_BLANK,
}

# 预计算标准化后的别名映射
_ALIAS_MAP: dict[str, str] = {}
for raw, code in _RAW_ALIAS_MAP.items():
    _ALIAS_MAP[_normalize_alias_key(raw)] = code
# 自映射（标准 code 也是自己的别名）
for code in CANONICAL_TYPES:
    _ALIAS_MAP[_normalize_alias_key(code)] = code


# ══════════════════════════════════════════════════════════════════════════════
# 标准值校验（用于普通 API）
# ══════════════════════════════════════════════════════════════════════════════


def validate_question_type(value: str | None) -> str:
    """严格校验题型值。

    只接受标准 QuestionType code。
    非标准值抛出 ValueError。

    Returns:
        标准 code。

    Raises:
        ValueError: 值为 None、空或非标准 code。
    """
    if not value:
        raise ValueError(f"题型不能为空，收到: {value!r}")
    if value in CANONICAL_TYPES:
        return value
    raise ValueError(f"非标准题型值: {value!r}。标准值: {sorted(CANONICAL_TYPES)}")


# ══════════════════════════════════════════════════════════════════════════════
# 导入/OCR/AI 值规范化（用于 pipeline 和导入入口）
# ══════════════════════════════════════════════════════════════════════════════


def normalize_question_type(
    value: str | None,
) -> tuple[str | None, list[str]]:
    """规范化导入/OCR/AI 的题型值。

    处理别名、大小写、连字符、空白等差异。

    Args:
        value: 原始题型值（可能为 None、空字符串、中文、英文别名等）。

    Returns:
        (normalized_code, warnings)：
        - normalized_code: 标准 code；无法识别时为 None。
        - warnings: 处理过程中的警告列表。
    """
    if not value:
        return None, ["题型值为空"]

    raw = str(value).strip()
    if not raw:
        return None, ["题型值为空"]

    normalized = _normalize_alias_key(raw)
    code = _ALIAS_MAP.get(normalized)

    if code is not None:
        if normalized != code:
            return code, [f"题型别名 '{value}' → 标准 code '{code}'"]
        return code, []

    return None, [f"无法识别的题型值: {value!r}"]


# ══════════════════════════════════════════════════════════════════════════════
# 元数据
# ══════════════════════════════════════════════════════════════════════════════


def get_question_type_metadata_items() -> list[dict[str, Any]]:
    """获取题型元数据列表（按 sort_order 排序）。

    用于元数据接口（GET /metadata/question-types）。
    """
    sorted_types = sorted(QuestionType, key=lambda qt: QUESTION_TYPE_SORT_ORDER[qt])
    return [
        {
            "code": qt.value,
            "label": QUESTION_TYPE_LABELS[qt],
            "sort_order": QUESTION_TYPE_SORT_ORDER[qt],
            "capabilities": QUESTION_TYPE_CAPABILITIES[qt],
        }
        for qt in sorted_types
    ]


# ══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════════


def is_canonical(value: str | None) -> bool:
    """判断值是否为标准题型 code。"""
    return value in CANONICAL_TYPES if value else False


def is_multi_blank_type(value: str | None) -> bool:
    """判断是否为多空选择题。"""
    return value == QT_MULTI_BLANK_CHOICE


def is_multiple_choice_type(value: str | None) -> bool:
    """判断是否为多选题。"""
    return value == QT_MULTIPLE_CHOICE


def is_true_false_type(value: str | None) -> bool:
    """判断是否为判断题（只认标准 code）。"""
    return value == QT_TRUE_FALSE


def is_choice_type(value: str | None) -> bool:
    """判断是否为单项选择题。"""
    return value == QT_SINGLE_CHOICE

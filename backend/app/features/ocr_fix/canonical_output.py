"""Canonical Output Layer — 统一输出兼容层。

将任意模型返回内容（纯文本、Markdown、JSON、JSON 代码块、混合格式）
统一转换为标准纯文本格式。

设计原则：
- Prompt 负责引导模型输出纯文本（优化项）
- Canonical Layer 负责兼容所有实际输出格式（保障项）
- JSON 不再直接判定失败，优先尝试 json_to_text 提取
- 只有无法提取有效内容时才触发 fallback
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 输出类型常量
OUTPUT_PLAIN = "plain"
OUTPUT_MARKDOWN = "markdown"
OUTPUT_JSON = "json"
OUTPUT_JSON_CODEBLOCK = "json_codeblock"
OUTPUT_MIXED = "mixed"
OUTPUT_EMPTY = "empty"

_JSON_CODE_BLOCK_RE = re.compile(r"^```json\s*\n(.*?)\n```\s*$", re.DOTALL)
_MARKDOWN_CODE_BLOCK_RE = re.compile(r"^```\w*\s*\n(.*?)\n```\s*$", re.DOTALL)


def _looks_like_json(text: str) -> bool:
    """快速判断文本是否看起来像 JSON。"""
    t = text.strip()
    return (t.startswith("{") and t.endswith("}")) or (t.startswith("[") and t.endswith("]"))


def _detect_output_type(text: str) -> str:
    """检测模型输出的类型。"""
    stripped = text.strip()
    if not stripped:
        return OUTPUT_EMPTY

    if _JSON_CODE_BLOCK_RE.match(stripped):
        return OUTPUT_JSON_CODEBLOCK

    if _looks_like_json(stripped):
        return OUTPUT_JSON

    if _MARKDOWN_CODE_BLOCK_RE.match(stripped):
        return OUTPUT_MARKDOWN

    return OUTPUT_PLAIN


def _json_to_text(parsed: Any) -> str | None:
    """将 JSON 解析结果转换为纯文本。

    支持常见 AI 输出结构：
    - {"corrected_text": "..."} / {"text": "..."} / {"content": "..."} 等单值结构
    - {"option": [{"text": "..."}, ...]} 选项数组结构
    - [{"text": "..."}, ...] 纯列表结构
    - 兜底：提取所有较长的字符串值拼接
    """
    if isinstance(parsed, dict):
        # 1. 已知单值键
        for key in ("corrected_text", "corrected", "fixed_text", "text", "output", "content"):
            val = parsed.get(key)
            if val and isinstance(val, str) and len(val) > 10:
                return val.strip()

        # 2. 选项数组 {"option": [{"text": "..."}, ...]}
        for key in ("option", "options", "choices"):
            items = parsed.get(key)
            if isinstance(items, list) and items:
                texts = _extract_list_texts(items)
                if texts:
                    return "\n".join(texts)

        # 3. 兜底：提取所有较长的字符串值
        all_texts = _extract_dict_fallback(parsed)
        if all_texts:
            return "\n".join(all_texts)

    elif isinstance(parsed, list):
        texts = _extract_list_texts(parsed)
        if texts:
            return "\n".join(texts)

    return None


def _extract_list_texts(items: list[Any]) -> list[str]:
    """从列表中提取文本项。"""
    texts: list[str] = []
    for item in items:
        if isinstance(item, dict):
            txt = item.get("text") or item.get("content") or ""
            if txt:
                texts.append(txt.strip())
        elif isinstance(item, str) and item.strip():
            texts.append(item.strip())
    return texts


def _extract_dict_fallback(parsed: dict[str, Any]) -> list[str]:
    """兜底提取：遍历所有字典值，收集较长的字符串。"""
    all_texts: list[str] = []
    for v in parsed.values():
        if isinstance(v, str) and len(v) > 5:
            all_texts.append(v.strip())
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    txt = item.get("text") or item.get("content") or ""
                    if txt:
                        all_texts.append(txt.strip())
                elif isinstance(item, str) and item.strip():
                    all_texts.append(item.strip())
    return all_texts


def _strip_markdown_code_block(text: str) -> str:
    """从 Markdown 代码块中提取内容。"""
    m = _MARKDOWN_CODE_BLOCK_RE.match(text.strip())
    if m:
        return m.group(1).strip()
    return text.strip()


def _json_codeblock_to_text(text: str) -> str | None:
    """从 ```json ... ``` 代码块提取 JSON 并转换为文本。"""
    m = _JSON_CODE_BLOCK_RE.match(text.strip())
    if not m:
        return None
    json_str = m.group(1).strip()
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError:
        return json_str  # JSON 解析失败，返回原始 JSON 字符串
    result = _json_to_text(parsed)
    return result if result else json_str


def _json_to_text_with_fallback(text: str) -> str | None:
    """将裸 JSON 文本转换为纯文本，带兜底。"""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text  # 解析失败，返回原始文本
    result = _json_to_text(parsed)
    return result if result else text


def canonicalize(
    text: str,
    model_name: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """将任意模型输出转换为标准纯文本。

    Args:
        text: 模型返回的原始内容。
        model_name: 模型名称（用于日志）。

    Returns:
        (canonical_text, metadata) 元组。
        canonical_text: 提取出的纯文本。极端情况下可能为空字符串。
        metadata: {
            "output_type": 输出类型,
            "strategy": 使用的提取策略,
            "before_length": 原始长度,
            "after_length": 提取后长度,
            "model_name": 模型名称,
        }
    """
    before_length = len(text)
    output_type = _detect_output_type(text)
    canonical_text = text.strip()
    strategy = "passthrough"

    if output_type == OUTPUT_EMPTY:
        strategy = "empty"
        canonical_text = ""

    elif output_type == OUTPUT_JSON_CODEBLOCK:
        strategy = "json_codeblock_to_text"
        extracted = _json_codeblock_to_text(text)
        if extracted is not None:
            canonical_text = extracted

    elif output_type == OUTPUT_JSON:
        strategy = "json_to_text"
        extracted = _json_to_text_with_fallback(text)
        if extracted is not None:
            canonical_text = extracted

    elif output_type == OUTPUT_MARKDOWN:
        strategy = "unmark"
        canonical_text = _strip_markdown_code_block(text)

    # OUTPUT_PLAIN: pass through

    after_length = len(canonical_text)
    metadata: dict[str, Any] = {
        "output_type": output_type,
        "strategy": strategy,
        "before_length": before_length,
        "after_length": after_length,
        "model_name": model_name,
    }

    logger.info(
        "[CanonicalOutput] model=%s type=%s strategy=%s length=%d→%d",
        model_name or "unknown",
        output_type,
        strategy,
        before_length,
        after_length,
    )

    return canonical_text, metadata

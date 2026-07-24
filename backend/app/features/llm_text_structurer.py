"""文本导入 LLM 结构化层 — 仅做格式整理，禁止补全。

职责（只做这些）：
- 识别题干 / 选项 / 答案 / 解析区域
- 修复换行 / 选项拆分 / 题号前缀
- 提取多空题结构

绝不做：
- 推测、生成、补全任何答案 / 选项 / 解析
- 修改题目语义
- 创造原文不存在的内容

所有 LLM 输出字段必须能在原文中找到（反幻觉守门），否则强制置 null。
"""
from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.features.token_budget import (
    check_token_limit,
    estimate_tokens,
    record_token_usage,
)

logger = logging.getLogger(__name__)

_VALID_QUESTION_TYPES = {
    "single_choice",
    "multiple_choice",
    "true_false",
    "fill_blank",
    "multi_blank_choice",
    "subjective",
}

# 选项行检测（与 text_question_parser 一致）
_OPTION_LINE_RE = re.compile(r"^\s*([A-Da-d])\s*[.．、:：)）]\s*(.+)")
# 答案标签
_ANSWER_LABEL_RE = re.compile(
    r"(?:【|\[)?\s*(?:参考|正确)?\s*(?:答案|Answer|Ans|Key)\s*(?:】|\])?\s*[：:]",
    re.IGNORECASE,
)
# 多空标记
_BLANK_MARK_RE = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩]|\(\s*\)|（\s*）|_{2,}")


# ============================================================
# 结构完整度评估
# ============================================================


def should_call_llm(block_text: str, parsed: dict[str, Any]) -> tuple[bool, str]:
    """判断是否需要 LLM 兜底。返回 (should_call, reason)。"""
    if not settings.TEXT_IMPORT_LLM_ENABLED:
        return False, "feature_disabled"

    if len(block_text) > settings.TEXT_IMPORT_LLM_MAX_BLOCK_CHARS:
        return False, "block_too_long"

    if len(block_text.strip()) < 15:
        return False, "block_too_short"

    stem = (parsed.get("stem") or "").strip()
    options = parsed.get("options") or []
    answer = parsed.get("answer")
    detection_method = parsed.get("detection_method", "")
    qt = parsed.get("question_type") or ""

    # 触发 1: 规则解析未拿到题干
    if not stem:
        return True, "stem_empty"

    # 触发 2: 选择题选项数 < 2，但原文含 ≥3 个选项行候选
    option_line_count = sum(
        1 for line in block_text.split("\n") if _OPTION_LINE_RE.match(line.strip())
    )
    if qt in ("single_choice", "multiple_choice", "multi_blank_choice"):
        if len(options) < 2 and option_line_count >= 2:
            return True, "options_underdetected"

    # 触发 3: 答案缺失但原文有答案标签
    answer_empty = not answer or (isinstance(answer, str) and not answer.strip())
    if answer_empty and _ANSWER_LABEL_RE.search(block_text):
        return True, "answer_label_unparsed"

    # 触发 4: 单行长文本（Word/PDF 压平）— 极有可能选项题干答案全在一行
    lines = [ln for ln in block_text.split("\n") if ln.strip()]
    if len(lines) <= 2 and len(block_text) >= 100 and option_line_count <= 1:
        # heuristic 已尝试 _break_inline_text，若仍 < 2 选项 → 兜底
        if len(options) < 2:
            return True, "single_line_flattened"

    # 触发 5: 多空题特征 ≥ 2 处但识别为非多空题
    blank_count = len(_BLANK_MARK_RE.findall(block_text))
    if blank_count >= 2 and qt not in ("multi_blank_choice", "fill_blank", "subjective"):
        # 仅当当前题型识别为单选/多选时兜底
        if qt in ("single_choice", "multiple_choice") and len(options) < 2:
            return True, "multi_blank_misdetected"

    # 触发 6: heuristic 模式 + warnings 中含解析失败信号
    if detection_method == "heuristic":
        warnings = parsed.get("warnings") or []
        if any("无法识别题干" in w or "未能从文本中解析" in w for w in warnings):
            return True, "heuristic_warning"

    return False, "rule_ok"


def _reset_budget_for_test() -> None:
    """测试钩子：清零共享预算计数。"""
    import app.features.token_budget as _tb
    _tb._token_usage["daily"] = 0
    _tb._token_usage["daily_date"] = ""


# ============================================================
# JSON 解析
# ============================================================


def _parse_json_response(content: str) -> dict | None:
    if not content:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    start = content.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(content[start : i + 1])
                    except json.JSONDecodeError:
                        return None
    return None


# ============================================================
# 反幻觉守门
# ============================================================


def _normalize_for_match(text: str) -> str:
    """归一化用于子串匹配：去空白、统一标点。"""
    if not text:
        return ""
    text = re.sub(r"\s+", "", text)
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("：", ":").replace("，", ",")
    text = text.replace("。", ".").replace("？", "?").replace("！", "!")
    return text.lower()


def _appears_in(needle: str, haystack_norm: str, *, ratio_threshold: float = 0.85) -> bool:
    if not needle:
        return True
    needle_norm = _normalize_for_match(needle)
    if not needle_norm:
        return True
    if needle_norm in haystack_norm:
        return True
    # 长字段允许相似度匹配（容忍 LLM 修复换行、压缩空白产生的小差异）
    if len(needle_norm) >= 8:
        ratio = SequenceMatcher(None, needle_norm, haystack_norm).quick_ratio()
        if ratio >= ratio_threshold:
            # quick_ratio 是上界，再次精确确认
            return SequenceMatcher(None, needle_norm, haystack_norm).ratio() >= ratio_threshold
    return False


# 答案信号：精确提取原文里"作为答案出现的字母集合"，做白名单匹配
# 答案标签后紧跟 1-4 个 A-D 字母（容许逗号 / 顿号 / 空格 / 直连）
_ANSWER_LABEL_LETTERS_RE = re.compile(
    r"(?:【|\[)?\s*(?:参考|正确)?\s*(?:答案|Answer|Ans|Key)\s*(?:】|\])?\s*[：:]\s*"
    r"([A-Da-d](?:\s*[,，、\s]?\s*[A-Da-d]){0,3})",
    re.IGNORECASE,
)
# 答案标签后紧跟判断题答案
_ANSWER_LABEL_TF_RE = re.compile(
    r"(?:【|\[)?\s*(?:参考|正确)?\s*(?:答案|Answer|Ans|Key)\s*(?:】|\])?\s*[：:]\s*"
    r"(?:正确|错误|对|错|True|False|√|×|T|F)\b",
    re.IGNORECASE,
)
# 末行独立 1-4 字母（自测版试卷常见尾部答案行）
_TRAILING_LETTER_LINE_RE = re.compile(r"(?:^|\n)\s*([A-Da-d]{1,4})\s*(?:\n|$)")
# 独立成行的判断答案
_TRUE_FALSE_LINE_RE = re.compile(
    r"(?:^|\n)\s*(?:正确|错误|对|错|True|False|√|×|T|F)\s*(?:\n|$)",
    re.IGNORECASE,
)

_LETTER_ONLY_RE = re.compile(r"^[A-Da-d]+$")
_TF_TRUE_TOKENS = {"正确", "对", "true", "t", "√"}
_TF_FALSE_TOKENS = {"错误", "错", "false", "f", "×"}


def _extract_source_answer_letters(original: str) -> set[str]:
    """提取原文中明确作为答案出现的 A-D 字母集合（白名单）。

    候选来源：
    - 答案标签后紧跟的字母（"答案：D" / "参考答案: A,C" / "Answer: B"）
    - 末行独立 1-4 字母行
    """
    letters: set[str] = set()
    for m in _ANSWER_LABEL_LETTERS_RE.finditer(original):
        for ch in m.group(1).upper():
            if "A" <= ch <= "D":
                letters.add(ch)
    for m in _TRAILING_LETTER_LINE_RE.finditer(original):
        for ch in m.group(1).upper():
            if "A" <= ch <= "D":
                letters.add(ch)
    return letters


def _source_has_tf_signal(original: str) -> bool:
    """原文是否含判断题答案信号（答案标签后跟 T/F 或独立 T/F 行）。"""
    if _ANSWER_LABEL_TF_RE.search(original):
        return True
    if _TRUE_FALSE_LINE_RE.search(original):
        return True
    return False


def _validate_no_hallucination(
    structured: dict[str, Any], original: str
) -> tuple[dict[str, Any], list[str]]:
    """检查 LLM 输出每个非空字段都能在原文中找到，否则置 null。

    返回 (cleaned_structured, dropped_fields)。
    """
    haystack = _normalize_for_match(original)
    dropped: list[str] = []
    cleaned: dict[str, Any] = {
        "stem": None,
        "question_type": None,
        "options": [],
        "answer": None,
        "analysis": None,
    }

    # stem
    stem = structured.get("stem")
    if isinstance(stem, str) and stem.strip():
        if _appears_in(stem, haystack, ratio_threshold=0.7):
            cleaned["stem"] = stem.strip()
        else:
            dropped.append("stem")

    # question_type
    qt = structured.get("question_type")
    if isinstance(qt, str) and qt in _VALID_QUESTION_TYPES:
        cleaned["question_type"] = qt

    # options — 每个选项 text 必须在原文出现
    raw_options = structured.get("options") or []
    valid_options: list[dict[str, str]] = []
    if isinstance(raw_options, list):
        seen_keys: set[str] = set()
        for opt in raw_options:
            if not isinstance(opt, dict):
                continue
            key = str(opt.get("key") or "").strip().upper()
            text = str(opt.get("text") or "").strip()
            if not key or not text or key in seen_keys:
                continue
            if not re.fullmatch(r"[A-Z]", key):
                continue
            if _appears_in(text, haystack, ratio_threshold=0.8):
                valid_options.append({"key": key, "text": text})
                seen_keys.add(key)
            else:
                dropped.append(f"option_{key}")
    cleaned["options"] = sorted(valid_options, key=lambda x: x["key"])

    # answer — 字母 / 判断答案走白名单匹配，其它字符串走子串匹配
    source_letters = _extract_source_answer_letters(original)
    source_has_tf = _source_has_tf_signal(original)
    answer = structured.get("answer")
    if isinstance(answer, str):
        ans = answer.strip()
        if ans:
            ans_upper = ans.upper()
            if _LETTER_ONLY_RE.fullmatch(ans):
                # 字母答案：必须是原文白名单的子集
                ans_letters = {c for c in ans_upper}
                if ans_letters and ans_letters.issubset(source_letters):
                    cleaned["answer"] = (
                        ans_upper if len(ans_letters) == 1
                        else ",".join(sorted(ans_letters))
                    )
                else:
                    dropped.append("answer")
            elif ans.lower() in _TF_TRUE_TOKENS or ans.lower() in _TF_FALSE_TOKENS or ans in {"√", "×"}:
                # 判断题答案：原文必须有 T/F 信号
                if source_has_tf:
                    cleaned["answer"] = ans
                else:
                    dropped.append("answer")
            elif _appears_in(ans, haystack, ratio_threshold=0.8):
                cleaned["answer"] = ans
            else:
                dropped.append("answer")
    elif isinstance(answer, list):
        # 多选答案数组：每个元素必须是单字母，且整体落在白名单内
        letters: set[str] = set()
        all_letters = True
        for item in answer:
            if not isinstance(item, str):
                all_letters = False
                break
            tok = item.strip().upper()
            if not _LETTER_ONLY_RE.fullmatch(tok) or len(tok) != 1:
                all_letters = False
                break
            letters.add(tok)
        if all_letters and letters and letters.issubset(source_letters):
            cleaned["answer"] = ",".join(sorted(letters))
        elif letters or not all_letters:
            dropped.append("answer")

    # analysis
    analysis = structured.get("analysis")
    if isinstance(analysis, str) and analysis.strip():
        if _appears_in(analysis, haystack, ratio_threshold=0.6):
            cleaned["analysis"] = analysis.strip()
        else:
            dropped.append("analysis")

    return cleaned, dropped


# ============================================================
# LLM 调用入口
# ============================================================


async def structure_text_block(
    block_text: str,
    rule_hint: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
) -> dict[str, Any] | None:
    """对单个文本块调用 LLM 结构化。失败 / 不可用时返回 None（静默降级）。

    Returns:
        {
            "stem": str | None,
            "question_type": str | None,
            "options": list[{"key", "text"}],
            "answer": str | None,
            "analysis": str | None,
            "_dropped": list[str],   # 反幻觉守门移除的字段
            "_tokens": int,
        }
        或 None（不可用 / 预算超限 / 解析失败 / 全部字段被守门移除）
    """
    if not settings.TEXT_IMPORT_LLM_ENABLED:
        return None

    from app.ai.client import deepseek
    from app.ai.prompts import build_text_structure

    if not deepseek.is_available():
        return None

    # Read model name from DB config when available, fall back to env var
    _model_name = settings.TEXT_IMPORT_LLM_MODEL
    if db is not None:
        from app.services.model_config_resolver import ensure_db_model_configured
        _creds = await ensure_db_model_configured(db)
        if _creds:
            _model_name = _creds[2]

    messages = build_text_structure(block_text, rule_hint)
    estimated = estimate_tokens(json.dumps(messages, ensure_ascii=False))
    # P3-7: 共享 _token_usage 计数器但限值独立。与其他模块（ocr_correction
    # 走 admin_ai_configs, batch_complete/enrich 走配置）不同，这里用
    # TEXT_IMPORT_LLM_DAILY_TOKEN 环境变量控制本模块的预算上限。
    # 如需全系统统一的单一日限值，后续可引入全局配置项。
    if not await check_token_limit(estimated, {
        "daily_token_limit": settings.TEXT_IMPORT_LLM_DAILY_TOKEN,
    }):
        logger.info("text_structure: daily token budget exhausted")
        return None

    try:
        result = await deepseek.chat(
            messages,
            temperature=0.0,
            model=_model_name,
        )
    except Exception as exc:
        logger.warning("text_structure llm call failed: %s", exc)
        return None

    await record_token_usage(int(result.get("tokens_used") or 0))

    structured = _parse_json_response(result.get("content") or "")
    if structured is None:
        logger.warning("text_structure: failed to parse LLM JSON")
        return None

    cleaned, dropped = _validate_no_hallucination(structured, block_text)

    # 全部字段被守门移除 → 视为无效输出
    if not cleaned.get("stem") and not cleaned.get("options") and not cleaned.get("answer"):
        logger.warning("text_structure: all fields dropped by hallucination guard")
        return None

    cleaned["_dropped"] = dropped
    cleaned["_tokens"] = int(result.get("tokens_used") or 0)
    return cleaned

"""AI 修复服务 — 对规则解析失败的低置信度题目进行 AI 辅助修复。

纯规则触发 + DeepSeek API 修复 + token 限额控制 + 静默降级。
不修改上游数据，修复结果需经 Stage 7 审核。
"""

import asyncio
import json
import logging
import re
import time

logger = logging.getLogger(__name__)

_VALID_QUESTION_TYPES = (
    "single_choice", "multiple_choice", "true_false", "fill_blank", "subjective",
)

# 内存 token 计数器（进程级，后续可对接 ai_chats 表）
_token_usage: dict[str, int | str] = {"daily": 0, "monthly": 0, "daily_date": "", "monthly_month": ""}


def _estimate_tokens(text: str) -> int:
    """简单 token 估算（中文 ~1.3 token/字，其余 ~0.3 token/字）。"""
    chinese = len(re.findall(r"[一-鿿]", text))
    return int(chinese * 1.3 + (len(text) - chinese) * 0.3)


def _reset_counters_if_needed():
    today = time.strftime("%Y-%m-%d")
    month = time.strftime("%Y-%m")
    if _token_usage["daily_date"] != today:
        _token_usage["daily"] = 0
        _token_usage["daily_date"] = today
    if _token_usage["monthly_month"] != month:
        _token_usage["monthly"] = 0
        _token_usage["monthly_month"] = month


def _check_token_limit(estimated_tokens: int, config: dict) -> bool:
    """检查 token 限额。返回 True 表示可以继续调用。"""
    _reset_counters_if_needed()
    daily_limit = config.get("daily_token_limit", 100000)
    monthly_limit = config.get("monthly_token_limit", 2000000)
    if int(_token_usage["daily"]) + estimated_tokens > daily_limit:  # type: ignore[operator]
        return False
    if int(_token_usage["monthly"]) + estimated_tokens > monthly_limit:  # type: ignore[operator]
        return False
    return True


def _record_token_usage(tokens: int):
    _reset_counters_if_needed()
    _token_usage["daily"] = int(_token_usage["daily"]) + tokens  # type: ignore[operator]
    _token_usage["monthly"] = int(_token_usage["monthly"]) + tokens  # type: ignore[operator]


def _looks_like_non_question_text(question: dict) -> bool:
    stem = str(question.get("stem") or "").strip()
    raw_text = str(question.get("raw_text") or question.get("raw_question_text") or "").strip()
    text = "\n".join(part for part in (stem, raw_text) if part)
    if len(text) < 120:
        return False

    options = question.get("options") or []
    answer = str(question.get("answer") or "").strip()
    has_choice_options = bool(options) or bool(re.search(r"(^|\n)\s*[A-D][.．、)]\s*\S+", text))
    has_question_signal = bool(re.search(r"(求|问|判断|选择|下列|正确|错误|的是|为多少|\?|？)", text))
    has_number_signal = bool(re.search(r"(^|\n)\s*(?:第\s*\d+\s*题|\d+[.．、)]\s*)", text))
    has_answer_signal = bool(answer) or bool(re.search(r"答案|参考答案|解析", text))
    prose_markers = re.findall(
        r"定义|定理|知识点|证明|证毕|解法|例题|例如|如下|因此可得|由此可知|综上|性质|推论|注意",
        text,
    )

    weak_question_signals = sum([
        has_choice_options,
        has_question_signal,
        has_number_signal,
        has_answer_signal,
    ])
    return len(prose_markers) >= 2 and weak_question_signals <= 1


def _should_repair(question: dict, threshold: float) -> tuple[bool, str]:
    if _looks_like_non_question_text(question):
        return False, "non_question_like"

    # 1. confidence_score < threshold
    if question.get("confidence_score", 1.0) < threshold:
        return True, "low_confidence"

    # 2. is_valid == False
    if not question.get("is_valid", True):
        return True, "invalid"

    # 3. options 为空且题型是选择题
    qt = question.get("question_type", "")
    options = question.get("options") or []
    if qt in ("single_choice", "multiple_choice") and not options:
        return True, "missing_options"

    # 4. answer 为空
    if not (question.get("answer") or "").strip():
        return True, "missing_answer"

    # 5. stem 异常短
    if len(question.get("stem", "")) < 5:
        return True, "short_stem"

    return False, "above_threshold"


def _parse_ai_response(content: str) -> dict | None:
    """从 AI 返回内容中提取 JSON 对象。"""
    # 直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 提取 ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 括号配对提取最外层 {...}
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
                        break

    return None


def _validate_repaired(repaired: dict) -> tuple[bool, list[str]]:
    """校验 AI 修复结果的基本 schema。"""
    errors: list[str] = []
    if not repaired.get("stem"):
        errors.append("missing_stem")
    qt = repaired.get("question_type", "")
    if qt not in _VALID_QUESTION_TYPES:
        errors.append(f"invalid_question_type: {qt}")
    if qt in ("single_choice", "multiple_choice") and not repaired.get("options"):
        errors.append("missing_options_for_choice")
    return len(errors) == 0, errors


def _normalize_ai_options(options) -> list[dict]:
    """将 AI 返回的 options 转为标准列表格式 [{"key": "A", "text": "..."}]。"""
    if not options:
        return []
    if isinstance(options, list):
        result: list[dict] = []
        for item in options:
            if isinstance(item, dict):
                key = item.get("key", "")
                text = item.get("text", "")
                if key and text:
                    result.append({"key": str(key).upper(), "text": str(text)})
        if result:
            return result

    if isinstance(options, dict):
        result = []
        for key in sorted(options.keys()):
            result.append({"key": str(key).upper(), "text": str(options[key]).strip()})
        return result

    return []


async def _call_ai_for_repair(
    raw_text: str, existing: dict, config: dict
) -> dict | None:
    """调用 DeepSeek 修复单题。返回修复结果或 None（降级）。"""
    from app.ai.client import deepseek
    from app.ai.prompts import build_repair_question

    messages = build_repair_question(raw_text, existing)
    prompt_text = json.dumps(messages, ensure_ascii=False)
    estimated = _estimate_tokens(prompt_text)

    if not _check_token_limit(estimated, config):
        return None

    try:
        result = await deepseek.chat(messages, temperature=0.3)
    except Exception:
        return None

    _record_token_usage(result["tokens_used"])

    repaired = _parse_ai_response(result["content"])
    if repaired is None:
        return None

    is_valid, errors = _validate_repaired(repaired)
    return {
        "repaired": repaired,
        "ai_valid": is_valid,
        "ai_errors": errors,
        "token_used": result["tokens_used"],
    }


async def repair_questions(
    questions: list[dict],
    config: dict | None = None,
) -> dict:
    """对低置信度题目进行 AI 修复（并发，最多 3 路）。

    Args:
        questions: stage5 输出的标准化题目列表
        config: {
            "confidence_threshold": 0.6,
            "daily_token_limit": 100000,
            "monthly_token_limit": 2000000,
            "enabled": True,
        }

    Returns:
        {"repaired": [...], "unrepaired": [...], "skipped": [...], "stats": {...}}
    """
    if config is None:
        config = {}

    threshold = config.get("confidence_threshold", 0.6)
    enabled = config.get("enabled", True)

    repaired: list[dict] = []
    unrepaired: list[dict] = []
    skipped: list[dict] = []
    total_tokens = 0

    if not enabled:
        for i, q in enumerate(questions):
            skipped.append({
                "question_index": i,
                "reason": "ai_disabled",
                "confidence": q.get("confidence_score", 0),
            })
        return {
            "repaired": [], "unrepaired": [], "skipped": skipped,
            "stats": {
                "total_candidates": len(questions),
                "repaired": 0, "unrepaired": 0, "skipped": len(skipped),
                "total_tokens": 0,
            },
        }

    from app.ai.client import deepseek

    if not deepseek.is_available():
        for i, q in enumerate(questions):
            unrepaired.append({
                "question_index": i,
                "reason": "ai_unavailable",
            })
        return {
            "repaired": [], "unrepaired": unrepaired, "skipped": [],
            "stats": {
                "total_candidates": len(questions),
                "repaired": 0, "unrepaired": len(unrepaired), "skipped": 0,
                "total_tokens": 0,
            },
        }

    candidates: list[tuple[int, dict, str]] = []
    for i, q in enumerate(questions):
        do_repair, reason = _should_repair(q, threshold)
        if not do_repair:
            skipped.append({
                "question_index": i,
                "reason": reason,
                "confidence": q.get("confidence_score", 0),
            })
        else:
            raw_text = q.get("raw_text", "") or q.get("raw_question_text", "")
            candidates.append((i, q, raw_text))

    sem = asyncio.Semaphore(3)

    async def _repair_one(idx: int, q: dict, raw_text: str):
        async with sem:
            return idx, await _call_ai_for_repair(raw_text, q, config)

    results = await asyncio.gather(
        *[_repair_one(i, q, rt) for i, q, rt in candidates],
        return_exceptions=True,
    )

    for (i, q, raw_text), result in zip(candidates, results):
        if isinstance(result, BaseException):
            logger.debug("ai_repair question %d failed: %s", i, result)
            ai_result = None
        else:
            _, ai_result = result

        if ai_result is None:
            unrepaired.append({
                "question_index": i,
                "reason": "ai_failed",
            })
            continue

        if not ai_result["ai_valid"]:
            unrepaired.append({
                "question_index": i,
                "reason": "ai_invalid_result",
            })
            total_tokens += ai_result["token_used"]
            continue

        result_data = ai_result["repaired"]
        ai_valid = ai_result["ai_valid"]
        ai_errors = ai_result["ai_errors"]
        token_used = ai_result["token_used"]
        total_tokens += token_used

        after = {
            "schema_version": q.get("schema_version", "v1"),
            "subject": q.get("subject", ""),
            "question_type": result_data.get("question_type", q.get("question_type", "")),
            "stem": result_data.get("stem", ""),
            "options": _normalize_ai_options(result_data.get("options")),
            "answer": result_data.get("answer", ""),
            "analysis": result_data.get("analysis", ""),
            "raw_text": raw_text,
            "knowledge_points": q.get("knowledge_points", []),
            "difficulty": q.get("difficulty", 3),
            "source": q.get("source", {}),
            "is_valid": ai_valid and not ai_errors,
            "errors": ai_errors,
            "warnings": q.get("warnings", []),
            "stem_hash": q.get("stem_hash", ""),
            "confidence_score": result_data.get("confidence", q.get("confidence_score", 0)),
            "risk_flags": list(dict.fromkeys(q.get("risk_flags") or [])),
        }

        repaired.append({
            "question_index": i,
            "before": {k: v for k, v in q.items() if k != "raw_text"},
            "after": after,
            "repair_actions": result_data.get("repair_actions", []),
            "confidence": result_data.get("confidence", 0),
            "token_used": token_used,
        })

    return {
        "repaired": repaired,
        "unrepaired": unrepaired,
        "skipped": skipped,
        "stats": {
            "total_candidates": len(questions),
            "repaired": len(repaired),
            "unrepaired": len(unrepaired),
            "skipped": len(skipped),
            "total_tokens": total_tokens,
        },
    }

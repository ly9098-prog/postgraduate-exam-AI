"""AI 修复服务 — 对规则解析失败的低置信度题目进行 AI 辅助修复。

纯规则触发 + DeepSeek API 修复 + token 限额控制 + 静默降级。
不修改上游数据，修复结果需经 Stage 7 审核。
"""

import asyncio
import json
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_VALID_QUESTION_TYPES = (
    "single_choice", "multiple_choice", "true_false", "fill_blank", "multi_blank_choice", "subjective",
)

# P2-4: risk flags that should still allow low-risk skip (informational only)
_HARMLESS_RISK_FLAGS = frozenset({
    "math_region_detected",
    "roman_repair_applied",
    "batch_fallback_repair",
    "math_image_crop_failed",
    "math_image_upload_failed",
})

# P2-4: risk flags that always require AI repair
_RISK_FLAGS_REQUIRE_REPAIR = frozenset({
    "complex_formula_requires_review",
    "table_low_confidence",
    "table_requires_review",
    "ocr_garbled_code",
    "non_question_like",
    "low_confidence",
    "fallback_low_confidence",
    "no_exercise_regions",
    "option_structure_corruption",
    "code_symbol_risk",
    "math_low_confidence",
    # 代码块完整性风险（BUGS Task 2: 这些 flag 禁止 low_risk_skip）
    "code_block_incomplete",
    "code_block_truncated",
    "code_brace_unbalanced",
    "code_garbled_text",
    "code_line_break_suspicious",
    "code_paren_unbalanced",
    "code_fence_unclosed",
    "code_structure_regression",
})

# 内存 token 计数器（共享模块，与 ocr_correction 同一预算池）
from app.features.code_integrity import contains_code, detect_code_block_integrity, is_code_question
from app.features.token_budget import (
    check_token_limit,
    estimate_tokens,
    record_token_usage,
)

_estimate_tokens = estimate_tokens  # backward-compat alias


async def _check_token_limit(estimated_tokens: int, config: dict) -> bool:
    """backward-compat async wrapper — 测试代码依赖此名称。"""
    return await check_token_limit(estimated_tokens, config)


async def _record_token_usage(tokens: int) -> None:
    """backward-compat async wrapper — 测试代码依赖此名称。"""
    await record_token_usage(tokens)


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


# ── Math subscript safety gate (P1.3: Problem C from BUGS) ──
# Pattern: P_1, P_2, P_3, P_n — core math subscripts in 408 stack questions
_RE_SUBSCRIPT = re.compile(r"\b([A-Za-z])[_\^]\{?(\d+|[imn])\}?")
# Pattern for raw subscripts without LaTeX: P_1, P1, P_{i} etc.
_RE_SUBSCRIPT_RAW = re.compile(r"\b([A-Za-z])\s*[_\^]\s*[{]?\s*(\d+|[imn])\s*[}]?")


def _detect_subscript_changes(before_stem: str, after_stem: str, raw_text: str) -> list[str]:
    """Detect AI repair changes to math subscripts that lack evidence in raw text.

    Compares subscript pairs (variable + index) between before and after stems.
    If a subscript changed (e.g. P_3 → P_1, P_1 → P_2), checks raw_text for
    evidence of the new subscript. Without evidence, the change is rejected.

    Returns:
        List of change descriptions, empty if all changes are safe.
    """
    if not before_stem or not after_stem:
        return []
    if before_stem == after_stem:
        return []

    # Extract subscript pairs from before/after
    before_pairs = set()
    for m in _RE_SUBSCRIPT.finditer(before_stem):
        var, idx = m.group(1), m.group(2)
        before_pairs.add((var, idx))

    after_pairs = set()
    for m in _RE_SUBSCRIPT.finditer(after_stem):
        var, idx = m.group(1), m.group(2)
        after_pairs.add((var, idx))

    if not before_pairs and not after_pairs:
        return []

    changes: list[str] = []
    # Method 1: Pairwise comparison — detect any change where a subscript
    # value is replaced (e.g. P_3 changes to something else)
    before_subscripts = list(_RE_SUBSCRIPT.finditer(before_stem))
    after_subscripts = list(_RE_SUBSCRIPT.finditer(after_stem))

    for bm in before_subscripts:
        b_var = bm.group(1)
        b_idx = bm.group(2)
        # Find the corresponding subscript in after_stem at the same position
        # by matching on nearby context (rough positional alignment)
        b_pos = bm.start()
        # Search for same variable with different index near this position in after
        best_match = None
        best_dist = float("inf")
        for am in after_subscripts:
            a_var = am.group(1)
            a_idx = am.group(2)
            if a_var == b_var and a_idx != b_idx:
                dist = abs(am.start() - b_pos)
                if dist < best_dist:
                    best_dist = dist
                    best_match = (a_var, b_idx, a_idx)

        if best_match:
            var, old_idx, new_idx = best_match
            if best_dist <= 20:  # same area in text
                def _subscript_in_raw(sub: str) -> bool:
                    return bool(
                        re.search(rf"{var}\s*[_\^]\s*{sub}(?!\d)", raw_text) or
                        re.search(rf"{var}\s*[_\^]\s*{{\s*{sub}\s*}}", raw_text) or
                        re.search(rf"{var}{sub}(?!\d)", raw_text)
                    )
                raw_has_new = _subscript_in_raw(new_idx)
                raw_has_old = _subscript_in_raw(old_idx)

                if raw_has_new:
                    continue
                if raw_has_old:
                    changes.append(
                        f"{var}_{{{old_idx}}}→{var}_{{{new_idx}}}: "
                        f"old subscript found in raw text, "
                        f"new not supported by OCR evidence"
                    )
                elif old_idx.isdigit() and new_idx.isdigit():
                    changes.append(
                        f"{var}_{{{old_idx}}}→{var}_{{{new_idx}}}: "
                        f"numeric subscript changed without OCR evidence"
                    )

    # Method 2 (legacy): check removed/added index sets for completeness
    before_by_var: dict[str, set[str]] = {}
    for var, idx in before_pairs:
        before_by_var.setdefault(var, set()).add(idx)
    after_by_var: dict[str, set[str]] = {}
    for var, idx in after_pairs:
        after_by_var.setdefault(var, set()).add(idx)

    for var in before_by_var:
        before_idxs = before_by_var[var]
        after_idxs = after_by_var.get(var, set())
        added_idxs = after_idxs - before_idxs
        for new_idx in added_idxs:
            # Check if any of the new subscripts are unsupported by raw text
            def _subscript_in_raw2(sub: str) -> bool:
                return bool(
                    re.search(rf"{var}\s*[_\^]\s*{sub}(?!\d)", raw_text) or
                    re.search(rf"{var}\s*[_\^]\s*{{\s*{sub}\s*}}", raw_text) or
                    re.search(rf"{var}{sub}(?!\d)", raw_text)
                )
            if not _subscript_in_raw2(new_idx) and new_idx.isdigit():
                changes.append(
                    f"{var}_{{{new_idx}}}: "
                    f"new subscript not found in OCR evidence"
                )

    # Also check for specificity loss: P_3 → P_i (generalizing a specific subscript)
    for var in before_by_var:
        before_idxs = before_by_var[var]
        after_idxs = after_by_var.get(var, set())
        numeric_before = {i for i in before_idxs if i.isdigit()}
        symbolic_after = {i for i in after_idxs if not i.isdigit() and i in ("i", "j", "k", "m", "n")}
        if numeric_before and symbolic_after:
            for old_idx in numeric_before:
                changes.append(
                    f"{var}_{{{old_idx}}}→{var}_{{{list(symbolic_after)[0]}}}: "
                    f"A specific subscript was generalized without evidence"
                )

    return changes


def _stem_has_code(stem: str) -> bool:
    """快速判断题干是否包含代码（保守匹配，避免自然语言误触发）。"""
    if not stem:
        return False
    if "```" in stem:
        return True
    if "->" in stem:
        return True
    # 仅匹配最不可能出现在题干自然语言中的 C 关键词
    if re.search(r"\b(?:struct\s|typedef|printf|scanf|malloc|free|NULL|nullptr|return\s|int\s+\*|char\s+\*|void\s+\*)", stem):
        return True
    # 仅当关键词后明确跟标识符或括号时才触发
    if re.search(r"\b(?:int|void|char|float|double)\s+(?:\w+\s*[\[(;=]|\*)", stem):
        return True
    if re.search(r"BiTNode|LinkList|SqList|ListNode|ElemType|LNode|TNode", stem):
        return True
    return False


def _append_decision_trace(question: dict, stage: str, result: str, reason: str) -> None:
    """向题目的 decision_trace 追加入口。如果题目没有 decision_trace 则初始化。"""
    if not isinstance(question, dict):
        return
    trace = list(question.get("decision_trace") or [])
    trace.append({"stage": stage, "result": result, "reason": reason})
    question["decision_trace"] = trace


def _is_low_risk_skip_candidate(question: dict, high_confidence_threshold: float = 0.95) -> bool:
    """P2-4: 判断是否可跳过 AI repair（低风险高置信度题）。

    条件（全满足才跳过）：
    - confidence >= high_confidence_threshold
    - ai_answer_flag != true
    - stem 不为空
    - answer 不为空（选择题/判断题）
    - risk_flags 不含需要 repair 的 flag
    """
    # 置信度门槛
    confidence = question.get("confidence_score", 0)
    if confidence < high_confidence_threshold:
        return False

    # AI 答案需要人工确认，不走跳过
    if question.get("ai_answer_flag"):
        return False

    # stem 必须非空
    stem = (question.get("stem") or "").strip()
    if not stem:
        return False

    # 选择题/判断题 answer 必须非空
    qt = question.get("question_type", "")
    if qt in ("single_choice", "multiple_choice", "true_false"):
        answer = (question.get("answer") or "").strip()
        if not answer:
            return False

    # risk_flags 不能包含需要 repair 的 flag
    risk_flags = set(question.get("risk_flags") or [])
    dangerous = risk_flags - _HARMLESS_RISK_FLAGS
    if dangerous & _RISK_FLAGS_REQUIRE_REPAIR:
        return False

    # ---- BUGS Task 2: 代码块完整性防护（即使 risk_flags 未同步也生效） ----
    # 包含代码的题目，在 stem 上直接执行完整性检测，避免任何旁路导致代码损坏被跳过
    if _stem_has_code(stem):
        integrity = detect_code_block_integrity(stem)
        if integrity["flags"]:
            return False

    return True


def _should_repair(
    question: dict,
    threshold: float,
    roman_anomalies: list[dict] | None = None,
    *,
    high_confidence_threshold: float = 0.95,
    low_risk_skip_enabled: bool = True,
) -> tuple[bool, str]:
    # ---- Code integrity gate: 代码结构损坏强制 repair，优先级高于所有 skip 逻辑 ----
    stem = question.get("stem", "")
    if stem:
        if contains_code(stem) or is_code_question(stem):
            integrity = detect_code_block_integrity(stem)
            if integrity["flags"]:
                return True, "code_integrity_forced"
    # ---- end code integrity gate ----

    if _looks_like_non_question_text(question):
        return False, "non_question_like"

    # P2-4: 低风险题跳过 AI repair（综合条件判断）
    if low_risk_skip_enabled and _is_low_risk_skip_candidate(question, high_confidence_threshold):
        return False, "low_risk_high_confidence"

    # 0. Roman numeral anomalies — always trigger repair regardless of confidence
    if roman_anomalies:
        return True, "roman_anomaly"

    # 1. confidence_score < threshold
    confidence = question.get("confidence_score", 1.0)
    if confidence < threshold:
        return True, "low_confidence"

    # 2. is_valid == False
    if not question.get("is_valid", True):
        return True, "invalid"

    # 3. options 为空且题型是选择题
    qt = question.get("question_type", "")
    options = question.get("options") or []
    if qt in ("single_choice", "multiple_choice") and not options:
        return True, "missing_options"

    # 3b. options 不完整 — 有选项但中间缺失（如 A, C, D 缺少 B）
    #     触发 AI 从 raw_text 中恢复缺失选项
    if qt == "single_choice" and options:
        if isinstance(options, list):
            found_keys = {o.get("key", "") for o in options if isinstance(o, dict)}
            expected_sequence = ["A", "B", "C", "D"]
            for i, key in enumerate(expected_sequence[:-1]):
                if key not in found_keys and expected_sequence[i + 1] in found_keys:
                    return True, "incomplete_options"

    # 4. answer 为空
    if qt in ("single_choice", "multiple_choice", "true_false") and not (question.get("answer") or "").strip():
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


def _marker_ids(groups: list[dict] | None) -> set[str]:
    return {str(group.get("id") or group.get("marker") or "").strip() for group in (groups or []) if str(group.get("id") or group.get("marker") or "").strip()}


def _stem_contains_markers(stem: str, markers: set[str]) -> bool:
    return all(marker in stem for marker in markers)


_BATCH_LIMIT = 15  # 单次 batch 最多 15 题，超长自动分批


def _parse_batch_ai_response(content: str) -> list[dict] | None:
    """从 AI 返回内容中提取 JSON 数组（多题批量修复结果）。"""
    text = content.strip()

    # 直接解析 JSON 数组
    if text.startswith("["):
        try:
            items = json.loads(text)
            if isinstance(items, list):
                return items
        except json.JSONDecodeError:
            pass

    # 提取 ```json ... ``` 代码块中的数组
    m = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", text)
    if m:
        try:
            items = json.loads(m.group(1).strip())
            if isinstance(items, list):
                return items
        except json.JSONDecodeError:
            pass

    # 按行扫描，逐题提取每个 {...}
    items: list[dict] = []
    current_start = -1
    brace_count = 0
    for i, ch in enumerate(text):
        if ch == "{":
            if brace_count == 0:
                current_start = i
            brace_count += 1
        elif ch == "}":
            brace_count -= 1
            if brace_count == 0 and current_start >= 0:
                try:
                    item = json.loads(text[current_start : i + 1])
                    if isinstance(item, dict):
                        items.append(item)
                except json.JSONDecodeError:
                    pass
                current_start = -1

    return items if len(items) >= 2 else None


async def _call_ai_for_repair(
    raw_text: str, existing: dict, config: dict, db: AsyncSession | None = None,
    api_key: str | None = None, base_url: str | None = None, model_name: str | None = None,
) -> dict | None:
    """调用 DeepSeek 修复单题。返回修复结果或 None（降级）。

    外部可传入 api_key/base_url/model_name 避免重复查询 DB 凭据。

    Structure Freeze 约束:
        - 当 ``existing.is_frozen`` 为 True 时，从 prompt 中移除 options 信息，
          防止 AI 看到并尝试改写冻结的选项结构。
        - 选项的恢复在 ``repair_questions()`` 的循环中统一处理。
    """
    from app.ai.client import deepseek
    from app.ai.prompts import build_repair_question

    if db is not None and api_key is None:
        from app.services.model_config_resolver import (
            AICapability,
            AIModelConfigResolver,
        )
        try:
            resolver = AIModelConfigResolver(db)
            ai_repair_config = await resolver.resolve_for_capability(AICapability.AI_REPAIR)
            api_key = await resolver.resolve_secret(ai_repair_config)
            base_url = ai_repair_config.endpoint
            model_name = ai_repair_config.model_name
        except ValueError:
            api_key = base_url = model_name = None

    # ── Structure Freeze: prevent AI from seeing frozen options ──
    # When is_frozen is True, the freeze stage is the single source of truth.
    # AI should NOT receive the existing option structure in the prompt,
    # because it might try to modify it. Only raw_text and non-option fields
    # are sent.
    if existing and existing.get("is_frozen"):
        existing = {k: v for k, v in existing.items() if k != "options"}

    messages = build_repair_question(raw_text, existing)
    prompt_text = json.dumps(messages, ensure_ascii=False)
    estimated = _estimate_tokens(prompt_text)

    if not await check_token_limit(estimated, config):
        return None

    try:
        result = await deepseek.chat(messages, temperature=0.3, model=model_name, api_key=api_key, base_url=base_url)
    except Exception:
        return None

    await record_token_usage(result["tokens_used"])

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


async def _call_ai_for_batch_repair(
    candidates: list[tuple[int, dict, str]],
    config: dict,
    db: AsyncSession | None = None,
) -> list[tuple[int, dict | None]]:
    """批量调用 DeepSeek 修复多题。自动分批（每批最多 _BATCH_LIMIT 题）。"""
    from app.ai.client import deepseek
    from app.ai.prompts import build_batch_repair_prompt

    if not candidates:
        return []

    api_key = base_url = model_name = None
    if db is not None:
        from app.services.model_config_resolver import (
            AICapability,
            AIModelConfigResolver,
        )
        try:
            resolver = AIModelConfigResolver(db)
            ai_repair_config = await resolver.resolve_for_capability(AICapability.AI_REPAIR)
            api_key = await resolver.resolve_secret(ai_repair_config)
            base_url = ai_repair_config.endpoint
            model_name = ai_repair_config.model_name
        except ValueError:
            api_key = base_url = model_name = None

    all_results: list[tuple[int, dict | None]] = []

    # 自动分批（优先使用 config 中的 batch_size，默认 _BATCH_LIMIT）
    batch_limit = config.get("batch_size", _BATCH_LIMIT) or _BATCH_LIMIT
    for batch_start in range(0, len(candidates), batch_limit):
        batch = candidates[batch_start : batch_start + batch_limit]
        # ── Structure Freeze: strip frozen options from batch prompt ──
        batch = [
            (idx, {k: v for k, v in q.items() if k != "options"} if q.get("is_frozen") else q, rt)
            for idx, q, rt in batch
        ]
        messages = build_batch_repair_prompt(batch)
        prompt_text = json.dumps(messages, ensure_ascii=False)
        estimated = _estimate_tokens(prompt_text)

        if not await check_token_limit(estimated, config):
            for idx, _q, _rt in batch:
                all_results.append((idx, None))
            continue

        try:
            result = await deepseek.chat(
                messages, temperature=0.3, model=model_name,
                api_key=api_key, base_url=base_url,
            )
        except Exception:
            for idx, _q, _rt in batch:
                all_results.append((idx, None))
            continue

        await record_token_usage(result["tokens_used"])
        responses = _parse_batch_ai_response(result["content"])

        if responses and len(responses) == len(batch):
            # M1: distribute tokens fairly, tracking remainder to avoid truncation
            total_tokens = result["tokens_used"]
            base = total_tokens // len(batch)
            rem = total_tokens % len(batch)
            for pos, ((idx, q, _rt), repaired) in enumerate(zip(batch, responses)):
                is_valid, errors = _validate_repaired(repaired)
                all_results.append((
                    idx,
                    {
                        "repaired": repaired,
                        "ai_valid": is_valid,
                        "ai_errors": errors,
                        "token_used": base + (1 if pos < rem else 0),
                    } if is_valid else None,
                ))
        else:
            # batch 解析失败，逐题降级
            logger.warning(
                "Batch repair parse failed (%d responses for %d questions), "
                "falling back to per-question repair",
                len(responses) if responses else 0, len(batch),
            )
            for idx, q, raw_text in batch:
                single = await _call_ai_for_repair(raw_text, q, config, db, api_key=api_key, base_url=base_url, model_name=model_name)
                if single:
                    single["_batch_fallback"] = True  # L2: mark degradation source
                all_results.append((idx, single))

    return all_results


# ---------------------------------------------------------------------------
# Roman numeral constrained-decision repair (Phase 1 of AI repair)
# ---------------------------------------------------------------------------


def _parse_roman_decision_response(content: str) -> dict | None:
    """Parse the AI's Roman numeral decision JSON."""
    try:
        result = json.loads(content)
        if isinstance(result, dict) and "decisions" in result:
            return result
    except json.JSONDecodeError:
        pass

    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", content)
    if m:
        try:
            result = json.loads(m.group(1).strip())
            if isinstance(result, dict) and "decisions" in result:
                return result
        except json.JSONDecodeError:
            pass

    return None


async def _call_ai_for_roman_decision(
    question: dict,
    anomalies: list[dict],
    config: dict,
    db: AsyncSession | None = None,
) -> dict | None:
    """Call DeepSeek for constrained Roman numeral repair decisions.

    Returns: {"decisions": [...], "token_used": N} or None on failure.
    """
    from app.ai.client import deepseek
    from app.ai.prompts import build_roman_decision_prompt

    if db is not None:
        from app.services.model_config_resolver import (
            AICapability,
            AIModelConfigResolver,
        )
        try:
            resolver = AIModelConfigResolver(db)
            ai_repair_config = await resolver.resolve_for_capability(AICapability.AI_REPAIR)
            api_key = await resolver.resolve_secret(ai_repair_config)
            base_url = ai_repair_config.endpoint
            model_name = ai_repair_config.model_name
        except ValueError:
            api_key = base_url = model_name = None
    else:
        api_key = base_url = model_name = None

    messages = build_roman_decision_prompt(question, anomalies)
    prompt_text = json.dumps(messages, ensure_ascii=False)
    estimated = _estimate_tokens(prompt_text)

    if not await check_token_limit(estimated, config):
        return None

    try:
        result = await deepseek.chat(
            messages, temperature=0.2, model=model_name,
            api_key=api_key, base_url=base_url,
        )
    except Exception:
        return None

    await record_token_usage(result["tokens_used"])

    parsed = _parse_roman_decision_response(result["content"])
    if parsed is None:
        return None

    return {
        "decisions": parsed.get("decisions", []),
        "token_used": result["tokens_used"],
    }


def _build_roman_fix_from_decision(
    anomaly: dict, decision: dict
) -> dict:
    """Convert an AI-chosen flat candidate into a mechanical fix instruction.

    The anomaly has pre-generated flat candidates (each a self-contained action).
    The decision picks one by chosen_candidate_index. This function translates
    the chosen candidate into a fix instruction that apply_roman_fix() can execute.
    """
    candidates = anomaly.get("candidates", [])
    chosen_idx = decision.get("chosen_candidate_index", -1)

    if chosen_idx < 0 or chosen_idx >= len(candidates):
        return {"action": "keep_as_is"}

    chosen = candidates[chosen_idx]
    source = anomaly.get("source", "")
    action = chosen.get("action", "")

    if action == "keep_as_is":
        return {"action": "keep_as_is"}

    if action == "replace_token":
        return {
            "action": "replace_token",
            "source": source,
            "position": chosen["position"],
            "from_token": chosen["current_token"],
            "to_token": chosen["token"],
        }

    if action == "replace_token_at_position":
        return {
            "action": "replace_token",
            "source": source,
            "position": chosen["position"],
            "from_token": chosen["current_token"],
            "to_token": chosen["token"],
        }

    if action == "insert_token":
        return {
            "action": "insert_token",
            "source": source,
            "after_position": chosen["position"] - 1,
            "token": chosen["token"],
        }

    if action == "replace_1_with_I":
        return {
            "action": "replace_1_with_I",
            "source": source,
            "original_fragment": "1、",
            "fixed_fragment": "I、",
        }

    return {"action": "keep_as_is"}


def _apply_roman_decisions(
    question: dict, anomalies: list[dict], decisions: list[dict]
) -> dict:
    """Apply AI-chosen Roman numeral fixes to a question mechanically."""
    from app.features.roman_schema import apply_roman_fix

    q = dict(question)

    # Track resolved anomaly sources so we only clear their warnings
    resolved_sequence_sources: set[str] = set()  # e.g. {"stem", "option_A"}
    resolved_digit_option_keys: set[str] = set()  # e.g. {"A"}

    for i, decision in enumerate(decisions):
        if i >= len(anomalies):
            break
        fix = _build_roman_fix_from_decision(anomalies[i], decision)
        if fix.get("action") != "keep_as_is":
            q = apply_roman_fix(q, fix)
            anom = anomalies[i]
            source = anom.get("source", "")
            issue_type = anom.get("issue_type", "")
            if issue_type == "ocr_digit_confusion":
                opt_key = source.split("_", 1)[1] if source.startswith("option_") else ""
                resolved_digit_option_keys.add(opt_key)
            else:
                resolved_sequence_sources.add(source)

    # Only clear warnings that correspond to resolved anomalies
    existing_warnings: list[str] = list(q.get("warnings", []))
    filtered_warnings: list[str] = []
    for w in existing_warnings:
        keep = True
        for src in resolved_sequence_sources:
            if w.startswith(f"broken_roman_numeral_sequence({src})"):
                keep = False
                break
        if keep:
            for key in resolved_digit_option_keys:
                if w.startswith("option_roman_digit_confusion") and f"option {key}" in w:
                    keep = False
                    break
        if keep:
            filtered_warnings.append(w)
    q["warnings"] = filtered_warnings

    # Record the repair
    risk_flags = list(q.get("risk_flags") or [])
    if "roman_repair_applied" not in risk_flags:
        risk_flags.append("roman_repair_applied")
    q["risk_flags"] = risk_flags

    return q


async def _run_roman_repair_phase(
    questions: list[dict],
    roman_anomalies: list[dict],
    config: dict,
    db: AsyncSession | None = None,
) -> list[dict]:
    """Run the constrained Roman numeral decision phase.

    Groups anomalies by question index, calls AI for decisions per question,
    applies fixes mechanically.

    Returns a list of repair result dicts: [{"index": N, "decisions": [...], "token_used": T}]
    """
    if not roman_anomalies:
        return []

    # Group anomalies by question index
    by_index: dict[int, list[dict]] = {}
    for anom in roman_anomalies:
        idx = anom.get("index", 0)
        by_index.setdefault(idx, []).append(anom)

    import asyncio
    sem = asyncio.Semaphore(3)
    results: list[dict] = []

    async def _decide_one(idx: int, anoms: list[dict]):
        async with sem:
            q = questions[idx] if idx < len(questions) else {}
            ai_result = await _call_ai_for_roman_decision(q, anoms, config, db)
            if ai_result:
                return {
                    "index": idx,
                    "decisions": ai_result["decisions"],
                    "token_used": ai_result["token_used"],
                }
            return {"index": idx, "decisions": [], "token_used": 0}

    gathered = await asyncio.gather(
        *[_decide_one(idx, anoms) for idx, anoms in by_index.items()],
        return_exceptions=True,
    )

    for result in gathered:
        if isinstance(result, dict):
            results.append(result)
        elif isinstance(result, BaseException):
            logger.warning("Roman decision phase exception: %s", result)

    return results


async def repair_questions(
    questions: list[dict],
    config: dict | None = None,
    db: AsyncSession | None = None,
    roman_diagnostics: list[dict] | None = None,
) -> dict:
    """对低置信度题目进行 AI 修复（两阶段：Roman 决策 + 通用修复）。

    Phase 1: Roman numeral constrained-decision repair (AI chooses from
             candidate fixes; code applies the fix mechanically).
    Phase 2: Standard free-form AI repair (existing behavior, unchanged).

    Args:
        questions: stage5 输出的标准化题目列表
        config: {
            "confidence_threshold": 0.6,
            "daily_token_limit": 100000,
            "monthly_token_limit": 2000000,
            "enabled": True,
        }
        roman_diagnostics: 结构化 Roman 异常列表（来自 batch_validation）

    Returns:
        {"repaired": [...], "unrepaired": [...], "skipped": [...], "stats": {...}}
    """
    if config is None:
        config = {}

    threshold = config.get("confidence_threshold", 0.6)
    high_confidence_threshold = config.get("high_confidence_threshold", 0.95)
    enabled = config.get("enabled", True)
    low_risk_skip_enabled = config.get("low_risk_skip_enabled", True)

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

    # ------------------------------------------------------------------
    # Phase 1: Roman numeral constrained-decision repair
    # ------------------------------------------------------------------
    roman_diagnostics = roman_diagnostics or []
    roman_results: dict[int, dict] = {}  # index → {decisions, token_used}
    roman_total_tokens = 0

    if roman_diagnostics and deepseek.is_available():
        phase1_results = await _run_roman_repair_phase(
            questions, roman_diagnostics, config, db,
        )
        for r in phase1_results:
            idx = r["index"]
            roman_results[idx] = r
            roman_total_tokens += r.get("token_used", 0)

    # Apply Roman fixes to questions before standard repair
    roman_fixed_questions: list[dict] = []
    for i, q in enumerate(questions):
        if i in roman_results and roman_results[i].get("decisions"):
            # Find anomalies for this question
            q_anomalies = [a for a in roman_diagnostics if a.get("index") == i]
            fixed = _apply_roman_decisions(
                q, q_anomalies, roman_results[i]["decisions"],
            )
            roman_fixed_questions.append(fixed)
        else:
            roman_fixed_questions.append(q)

    # Build per-question roman anomaly lookup for _should_repair
    roman_anomalies_by_index: dict[int, list[dict]] = {}
    for anom in roman_diagnostics:
        idx = anom.get("index", 0)
        roman_anomalies_by_index.setdefault(idx, []).append(anom)

    # ------------------------------------------------------------------
    # Phase 2: Standard AI repair (unchanged logic)
    # ------------------------------------------------------------------
    candidates: list[tuple[int, dict, str]] = []
    for i, q in enumerate(roman_fixed_questions):
        q_anomalies = roman_anomalies_by_index.get(i)
        # Roman-repaired questions that had ONLY roman issues skip Phase 2
        if i in roman_results and roman_results[i].get("decisions"):
            # Check if there are still non-roman reasons to repair
            _, reason = _should_repair(q, threshold, roman_anomalies=None, high_confidence_threshold=high_confidence_threshold, low_risk_skip_enabled=low_risk_skip_enabled)
            if reason == "above_threshold":
                # Roman repair was the only issue — record and skip Phase 2
                roman_entry = {
                    "question_index": i,
                    "before": {k: v for k, v in questions[i].items() if k != "raw_text"},
                    "after": q,
                    "repair_actions": ["roman_numeral_fixed"],
                    "repair_method": "roman_decision",
                    "confidence": 0.95,
                    "token_used": roman_results[i].get("token_used", 0),
                }
                # P0: decision_trace 记录 Roman repair 跳过 Phase 2
                _append_decision_trace(q, "ai_repair", "skipped", "roman_only")
                repaired.append(roman_entry)
                total_tokens += roman_results[i].get("token_used", 0)
                continue

        do_repair, reason = _should_repair(q, threshold, roman_anomalies=q_anomalies, high_confidence_threshold=high_confidence_threshold, low_risk_skip_enabled=low_risk_skip_enabled)
        if not do_repair:
            _append_decision_trace(questions[i], "ai_repair", "skipped", reason)
            skipped.append({
                "question_index": i,
                "reason": reason,
                "confidence": q.get("confidence_score", 0),
            })
        else:
            raw_text = q.get("raw_text", "") or q.get("raw_question_text", "")
            if reason == "incomplete_options":
                # Strip options so AI recovers all 4 from raw_text.
                # The post-ai repair immutable-options check handles superset
                # recovery (4 > 3) in the validation loop below.
                q = dict(q)
                q.pop("options", None)
                raw_text = (
                    "【注意】本题选项不完整（中间缺失），"
                    "请根据原始文本中的完整选项内容补充所有选项。\n\n"
                    + raw_text
                )
            candidates.append((i, q, raw_text))

    # 批量修复（一次 LLM 调用修复多题），超长自动分批
    batch_size = config.get("batch_size", _BATCH_LIMIT)
    if batch_size > 1 and len(candidates) > 1:
        results = await _call_ai_for_batch_repair(candidates, config, db)
    else:
        # 单题修复（并发 3 路）
        sem = asyncio.Semaphore(3)

        async def _repair_one(idx: int, q: dict, raw_text: str):
            async with sem:
                return idx, await _call_ai_for_repair(raw_text, q, config, db)

        gathered = await asyncio.gather(
            *[_repair_one(i, q, rt) for i, q, rt in candidates],
            return_exceptions=True,
        )

        results: list[tuple[int, dict | None]] = []
        for (i, _q, _rt), result in zip(candidates, gathered):
            if isinstance(result, BaseException):
                results.append((i, None))
            else:
                results.append(result)  # type: ignore[assignment]

    for (i, q, raw_text), (_, ai_result) in zip(candidates, results):

        if ai_result is None:
            _append_decision_trace(questions[i], "ai_repair", "failed", "ai_failed")
            unrepaired.append({
                "question_index": i,
                "reason": "ai_failed",
            })
            continue

        if not ai_result["ai_valid"]:
            _append_decision_trace(questions[i], "ai_repair", "failed", "ai_invalid_result")
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

        blank_option_groups = result_data.get("blank_option_groups") or q.get("blank_option_groups", [])
        repaired_stem = result_data.get("stem", "")
        original_markers = _marker_ids(q.get("blank_option_groups"))
        if original_markers and not _stem_contains_markers(repaired_stem, original_markers):
            logger.warning(
                "AI repair lost blank markers for question %d: markers=%s not in stem, discarding repaired stem",
                i, original_markers,
            )
            repaired_stem = q.get("stem", "")
            ai_errors = [*ai_errors, "ai_stem_lost_blank_markers"]

        from app.services.pdf_text_normalizer import deduplicate_repeated_text
        repaired_stem = deduplicate_repeated_text(repaired_stem)

        # ══════════════════════════════════════════════════════════════════════
        # Layer 4: Options MUST be immutable when they already exist
        # ══════════════════════════════════════════════════════════════════════
        # Rules:
        #   1. If options already exist → AI must NOT modify them (exact match).
        #      Any change (modify, add, delete) → rejection.
        #   2. If options are empty (parser failed) → AI can extract from raw_text.
        #      This is valid repair — recovering what the parser missed.
        #   3. Frozen questions always have non-empty options → Rule 1 covers them.
        #   4. If options exist and AI returns empty → rejection (deletion).
        is_frozen = bool(q.get("is_frozen", False))
        original_opts = q.get("options", [])
        ai_options = _normalize_ai_options(result_data.get("options"))

        # Rule 1: Existing options are IMMUTABLE
        # AI must not modify or delete existing options.
        #
        # Exception: AI may ADD missing option keys (recovery) when the AI's
        # result is a strict superset of the original. This handles OCR cases
        # where the parser missed options due to corruption (e.g. garbled
        # option B text between A and C).
        #
        # Three outcomes:
        #   1. ai_keys > original_keys  → allow (superset recovery)
        #   2. ai_keys == original_keys → reject (modification without addition)
        #   3. ai_keys < original_keys  → reject (deletion)
        if original_opts and ai_options and ai_options != original_opts:
            original_keys = {o["key"] for o in original_opts}
            ai_keys = {o["key"] for o in ai_options}

            if ai_keys > original_keys:
                logger.info(
                    "[IMMUTABLE] ai_repair ALLOWED for q%d: AI recovered missing "
                    "options (original=%d, ai=%d, added=[%s])",
                    i, len(original_opts), len(ai_options),
                    ",".join(sorted(ai_keys - original_keys)),
                )
            else:
                logger.warning(
                    "[IMMUTABLE] ai_repair REJECTED for q%d: AI tried to modify options "
                    "(frozen=%s, ai_opts=%d, original_opts=%d)",
                    i, is_frozen, len(ai_options), len(original_opts),
                )
                _append_decision_trace(questions[i], "ai_repair", "rejected",
                                       "options_modified_by_ai")
                unrepaired.append({
                    "question_index": i,
                    "reason": "options_modified_by_ai",
                })
                total_tokens += token_used
                continue

        # Rule 2: Existing options must not be deleted
        if original_opts and not ai_options:
            logger.warning(
                "[IMMUTABLE] ai_repair REJECTED for q%d: AI deleted existing options "
                "(original_opts=%d)",
                i, len(original_opts),
            )
            _append_decision_trace(questions[i], "ai_repair", "rejected",
                                   "options_deleted_by_ai")
            unrepaired.append({
                "question_index": i,
                "reason": "options_deleted_by_ai",
            })
            total_tokens += token_used
            continue

        # Rule 3: If options were empty (parser failed to extract), AI may
        # recover them from raw_text. This is a valid repair operation.
        # The AI is NOT generating options out of thin air — it's extracting
        # from the raw question text that contains option patterns.
        if not original_opts and not is_frozen:
            # Allow AI to populate options from raw_text (repair behavior)
            pass

        # ── Preserve original options when they already existed ──
        # Only skip restore when AI added missing keys (superset recovery
        # passed Rule 1). In that case, use AI's options directly since they
        # include the recovered keys.
        if original_opts:
            _superset = (
                ai_options
                and {o["key"] for o in ai_options} > {o["key"] for o in original_opts}
            )
            if not _superset:
                ai_options = list(original_opts)

        after = {
            "schema_version": q.get("schema_version", "v1"),
            "subject": q.get("subject", ""),
            "question_type": result_data.get("question_type", q.get("question_type", "")),
            "stem": repaired_stem,
            "options": ai_options,
            "frozen_options_restored": is_frozen,
            "options_preserved": not is_frozen and bool(original_opts),
            "blank_option_groups": blank_option_groups,
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

        repair_actions = result_data.get("repair_actions", [])
        # If this question was also Roman-repaired, re-apply fixes and merge info
        if i in roman_results:
            repair_actions = ["roman_numeral_fixed", *repair_actions]
            # Re-apply Phase 1 Roman fixes on Phase 2 result so they aren't
            # overwritten when the question also needed non-Roman repair.
            q_anoms = roman_anomalies_by_index.get(i)
            if q_anoms:
                after = _apply_roman_decisions(after, q_anoms, roman_results[i]["decisions"])
            after.setdefault("risk_flags", [])
            if "roman_repair_applied" not in after["risk_flags"]:
                after["risk_flags"] = ["roman_repair_applied", *after["risk_flags"]]

        # ---- Math subscript safety gate (P1.3: Problem C from BUGS) ----
        # Detect and reject AI repair that changes core math subscripts without
        # evidence from OCR/VL raw text.
        # Cases: P_3 → P_1, P_1 → P_2, P_i → P_3 (subscript identity changes)
        _before_stem = str(questions[i].get("stem", "") or "")
        _after_stem = str(after.get("stem", "") or "")
        _raw_text = str(questions[i].get("raw_text") or questions[i].get("raw_question_text") or "")
        _subscript_changes = _detect_subscript_changes(_before_stem, _after_stem, _raw_text)
        if _subscript_changes:
            logger.warning(
                "[SUBSCRIPT-SAFETY] q%d: AI repair changed subscripts without evidence: %s",
                i, _subscript_changes,
            )
            _append_decision_trace(
                questions[i], "ai_repair", "rejected",
                f"subscript_change_without_evidence: {_subscript_changes}",
            )
            unrepaired.append({
                "question_index": i,
                "reason": f"subscript_change_rejected: {_subscript_changes}",
            })
            total_tokens += token_used
            continue

        # ---- AI safety gate: 评估 AI 修复是否可接受 ----
        from app.features.ai_safety import evaluate_and_trace

        before_q = questions[i]
        before_stem = _before_stem
        before_opts = str(before_q.get("options", "") or "")
        before_answer = str(before_q.get("answer", "") or "")
        after_stem = _after_stem
        after_opts = str(after.get("options", "") or "")
        after_answer = str(after.get("answer", "") or "")

        safety_context = {
            "has_options": bool(before_opts or after_opts),
            "stem_context": before_stem[:200],
            "expected_answer": before_answer,
            "after_answer": after_answer,
        }

        safety_trace, _safe_stem = evaluate_and_trace(
            stage="ai_repair",
            model="deepseek",
            before=before_stem,
            after=after_stem,
            context=safety_context,
            tokens_used=token_used + roman_results.get(i, {}).get("token_used", 0),
        )

        if not safety_trace.accepted:
            _append_decision_trace(questions[i], "ai_safety", "blocked", f"safety_rejected: {safety_trace.rollback_reason}")
            unrepaired.append({
                "question_index": i,
                "reason": f"safety_rejected: {safety_trace.rollback_reason}",
            })
            continue

        repair_entry = {
            "question_index": i,
            "before": {k: v for k, v in questions[i].items() if k != "raw_text"},
            "after": after,
            "repair_actions": repair_actions,
            "confidence": result_data.get("confidence", 0),
            "token_used": token_used + roman_results.get(i, {}).get("token_used", 0),
            "safety": safety_trace.to_dict(),
        }
        _append_decision_trace(after, "ai_repair", "repaired", ";".join(repair_actions) if repair_actions else "ai_repaired")
        if safety_trace.risk_flags:
            after.setdefault("risk_flags", [])
            for flag in safety_trace.risk_flags:
                if flag not in after["risk_flags"]:
                    after["risk_flags"].append(flag)
        if ai_result.get("_batch_fallback"):  # L2: mark batch-fallback degradation
            repair_entry["repair_method"] = "batch_fallback"
            after.setdefault("risk_flags", [])
            if "batch_fallback_repair" not in after["risk_flags"]:
                after["risk_flags"] = [*after["risk_flags"], "batch_fallback_repair"]
        repaired.append(repair_entry)

    return {
        "repaired": repaired,
        "unrepaired": unrepaired,
        "skipped": skipped,
        "stats": {
            "total_candidates": len(questions),
            "repaired": len(repaired),
            "unrepaired": len(unrepaired),
            "skipped": len(skipped),
            "total_tokens": total_tokens + roman_total_tokens,
        },
    }

"""AI 修复服务 — 对规则解析失败的低置信度题目进行 AI 辅助修复。

纯规则触发 + DeepSeek API 修复 + token 限额控制 + 静默降级。
不修改上游数据，修复结果需经 Stage 7 审核。
"""

import asyncio
import json
import logging
import re
import time

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_VALID_QUESTION_TYPES = (
    "single_choice", "multiple_choice", "true_false", "fill_blank", "multi_blank_choice", "subjective",
)

# 内存 token 计数器（共享模块，与 ocr_correction 同一预算池）
from app.features.token_budget import (
    estimate_tokens, check_token_limit, record_token_usage, get_token_usage_snapshot,
)

_estimate_tokens = estimate_tokens  # backward-compat alias


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


def _should_repair(
    question: dict,
    threshold: float,
    roman_anomalies: list[dict] | None = None,
) -> tuple[bool, str]:
    if _looks_like_non_question_text(question):
        return False, "non_question_like"

    # 0. Roman numeral anomalies — always trigger repair regardless of confidence
    if roman_anomalies:
        return True, "roman_anomaly"

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
    depth = 0
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
    """
    from app.ai.client import deepseek
    from app.ai.prompts import build_repair_question

    if db is not None and api_key is None:
        from app.services.model_config_resolver import ensure_db_model_configured
        creds = await ensure_db_model_configured(db)
        api_key = creds[0] if creds else None
        base_url = creds[1] if creds else None
        model_name = creds[2] if creds else None

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

    creds = None
    if db is not None:
        from app.services.model_config_resolver import ensure_db_model_configured
        creds = await ensure_db_model_configured(db)

    api_key = creds[0] if creds else None
    base_url = creds[1] if creds else None
    model_name = creds[2] if creds else None

    all_results: list[tuple[int, dict | None]] = []

    # 自动分批（优先使用 config 中的 batch_size，默认 _BATCH_LIMIT）
    batch_limit = config.get("batch_size", _BATCH_LIMIT) or _BATCH_LIMIT
    for batch_start in range(0, len(candidates), batch_limit):
        batch = candidates[batch_start : batch_start + batch_limit]
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
        from app.services.model_config_resolver import ensure_db_model_configured
        creds = await ensure_db_model_configured(db)
        api_key = creds[0] if creds else None
        base_url = creds[1] if creds else None
        model_name = creds[2] if creds else None
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
            _, reason = _should_repair(q, threshold, roman_anomalies=None)
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
                repaired.append(roman_entry)
                total_tokens += roman_results[i].get("token_used", 0)
                continue

        do_repair, reason = _should_repair(q, threshold, roman_anomalies=q_anomalies)
        if not do_repair:
            skipped.append({
                "question_index": i,
                "reason": reason,
                "confidence": q.get("confidence_score", 0),
            })
        else:
            raw_text = q.get("raw_text", "") or q.get("raw_question_text", "")
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

        after = {
            "schema_version": q.get("schema_version", "v1"),
            "subject": q.get("subject", ""),
            "question_type": result_data.get("question_type", q.get("question_type", "")),
            "stem": repaired_stem,
            "options": _normalize_ai_options(result_data.get("options")),
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

        repair_entry = {
            "question_index": i,
            "before": {k: v for k, v in questions[i].items() if k != "raw_text"},
            "after": after,
            "repair_actions": repair_actions,
            "confidence": result_data.get("confidence", 0),
            "token_used": token_used + roman_results.get(i, {}).get("token_used", 0),
        }
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

"""AI complete — fill missing fields for pending question imports.

Extracted from ``question_pipeline.py`` (P5-3).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import fallback
from app.ai.client import llm
from app.ai.gateway import resolve_llm_runtime_config
from app.ai.prompts import (
    build_batch_complete_question,
    build_complete_question,
    build_repair_question,
)
from app.features.question_pipeline import (
    SUBJECT_VALUES,
    TYPE_VALUES,
    _build_log,
    _call_or_fallback,
    _detect_missing,
    _extract_json,
    _get_qi,
    _qi_to_dict,
)
from app.models.question_import import QuestionImport

logger = logging.getLogger(__name__)


async def _get_active_subjects(db: AsyncSession) -> list[dict]:
    """Load active subjects for AI prompt context."""
    from sqlalchemy import select

    from app.models.admin import Subject
    try:
        result = await db.execute(
            select(Subject.id, Subject.code, Subject.name)
            .where(Subject.is_active.is_(True))
            .order_by(Subject.level.asc(), Subject.sort_order.asc())
        )
        return [{"id": r.id, "code": r.code, "name": r.name} for r in result.all()]
    except Exception:
        return []


def _coerce_confidence(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    return None


def _snapshot_options(opts: Any) -> str:
    if not opts:
        return ""
    if isinstance(opts, dict):
        return str(sorted(opts.items()))
    if isinstance(opts, list):
        return str(sorted(
            (str(o.get("key", "")), str(o.get("text", "")))
            for o in opts if isinstance(o, dict)
        ))
    return str(opts)


def _capture_qi_snapshot(qi: QuestionImport) -> dict:
    """Capture before-snapshot of key question fields for change detection."""
    content = qi.parsed_content or {}
    return {
        "stem": str(content.get("text") or ""),
        "answer": str(qi.parsed_answer or ""),
        "options": _snapshot_options(qi.parsed_options),
        "analysis": str(qi.parsed_analysis or ""),
    }


def _diff_complete_risk(before: dict, qi: QuestionImport) -> list[str]:
    """Diff before/after snapshot and return risk flags for significant changes."""
    risk_flags: list[str] = []
    content = qi.parsed_content or {}

    after_stem = str(content.get("text") or "")
    if before.get("stem") and after_stem and before["stem"] != after_stem:
        risk_flags.append("complete_changed_stem")

    after_answer = str(qi.parsed_answer or "")
    if not before.get("answer") and after_answer:
        risk_flags.append("complete_generated_answer")
        risk_flags.append("complete_changed_answer")
    elif before.get("answer") and after_answer and before["answer"] != after_answer:
        risk_flags.append("complete_changed_answer")

    after_options = _snapshot_options(qi.parsed_options)
    if before.get("options") and after_options and before["options"] != after_options:
        risk_flags.append("complete_changed_options")

    return risk_flags


def _has_complete_answer_risk(ai_metadata: dict | None) -> bool:
    """Check if complete stage changed/generated the answer (high risk for enrich)."""
    if not ai_metadata:
        return False
    risk_flags = ai_metadata.get("_complete_risk_flags") or []
    return bool(set(risk_flags) & {"complete_changed_answer", "complete_generated_answer"})


def _apply_complete_suggestion(
    qi: QuestionImport, parsed: dict, missing: list[str]
) -> dict:
    suggestion: dict = {}
    if "subject" in missing or "subject_id" in missing:
        sid = parsed.get("subject_id")
        if isinstance(sid, int) and sid > 0:
            qi.subject_id = sid
            suggestion["subject_id"] = sid
    if "question_type" in missing and parsed.get("question_type") in TYPE_VALUES:
        qi.question_type = parsed["question_type"]
        suggestion["question_type"] = parsed["question_type"]
    if "analysis" in missing:
        a = parsed.get("analysis")
        if isinstance(a, str) and a.strip():
            qi.parsed_analysis = a.strip()
            suggestion["analysis"] = a.strip()
    if "answer" in missing:
        ans = parsed.get("answer")
        if isinstance(ans, str) and ans.strip():
            suggestion["answer"] = ans.strip()
            qi.ai_answer_flag = True
            qi.answer_status = "ai_filled"
            qi.answer_source = "ai"
            qi.answer_confidence = _coerce_confidence(parsed.get("confidence"))
    if isinstance(parsed.get("knowledge_points"), list):
        suggestion["knowledge_points"] = [
            str(k).strip() for k in parsed["knowledge_points"] if str(k).strip()
        ]
    if isinstance(parsed.get("difficulty"), (int, float)):
        suggestion["difficulty"] = max(1, min(5, int(parsed["difficulty"])))
    return suggestion


# ---------------------------------------------------------------------------
# Completion auto-switch → field mapping
# ---------------------------------------------------------------------------

_COMPLETION_AUTO_MAP: dict[str, str] = {
    "stem": "completion_auto_stem",
    "options": "completion_auto_options",
    "analysis": "completion_auto_answer_reasoning",
    "knowledge_points": "completion_auto_knowledge_tags",
}


def _get_disabled_completion_fields(configs: dict) -> set[str]:
    """Return set of fields disabled by admin_ai_configs completion_auto_* switches."""
    disabled: set[str] = set()
    for field, cfg_key in _COMPLETION_AUTO_MAP.items():
        if not configs.get(cfg_key, True):
            disabled.add(field)
    return disabled


# ---------------------------------------------------------------------------
# Detail-level complete
# ---------------------------------------------------------------------------


async def _complete_import_repair(
    db: AsyncSession, user_id: int, qi: QuestionImport,
    system_prompt: str | None = None,
) -> dict:
    """AI 修复模式：使用 question_repair prompt 重建题目结构。"""
    raw_data = dict(qi.raw_data or {})
    raw_text = (
        raw_data.get("raw_text")
        or raw_data.get("text")
        or str(raw_data)
    )
    existing = _qi_to_dict(qi)

    messages = build_repair_question(raw_text, existing)
    if system_prompt:
        messages[0] = {"role": "system", "content": system_prompt}

    prompt_text = json.dumps(messages, ensure_ascii=False)
    resp, raw, _ = await _call_or_fallback(
        messages, {"error": "AI 修复不可用"}, db,
    )

    if raw is None:
        db.add(_build_log(
            user_id=user_id, action="complete", target_type="import",
            target_id=qi.id, batch_id=qi.batch_id, prompt_text=prompt_text,
            raw_response=None, parsed_result=resp.get("fallback_value", {}),
            confidence=0.0, model="fallback", tokens_used=0, duration_ms=0,
            success=False, error_message=resp.get("error") or "AI 修复不可用",
        ))
        return {"missing": [], "from_fallback": True, "ai_metadata": {}, "repair_mode": True}

    parsed_raw = _extract_json(raw) or {}
    repair_fields = [f for f in ("stem", "options", "answer", "analysis", "subject_id", "question_type")
                     if f in parsed_raw or f in existing or
                     (f == "subject_id" and ("subject" in parsed_raw or "subject_id" in parsed_raw))]
    completed = await _apply_batch_complete_result(qi, parsed_raw, repair_fields, "force_overwrite", db=db)
    confidence = _coerce_confidence(parsed_raw.get("confidence"))

    qi.ai_generated = True
    qi.ai_source = "repair"
    qi.ai_confidence = confidence
    qi.ai_metadata = {
        **(qi.ai_metadata or {}),
        "repair_suggestion": {f: parsed_raw.get(f) for f in repair_fields if f in parsed_raw},
        "repair_mode": True,
        "missing_fields": [],
    }
    qi.ai_raw_response = raw

    db.add(_build_log(
        user_id=user_id, action="complete", target_type="import",
        target_id=qi.id, batch_id=qi.batch_id, prompt_text=prompt_text,
        raw_response=raw, parsed_result=qi.ai_metadata,
        confidence=confidence,
        model=resp["model"], tokens_used=resp["tokens_used"],
        duration_ms=resp["duration_ms"], success=True,
    ))
    return {
        "missing": [],
        "from_fallback": False,
        "ai_metadata": qi.ai_metadata,
        "tokens_used": resp["tokens_used"],
        "duration_ms": resp["duration_ms"],
        "repair_mode": True,
        "completed_fields": completed,
    }


async def complete_import(
    db: AsyncSession, user_id: int, import_id: int
) -> dict:
    qi = await _get_qi(db, import_id)
    if qi.status != "pending":
        raise ValueError("仅支持对 pending 记录使用 AI 补全")

    missing = _detect_missing(qi)

    system_prompt: str | None = None
    repair_mode: bool = False
    try:
        from app.services.admin_ai_config_service import get_all_configs as _get_cfg
        _cfg = await _get_cfg(db)
        system_prompt = str(_cfg.get("completion_prompt")) if _cfg.get("completion_prompt") else None
        repair_mode = bool(_cfg.get("completion_repair_structure", False))
        if not repair_mode:
            _disabled = _get_disabled_completion_fields(_cfg)
            if _disabled:
                missing = [f for f in missing if f not in _disabled]
    except Exception:
        pass

    if repair_mode:
        return await _complete_import_repair(db, user_id, qi, system_prompt)
    if not missing:
        return {"missing": [], "from_fallback": False, "ai_metadata": {}}

    subject_list = await _get_active_subjects(db)
    messages = build_complete_question(_qi_to_dict(qi), missing, system_prompt=system_prompt, subject_list=subject_list)
    prompt_text = json.dumps(messages, ensure_ascii=False)
    resp, raw, _ = await _call_or_fallback(
        messages, fallback.get_fallback_complete(missing), db
    )

    if raw is None:
        parsed = resp["fallback_value"]
        db.add(_build_log(
            user_id=user_id, action="complete", target_type="import",
            target_id=qi.id, batch_id=qi.batch_id, prompt_text=prompt_text,
            raw_response=None, parsed_result=parsed, confidence=0.0,
            model=resp["model"], tokens_used=0, duration_ms=0,
            success=False, error_message=resp.get("error"),
        ))
        return {"missing": missing, "from_fallback": True, "ai_metadata": parsed}

    parsed_raw = _extract_json(raw) or {}

    before_snapshot = _capture_qi_snapshot(qi)
    suggestion = _apply_complete_suggestion(qi, parsed_raw, missing)

    complete_risk_flags = _diff_complete_risk(before_snapshot, qi)
    if complete_risk_flags:
        logger.info(
            "P3-5: complete_import %d risk flags: %s", import_id, complete_risk_flags,
        )

    answer_uncertain = bool(parsed_raw.get("answer_uncertain"))
    confidence = _coerce_confidence(parsed_raw.get("confidence"))

    qi.ai_generated = True
    qi.ai_source = "complete"
    qi.ai_confidence = confidence
    qi.ai_metadata = {
        **(qi.ai_metadata or {}),
        "complete_suggestion": suggestion,
        "answer_uncertain": answer_uncertain or bool(complete_risk_flags),
        "reason": parsed_raw.get("reason"),
        "missing_fields": missing,
        "_complete_risk_flags": complete_risk_flags,
        "_complete_before_snapshot": before_snapshot,
    }
    qi.ai_raw_response = raw

    # 单题补全的 knowledge_points/difficulty 同步到顶层 ai_metadata（与批量
    # 路径 _apply_batch_complete_result 一致）。发布时 question_publish_service
    # 只读 ai_metadata["knowledge_points"]/["difficulty"]，仅写在
    # complete_suggestion 里会在发布时丢失。
    if suggestion.get("knowledge_points"):
        qi.ai_metadata["knowledge_points"] = suggestion["knowledge_points"]
    if suggestion.get("difficulty") is not None:
        qi.ai_metadata["difficulty"] = suggestion["difficulty"]

    from app.core.ai_trace import AIEditTrace
    complete_trace = AIEditTrace(
        stage="ai_complete",
        model=resp.get("model", "unknown"),
        before=str(_qi_to_dict(qi))[:500],
        after=str(qi.ai_metadata)[:500],
        tokens_used=resp.get("tokens_used", 0),
        duration_ms=resp.get("duration_ms", 0),
    )
    qi.ai_metadata["_trace"] = complete_trace.to_dict()

    db.add(_build_log(
        user_id=user_id, action="complete", target_type="import",
        target_id=qi.id, batch_id=qi.batch_id, prompt_text=prompt_text,
        raw_response=raw, parsed_result=qi.ai_metadata,
        confidence=confidence,
        model=resp["model"], tokens_used=resp["tokens_used"],
        duration_ms=resp["duration_ms"], success=True,
    ))
    return {
        "missing": missing,
        "from_fallback": False,
        "ai_metadata": qi.ai_metadata,
        "tokens_used": resp["tokens_used"],
        "duration_ms": resp["duration_ms"],
    }


# ---------------------------------------------------------------------------
# Field-level complete (with strategy)
# ---------------------------------------------------------------------------


def _detect_fields_to_complete(
    qi: QuestionImport, target_fields: list[str], strategy: str,
    disabled_fields: set[str] | None = None,
) -> list[str]:
    # Normalize legacy "subject" → "subject_id" regardless of strategy
    normalized_fields = ["subject_id" if f == "subject" else f for f in target_fields]
    if strategy == "force_overwrite":
        if disabled_fields:
            return [f for f in normalized_fields if f not in disabled_fields]
        return list(normalized_fields)

    need: list[str] = []
    for field in target_fields:
        norm_field = "subject_id" if field == "subject" else field
        if disabled_fields and norm_field in disabled_fields:
            continue
        if norm_field == "subject_id" and not qi.subject_id:
            need.append("subject_id")
        elif field == "question_type" and not qi.question_type:
            need.append("question_type")
        elif field == "stem" and not (qi.parsed_content and qi.parsed_content.get("text")):
            need.append("stem")
        elif field == "answer" and not qi.parsed_answer:
            need.append("answer")
        elif field == "analysis" and not qi.parsed_analysis:
            need.append("analysis")
        elif field == "options" and not qi.parsed_options:
            need.append("options")
        elif field == "knowledge_points":
            meta = qi.ai_metadata or {}
            if not meta.get("knowledge_points"):
                need.append("knowledge_points")
        elif field == "difficulty":
            meta = qi.ai_metadata or {}
            if not meta.get("difficulty"):
                need.append("difficulty")
        elif field in ("tips", "tags"):
            meta = qi.ai_metadata or {}
            if not meta.get(field):
                need.append(field)
    return need


async def _apply_batch_complete_result(
    qi: QuestionImport, parsed: dict, fields: list[str], strategy: str,
    db: AsyncSession | None = None,
) -> list[str]:
    completed: list[str] = []

    def _should_apply(field: str) -> bool:
        return strategy == "force_overwrite" or field in fields

    if "subject_id" in fields or "subject" in fields:
        sid = parsed.get("subject_id")
        if isinstance(sid, int) and sid > 0:
            qi.subject_id = sid
            completed.append("subject_id")
        elif parsed.get("subject") in SUBJECT_VALUES and db is not None:
            # Backward compat: AI returned old-style subject string → resolve to subject_id
            from app.services.admin_subject_service import resolve_subject_id
            resolved = await resolve_subject_id(db, parsed["subject"])
            if resolved is not None:
                qi.subject_id = resolved
                completed.append("subject_id")
            else:
                logger.debug(
                    "AI complete: legacy subject=%r cannot be resolved, skipping",
                    parsed["subject"],
                )

    if "question_type" in fields and parsed.get("question_type") in TYPE_VALUES:
        qi.question_type = parsed["question_type"]
        completed.append("question_type")

    if _should_apply("analysis"):
        a = parsed.get("analysis")
        if isinstance(a, str) and a.strip():
            qi.parsed_analysis = a.strip()
            completed.append("analysis")

    if "answer" in fields:
        ans = parsed.get("answer")
        if isinstance(ans, str) and ans.strip():
            qi.parsed_answer = ans
            qi.ai_answer_flag = True
            qi.answer_status = "ai_filled"
            qi.answer_source = "ai"
            qi.answer_confidence = _coerce_confidence(parsed.get("confidence"))
            completed.append("answer")

    if "stem" in fields:
        stem_val = parsed.get("stem") or (parsed.get("parsed_content") or {}).get("text")
        if isinstance(stem_val, str) and stem_val.strip():
            from app.services.pdf_text_normalizer import deduplicate_repeated_text
            content = dict(qi.parsed_content or {})
            content["text"] = deduplicate_repeated_text(stem_val.strip())
            qi.parsed_content = content
            completed.append("stem")

    if "options" in fields:
        opts = parsed.get("options") or parsed.get("parsed_options")
        if isinstance(opts, dict) and opts:
            qi.parsed_options = opts
            completed.append("options")
        elif isinstance(opts, list) and opts:
            qi.parsed_options = {str(i): o for i, o in enumerate(opts) if o}
            completed.append("options")

    qi.ai_generated = True
    qi.ai_source = "batch_complete"
    ai_meta = dict(qi.ai_metadata or {})

    if "knowledge_points" in fields:
        kps = parsed.get("knowledge_points")
        if isinstance(kps, list) and kps:
            ai_meta["knowledge_points"] = [str(k).strip() for k in kps if str(k).strip()]
            completed.append("knowledge_points")

    if "difficulty" in fields:
        diff = parsed.get("difficulty")
        if isinstance(diff, (int, float)):
            ai_meta["difficulty"] = max(1, min(5, int(diff)))
            completed.append("difficulty")

    if "tips" in fields:
        tips = parsed.get("tips") or parsed.get("solving_tips")
        if isinstance(tips, str) and tips.strip():
            ai_meta["tips"] = tips.strip()
            completed.append("tips")

    if "tags" in fields:
        tags = parsed.get("tags")
        if isinstance(tags, list) and tags:
            ai_meta["tags"] = [str(t).strip() for t in tags if str(t).strip()]
            completed.append("tags")

    qi.ai_metadata = ai_meta
    return completed


async def complete_import_with_strategy(
    db: AsyncSession,
    user_id: int,
    import_id: int,
    target_fields: list[str],
    strategy: str,
    disabled_fields: set[str] | None = None,
    system_prompt: str | None = None,
) -> dict:
    """带字段选择和策略的 AI 补全。不提交事务，供 batch 调用。"""
    qi = await _get_qi(db, import_id)
    if qi.status != "pending":
        return {"completed": [], "from_fallback": False, "ai_metadata": {}, "error": f"非 pending 状态: {qi.status}"}

    to_complete = _detect_fields_to_complete(qi, target_fields, strategy, disabled_fields)
    if not to_complete:
        return {"completed": [], "from_fallback": False, "ai_metadata": {}}

    subject_list = await _get_active_subjects(db)
    messages = build_batch_complete_question(_qi_to_dict(qi), to_complete, strategy, system_prompt=system_prompt, subject_list=subject_list)
    prompt_text = json.dumps(messages, ensure_ascii=False)
    resp, raw, _ = await _call_or_fallback(
        messages, fallback.get_fallback_complete(to_complete), db
    )

    if raw is None:
        parsed = resp["fallback_value"]
        db.add(_build_log(
            user_id=user_id, action="batch_complete", target_type="import",
            target_id=qi.id, batch_id=qi.batch_id, prompt_text=prompt_text,
            raw_response=None, parsed_result=parsed, confidence=0.0,
            model=resp["model"], tokens_used=0, duration_ms=0,
            success=False, error_message=resp.get("error"),
        ))
        return {"completed": [], "from_fallback": True, "ai_metadata": parsed, "error": resp.get("error")}

    parsed_raw = _extract_json(raw) or {}

    before_snapshot = _capture_qi_snapshot(qi)
    completed = await _apply_batch_complete_result(qi, parsed_raw, to_complete, strategy, db=db)

    complete_risk_flags = _diff_complete_risk(before_snapshot, qi)
    if complete_risk_flags:
        logger.info(
            "P3-5: complete_import_with_strategy %d risk flags: %s",
            import_id, complete_risk_flags,
        )

    confidence = _coerce_confidence(parsed_raw.get("confidence"))

    qi.ai_confidence = confidence
    qi.ai_raw_response = raw
    existing_meta = dict(qi.ai_metadata or {})
    existing_meta["_complete_risk_flags"] = complete_risk_flags
    existing_meta["_complete_before_snapshot"] = before_snapshot
    qi.ai_metadata = existing_meta

    db.add(_build_log(
        user_id=user_id, action="batch_complete", target_type="import",
        target_id=qi.id, batch_id=qi.batch_id, prompt_text=prompt_text,
        raw_response=raw, parsed_result=qi.ai_metadata,
        confidence=confidence,
        model=resp["model"], tokens_used=resp["tokens_used"],
        duration_ms=resp["duration_ms"], success=True,
    ))
    return {
        "completed": completed,
        "from_fallback": False,
        "ai_metadata": qi.ai_metadata,
        "tokens_used": resp["tokens_used"],
        "duration_ms": resp["duration_ms"],
    }


# ---------------------------------------------------------------------------
# Batch complete
# ---------------------------------------------------------------------------


async def batch_complete_questions(
    db: AsyncSession,
    user_id: int,
    import_ids: list[int],
    target_fields: list[str],
    strategy: str,
    max_concurrency: int = 3,
    skip_budget_check: bool = False,
) -> dict:
    """批量 AI 补全。外部需自行 commit。"""
    _start_time = datetime.now()
    disabled_fields: set[str] = set()
    system_prompt: str | None = None
    from app.services.admin_ai_config_service import get_all_configs
    try:
        cfg = await get_all_configs(db)
        disabled_fields = _get_disabled_completion_fields(cfg)
        system_prompt = str(cfg.get("completion_prompt")) if cfg.get("completion_prompt") else None
    except Exception:
        pass

    runtime = await resolve_llm_runtime_config(db, feature="completion")

    # Step 1: 顺序预读取所有 QI
    subject_list = await _get_active_subjects(db)
    prepared: list[dict] = []
    for import_id in import_ids:
        try:
            qi = await _get_qi(db, import_id)
            if qi.status != "pending":
                prepared.append(dict(
                    import_id=import_id, status="failed",
                    error=f"非 pending 状态: {qi.status}", completed_fields=[],
                ))
                continue

            to_complete = _detect_fields_to_complete(qi, target_fields, strategy, disabled_fields)
            if not to_complete:
                prepared.append(dict(
                    import_id=import_id, status="skipped",
                    error=None, completed=[],
                ))
                continue

            messages = build_batch_complete_question(
                _qi_to_dict(qi), to_complete, strategy, system_prompt=system_prompt,
                subject_list=subject_list,
            )
            prompt_text = json.dumps(messages, ensure_ascii=False)
            prepared.append(dict(
                import_id=import_id, qi=qi, to_complete=to_complete,
                messages=messages, prompt_text=prompt_text,
                fallback_value=fallback.get_fallback_complete(to_complete),
            ))
        except Exception as e:
            prepared.append(dict(
                import_id=import_id, status="failed",
                error=str(e), completed_fields=[],
            ))

    # Step 2: 并发调用 AI
    sem = asyncio.Semaphore(max_concurrency or 3)

    async def _do_ai_call(item: dict) -> dict:
        if "messages" not in item:
            return item
        async with sem:
            if runtime is None:
                item["resp_raw"] = None
                item["parsed_raw"] = item["fallback_value"]
                item["error"] = "AI模型API Key未配置"
                return item
            if not skip_budget_check:
                from app.core.config import settings
                from app.features.token_budget import check_token_limit, estimate_tokens
                _estimated = estimate_tokens(json.dumps(item["messages"], ensure_ascii=False)) * 3
                if not await check_token_limit(_estimated, {
                    "daily_token_limit": settings.AI_DAILY_TOKEN_LIMIT,
                    "monthly_token_limit": settings.AI_MONTHLY_TOKEN_LIMIT,
                }):
                    item["resp_raw"] = None
                    item["parsed_raw"] = item["fallback_value"]
                    item["error"] = "token_budget_exhausted"
                    return item
            try:
                resp = await llm.chat(
                    item["messages"],
                    model=runtime.model_name,
                    api_key=runtime.api_key,
                    base_url=runtime.base_url,
                    provider=runtime.provider,
                )
                item["resp_raw"] = resp["content"]
                item["parsed_raw"] = _extract_json(resp["content"]) or {}
                item["tokens_used"] = resp["tokens_used"]
                item["duration_ms"] = resp["duration_ms"]
                item["model"] = resp["model"]
            except RuntimeError as e:
                item["resp_raw"] = None
                item["parsed_raw"] = item["fallback_value"]
                item["error"] = str(e)
            except Exception as e:
                item["resp_raw"] = None
                item["parsed_raw"] = item["fallback_value"]
                item["error"] = str(e)
            return item

    ai_results = await asyncio.gather(
        *[_do_ai_call(item) for item in prepared], return_exceptions=True,
    )

    # Step 3: 顺序应用结果到 DB
    succeeded = 0
    failed = 0
    skipped = 0
    results: list[dict] = []

    for item in ai_results:
        if not isinstance(item, dict):
            skipped += 1
            results.append(dict(import_id=-1, status="failed", error=str(item), completed_fields=[]))
            continue

        import_id = item["import_id"]

        if item.get("status") == "failed":
            failed += 1
            results.append(dict(
                import_id=import_id, status="failed",
                error=item.get("error"), completed_fields=[],
            ))
            continue
        if item.get("status") == "skipped":
            skipped += 1
            results.append(dict(
                import_id=import_id, status="skipped",
                error=None, completed_fields=[],
            ))
            continue

        if item.get("resp_raw") is None:
            qi = item["qi"]
            fbv = item["parsed_raw"]
            db.add(_build_log(
                user_id=user_id, action="batch_complete", target_type="import",
                target_id=qi.id, batch_id=qi.batch_id, prompt_text=item["prompt_text"],
                raw_response=None, parsed_result=fbv, confidence=0.0,
                model="fallback", tokens_used=0, duration_ms=0,
                success=False, error_message=item.get("error"),
            ))
            failed += 1
            results.append(dict(import_id=import_id, status="failed", error=item.get("error"), completed_fields=[]))
            continue

        qi = item["qi"]
        parsed_raw = item["parsed_raw"]
        to_complete = item["to_complete"]

        before_snapshot = _capture_qi_snapshot(qi)
        completed = await _apply_batch_complete_result(qi, parsed_raw, to_complete, strategy, db=db)

        complete_risk_flags = _diff_complete_risk(before_snapshot, qi)
        if complete_risk_flags:
            logger.info("P3-5: batch_complete %d risk flags: %s", import_id, complete_risk_flags)

        confidence = _coerce_confidence(parsed_raw.get("confidence"))

        qi.ai_confidence = confidence
        qi.ai_raw_response = item["resp_raw"]
        existing_meta = dict(qi.ai_metadata or {})
        existing_meta["_complete_risk_flags"] = complete_risk_flags
        existing_meta["_complete_before_snapshot"] = before_snapshot
        qi.ai_metadata = existing_meta

        db.add(_build_log(
            user_id=user_id, action="batch_complete", target_type="import",
            target_id=qi.id, batch_id=qi.batch_id, prompt_text=item["prompt_text"],
            raw_response=item["resp_raw"], parsed_result=qi.ai_metadata,
            confidence=confidence,
            model=item.get("model", "fallback"),
            tokens_used=item.get("tokens_used", 0),
            duration_ms=item.get("duration_ms", 0), success=True,
        ))

        if completed:
            succeeded += 1
        else:
            skipped += 1
        results.append(dict(
            import_id=import_id,
            status="success" if completed else "skipped",
            error=None, completed_fields=completed,
        ))

    total_tokens = sum(
        item.get("tokens_used", 0) for item in ai_results if isinstance(item, dict)
    )
    if total_tokens:
        from app.features.token_budget import record_token_usage
        await record_token_usage(total_tokens)

    _duration_ms = int((datetime.now() - _start_time).total_seconds() * 1000)

    return {
        "total": len(import_ids),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "items": results,
        "complete_stats": {
            "total": len(import_ids),
            "success": succeeded,
            "failed": failed,
            "skipped": skipped,
            "concurrency": max_concurrency,
            "duration_ms": _duration_ms,
            "tokens_used": total_tokens,
        },
    }

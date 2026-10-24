"""Normalize learning-AI provider payloads without provider or database IO."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime


def extract_json_object(content: object) -> dict | None:
    """Extract one JSON object without attempting lossy repair."""
    text_value = str(content or "").strip()
    if not text_value:
        return None
    if text_value.startswith("```"):
        first_newline = text_value.find("\n")
        if first_newline >= 0:
            text_value = text_value[first_newline + 1 :]
        if text_value.endswith("```"):
            text_value = text_value[:-3].rstrip()
    left = text_value.find("{")
    right = text_value.rfind("}")
    if left >= 0 and right > left:
        text_value = text_value[left : right + 1]
    try:
        parsed = json.loads(text_value)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def normalize_text_list(
    value: object, *, limit: int, max_chars: int = 240
) -> list[str]:
    """Keep only bounded non-empty strings from a provider text array."""
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text_value = item.strip()
        if not text_value:
            continue
        result.append(text_value[:max_chars])
        if len(result) >= limit:
            break
    return result


def normalize_dashboard_actions(value: object, *, limit: int = 4) -> list[dict]:
    """Keep only bounded, typed action objects for the dashboard UI."""
    action_types = frozenset({"review", "wrong", "practice", "subject"})
    if not isinstance(value, list):
        return []
    result: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type") or "").strip().lower()
        if action_type not in action_types:
            continue
        raw_title = item.get("title")
        raw_desc = item.get("desc")
        title = raw_title.strip() if isinstance(raw_title, str) else ""
        desc = raw_desc.strip() if isinstance(raw_desc, str) else ""
        if not title:
            continue
        result.append(
            {
                "type": action_type,
                "title": title[:80],
                "desc": desc[:220],
            }
        )
        if len(result) >= limit:
            break
    return result


def normalize_knowledge_points(value: object, *, limit: int) -> list[dict]:
    """Normalize provider knowledge-point objects and clamp accuracy."""
    if not isinstance(value, list):
        return []
    normalized: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        raw_name = item.get("knowledge_point")
        raw_suggestion = item.get("suggestion")
        if not isinstance(raw_name, str):
            continue
        name = raw_name.strip()
        suggestion = raw_suggestion.strip() if isinstance(raw_suggestion, str) else ""
        if not name:
            continue
        try:
            score = float(item.get("accuracy", 0) or 0)
        except (TypeError, ValueError):
            score = 0.0
        if score > 1:
            score = score / 100.0
        score = max(0.0, min(1.0, score))
        normalized.append(
            {
                "knowledge_point": name[:80],
                "accuracy": round(score, 4),
                "suggestion": suggestion[:240],
            }
        )
        if len(normalized) >= limit:
            break
    return normalized


def build_knowledge_point_stats(subject_rows: list) -> list[dict]:
    """Project recent wrong-question subject rows into prompt statistics."""
    stats: list[dict] = []
    for row in subject_rows:
        subject = row[0]
        total = int(row[1] or 0)
        mastered = int(row[2] or 0)
        mastery_rate = round(mastered / total, 2) if total > 0 else 0.0
        stats.append(
            {
                "knowledge_point": subject,
                "mastery_rate": mastery_rate,
                "mastered": mastered,
                "total_wrong": total,
            }
        )
    return stats


def build_local_ai_diagnosis(
    *,
    knowledge_point_stats: list[dict],
    subject_count: int,
    total_questions: int,
    provider_failed: bool = False,
) -> dict:
    """Build the deterministic wrong-question diagnosis fallback."""
    weak = sorted(
        (item for item in knowledge_point_stats if item["mastery_rate"] < 0.5),
        key=lambda item: (item["mastery_rate"], -item["total_wrong"]),
    )
    strong = sorted(
        (item for item in knowledge_point_stats if item["mastery_rate"] >= 0.7),
        key=lambda item: (-item["mastery_rate"], -item["total_wrong"]),
    )
    suggestions: list[str] = []
    if weak:
        suggestions.append(
            f"优先复盘{weak[0]['knowledge_point']}错题，"
            f"当前错题掌握率约{int(weak[0]['mastery_rate'] * 100)}%"
        )
    if len(weak) > 1:
        suggestions.append(
            f"其次巩固{weak[1]['knowledge_point']}，建议集中完成一轮错题复盘"
        )
    if total_questions < 50:
        suggestions.append("当前练习样本较少，累计到 50 题以上后洞察会更稳定")
    suggestions.append("优先处理重复出错且尚未掌握的题目，并按复习计划回看")
    return {
        "weak_points": [
            {
                "knowledge_point": item["knowledge_point"],
                "accuracy": item["mastery_rate"],
                "suggestion": "建议针对性复盘并完成一次间隔复习",
            }
            for item in weak[:3]
        ],
        "strong_points": [
            {
                "knowledge_point": item["knowledge_point"],
                "accuracy": item["mastery_rate"],
                "suggestion": "已较好掌握错题，保持当前复习节奏",
            }
            for item in strong[:2]
        ],
        "learning_suggestions": suggestions[:5],
        "summary": (
            "AI 模型响应较慢，本次先基于最近 60 天错题数据生成即时洞察；可稍后刷新获取 AI 增强分析。"
            if provider_failed
            else f"基于最近60天{subject_count}个科目的错题数据生成诊断。"
        ),
        "generated": False,
    }


def build_dashboard_ai_payload(
    *,
    overview: dict,
    subject_items: list[dict],
    trends: list[dict],
    forgetting: dict,
    trend_days: int,
) -> dict:
    """Build the bounded aggregate payload sent to the learning LLM."""
    strong_subj = max(subject_items, key=lambda item: item["accuracy"]) if subject_items else None
    weak_subj = min(subject_items, key=lambda item: item["accuracy"]) if subject_items else None
    trend_total = sum(point.get("questions", 0) for point in trends)
    trend_correct = sum(point.get("correct", 0) for point in trends)
    trend_active = sum(1 for point in trends if point.get("questions", 0) > 0)
    return {
        "overview": {
            "today_questions": overview["today_questions"],
            "today_accuracy": round(
                overview["today_correct"] / max(1, overview["today_questions"]), 4
            )
            if overview["today_questions"] > 0
            else 0.0,
            "due_review_count": overview["due_review_count"],
            "consecutive_days": overview["consecutive_days"],
            "total_questions": overview["total_questions"],
            "total_accuracy": overview["accuracy"],
        },
        "trends": {
            "days": trend_days,
            "total_questions": trend_total,
            "active_days": trend_active,
            "avg_accuracy": round(trend_correct / trend_total, 4)
            if trend_total > 0
            else 0.0,
        },
        "subjects": {
            "strongest": strong_subj["label"] if strong_subj else None,
            "weakest": weak_subj["label"] if weak_subj else None,
            "items": [
                {
                    "label": item["label"],
                    "accuracy": item["accuracy"],
                    "total_questions": item["total_questions"],
                }
                for item in subject_items[:12]
            ],
        },
        "review_risk": {
            "high_forget_count": forgetting.get("high_forget_count", 0),
            "stuck_questions": forgetting.get("stuck_questions", 0),
            "top_topics": forgetting.get("top_forgotten_topics", [])[:5],
        },
    }


def build_dashboard_ai_response(
    *,
    parsed: dict,
    ai_response: dict,
    generated_at: str,
) -> dict | None:
    """Normalize a successful provider response, or return None for fallback."""
    raw_summary = parsed.get("summary")
    summary = raw_summary.strip()[:320] if isinstance(raw_summary, str) else ""
    findings = normalize_text_list(parsed.get("findings"), limit=6)
    risks = normalize_text_list(parsed.get("risks"), limit=4)
    actions = normalize_dashboard_actions(parsed.get("actions"), limit=4)
    if not summary and not findings and not risks and not actions:
        return None
    return {
        "summary": summary or "已根据当前学习数据生成诊断。",
        "findings": findings,
        "risks": risks,
        "actions": actions,
        "generated_at": generated_at,
        "model": str(ai_response.get("model") or "") or None,
        "generated": True,
    }


def build_dashboard_ai_prompt(payload: dict, trend_days: int) -> list[dict]:
    """Build the fixed JSON-output prompt for the dashboard LLM."""
    system_prompt = (
        "你是一个学习数据分析助手。你只能根据输入的学习统计数据生成简洁、可执行的学习诊断。"
        "不要编造输入中不存在的数据。不要输出泛泛鸡汤。"
        "请用 JSON 返回，格式为："
        '{"summary": "一句话总结", "findings": ["发现1", "发现2"], "risks": ["风险1"], '
        '"actions": [{"type": "review|wrong|practice|subject", "title": "行动标题", "desc": "行动描述"}]}'
    )
    user_prompt = (
        f"以下是一位考研学生近 {trend_days} 天的学习统计数据，请生成诊断。\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def build_rule_based_dashboard_analysis(
    payload: dict,
    trend_days: int,
    *,
    now: datetime,
    serialize_now: Callable[[datetime], str],
) -> dict:
    """Build the deterministic fallback diagnosis when the LLM is unavailable."""
    ov = payload.get("overview", {})
    tr = payload.get("trends", {})
    rr = payload.get("review_risk", {})
    sb = payload.get("subjects", {})

    findings: list[str] = []
    risks: list[str] = []
    actions: list[dict] = []
    total_q = ov.get("total_questions", 0)

    if total_q == 0:
        return {
            "summary": "数据不足，无法生成分析。",
            "findings": ["暂无学习数据，完成第一次练习后生成分析。"],
            "risks": [],
            "actions": [
                {
                    "type": "practice",
                    "title": "开始第一次练习",
                    "desc": "完成练习后回来查看分析。",
                }
            ],
            "generated_at": serialize_now(now),
            "model": "rule-based",
            "generated": False,
        }

    today_q = ov.get("today_questions", 0)
    due = ov.get("due_review_count", 0)
    streak = ov.get("consecutive_days", 0)
    trend_total = tr.get("total_questions", 0)
    active_days = tr.get("active_days", 0)
    avg_acc = tr.get("avg_accuracy", 0)
    hf = rr.get("high_forget_count", 0)
    stuck = rr.get("stuck_questions", 0)
    subject_items = sb.get("items") or []
    weak_item = min(
        (item for item in subject_items if isinstance(item, dict)),
        key=lambda item: float(item.get("accuracy") or 0),
        default=None,
    )
    weak_label = (
        weak_item.get("label")
        if weak_item and float(weak_item.get("accuracy") or 0) < 0.70
        else None
    )
    top_topics = rr.get("top_topics", [])

    findings.append(
        f"近{trend_days}天完成{trend_total}题，活跃{active_days}天，平均正确率{round(avg_acc * 100)}%。"
    )
    if today_q > 0:
        findings.append(f"今日完成{today_q}题，连续学习{streak}天。")
    if total_q > 0:
        findings.append(
            f"累计做题{total_q}题，总正确率{round(ov.get('total_accuracy', 0) * 100)}%。"
        )

    if due > 0:
        findings.append(f"当前有{due}道到期复习。")
        actions.append(
            {
                "type": "review",
                "title": f"先完成{due}道到期复习",
                "desc": "建议优先处理复习任务。",
            }
        )
    if hf > 0:
        risks.append(f"反复出错题目{hf}道，建议集中复盘。")
        actions.append(
            {
                "type": "wrong",
                "title": f"复盘{hf}道高频遗忘错题",
                "desc": "针对高频遗忘点做专项巩固。",
            }
        )
    if stuck > 0:
        risks.append(f"长期未掌握题目{stuck}道，建议优先突破反复卡住的内容。")
        if not any(action.get("type") == "wrong" for action in actions):
            actions.append(
                {
                    "type": "wrong",
                    "title": f"处理{stuck}道长期未掌握题",
                    "desc": "先复盘长期未掌握内容，再继续扩展新题。",
                }
            )
    if weak_label:
        findings.append(f"薄弱学科：{weak_label}。")
        actions.append(
            {
                "type": "subject",
                "title": f"重点看{weak_label}错题",
                "desc": "该学科正确率偏低，建议优先复盘。",
            }
        )
    if top_topics:
        topics_str = "、".join(topic["topic"] for topic in top_topics[:3])
        risks.append(f"高频遗忘知识点：{topics_str}。")

    if not actions:
        actions.append(
            {
                "type": "practice",
                "title": "保持练习节奏",
                "desc": "当前状态良好，继续每日练习。",
            }
        )

    if due == 0 and hf == 0 and stuck == 0 and not weak_label:
        summary = f"学习节奏稳定，累计{total_q}题，连续{streak}天。继续保持！"
    elif due > 0:
        summary = f"学习数据良好，但到期复习{due}道需尽快处理。"
    elif stuck > 0:
        summary = f"当前有{stuck}道长期未掌握题目，建议先集中突破再扩展新题。"
    else:
        summary = (
            f"近{trend_days}天平均正确率{round(avg_acc * 100)}%，建议关注薄弱环节。"
        )

    return {
        "summary": summary,
        "findings": findings[:4],
        "risks": risks[:3],
        "actions": actions[:3],
        "generated_at": serialize_now(now),
        "model": "rule-based",
        "generated": False,
    }

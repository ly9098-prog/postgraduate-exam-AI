"""Pure historical-scope and response projections for chapter knowledge diagnosis."""

from __future__ import annotations

from typing import Any, Callable


def project_chapter_sessions(rows: Any, *, ports: Callable[[str], Any]) -> list[dict]:
    result: list[dict] = []
    for row in rows:
        scope = ports("public_practice_session_scope")(row.scope_snapshot)
        root_id = ports("_int")(row.scope_root_knowledge_point_id)
        if scope is None or root_id <= 0:
            continue
        if ports("_int")(scope.get("root_knowledge_point_id")) != root_id:
            continue
        result.append(
            {
                "request_id": str(row.request_id or ""),
                "root_knowledge_point_id": root_id,
                "root_name": str(scope.get("root_name") or ""),
                "served_ids": {
                    ports("_int")(value)
                    for value in scope.get("served_knowledge_point_ids") or []
                    if ports("_int")(value) > 0
                },
                "resolved_ids": {
                    ports("_int")(value)
                    for value in scope.get("resolved_knowledge_point_ids") or []
                    if ports("_int")(value) > 0
                },
                "served_count": max(
                    0, ports("_int")(scope.get("served_knowledge_point_count"))
                ),
                "resolved_count": max(
                    0, ports("_int")(scope.get("resolved_knowledge_point_count"))
                ),
                "question_count": ports("_int")(row.question_count),
                "correct_count": ports("_int")(row.correct_count),
                "finished_at": row.finished_at,
            }
        )
    return result


def _root_chapter_reports(
    nodes: list[dict], chapter_stats: dict[int, dict], *, ports: Callable[[str], Any]
) -> list[dict]:
    reports: list[dict] = []
    for node in nodes:
        if ports("_int")(node.get("depth")) != 0:
            continue
        kp_id = ports("_int")(node.get("knowledge_point_id"))
        stat = chapter_stats.get(kp_id, {})
        question_count = ports("_int")(stat.get("question_count"))
        mastery = node.get("subtree_mastery_score")
        last_at = stat.get("last_practiced_at")
        reports.append(
            _chapter_report(
                node, kp_id, stat, question_count, mastery, last_at, ports=ports
            )
        )
    return reports


def _chapter_report(
    node: dict,
    kp_id: int,
    stat: dict,
    question_count: int,
    mastery: Any,
    last_at: Any,
    *,
    ports: Callable[[str], Any],
) -> dict:
    return {
        "knowledge_point_id": kp_id,
        "knowledge_point_name": str(node.get("name") or ""),
        "mastery_score": round(ports("_float")(mastery), 1)
        if mastery is not None
        else None,
        "coverage_ratio": round(
            max(0.0, min(1.0, ports("_float")(node.get("subtree_coverage_ratio")))), 4
        ),
        "weak_knowledge_points": ports("_int")(
            node.get("subtree_weak_knowledge_points")
        ),
        "reliable_knowledge_points": ports("_int")(
            node.get("subtree_reliable_knowledge_points")
        ),
        "trainable_knowledge_points": ports("_int")(
            node.get("subtree_trainable_knowledge_points")
        ),
        "session_count": ports("_int")(stat.get("session_count")),
        "last_7_days_session_count": ports("_int")(stat.get("recent_session_count")),
        "question_count": question_count,
        "correct_count": ports("_int")(stat.get("correct_count")),
        "accuracy": ports("_accuracy")(
            ports("_int")(stat.get("correct_count")), question_count
        ),
        "scope_served_knowledge_point_count": ports("_int")(
            stat.get("scope_served_count")
        ),
        "scope_resolved_knowledge_point_count": ports("_int")(
            stat.get("scope_resolved_count")
        ),
        "scope_coverage_ratio": ports("_scope_coverage")(
            ports("_int")(stat.get("scope_served_count")),
            ports("_int")(stat.get("scope_resolved_count")),
        ),
        "last_practiced_at": ports("serialize_utc_datetime")(last_at)
        if isinstance(last_at, ports("datetime"))
        else None,
    }


def recent_session_reports(
    sessions: list[dict], *, ports: Callable[[str], Any]
) -> list[dict]:
    recent_sessions = []
    for session in sessions[: ports("_MAX_RECENT_SESSIONS")]:
        question_count = ports("_int")(session.get("question_count"))
        finished_at = session.get("finished_at")
        if not isinstance(finished_at, ports("datetime")):
            continue
        recent_sessions.append(
            {
                "request_id": str(session.get("request_id") or ""),
                "root_knowledge_point_id": ports("_int")(
                    session.get("root_knowledge_point_id")
                ),
                "root_name": str(session.get("root_name") or ""),
                "question_count": question_count,
                "correct_count": ports("_int")(session.get("correct_count")),
                "accuracy": ports("_accuracy")(
                    ports("_int")(session.get("correct_count")), question_count
                ),
                "served_knowledge_point_count": max(
                    0, ports("_int")(session.get("served_count"))
                ),
                "resolved_knowledge_point_count": max(
                    0, ports("_int")(session.get("resolved_count"))
                ),
                "scope_coverage_ratio": ports("_scope_coverage")(
                    max(0, ports("_int")(session.get("served_count"))),
                    max(0, ports("_int")(session.get("resolved_count"))),
                ),
                "finished_at": ports("serialize_utc_datetime")(finished_at),
            }
        )
    return recent_sessions


def diagnosis_report(
    chapters: list[dict],
    totals: dict,
    subject: dict,
    days: int,
    *,
    ports: Callable[[str], Any],
) -> dict:
    practiced_root_ids = {
        chapter["knowledge_point_id"]
        for chapter in chapters
        if int(chapter["session_count"]) > 0
    }
    total_questions = ports("_int")(totals.get("question_count"))
    report = {
        "period_days": max(1, min(int(days), 365)),
        "session_count": ports("_int")(totals.get("session_count")),
        "last_7_days_session_count": ports("_int")(totals.get("recent_session_count")),
        "question_count": total_questions,
        "correct_count": ports("_int")(totals.get("correct_count")),
        "accuracy": ports("_accuracy")(
            ports("_int")(totals.get("correct_count")), total_questions
        ),
        "practiced_chapter_count": len(practiced_root_ids),
        "served_knowledge_point_count": len(totals.get("served_ids") or set()),
        "scope_served_knowledge_point_count": ports("_int")(
            totals.get("scope_served_count")
        ),
        "scope_resolved_knowledge_point_count": ports("_int")(
            totals.get("scope_resolved_count")
        ),
        "scope_coverage_ratio": totals.get("scope_coverage_ratio"),
        "current_coverage_ratio": round(
            max(0.0, min(1.0, ports("_float")(subject.get("coverage_ratio")))), 4
        ),
        "current_reliable_knowledge_points": ports("_int")(
            subject.get("reliable_knowledge_points")
        ),
        "current_trainable_knowledge_points": ports("_int")(
            subject.get("trainable_knowledge_points")
        ),
        "current_weak_knowledge_points": ports("_int")(
            subject.get("weak_knowledge_points")
        ),
    }
    return report


def diagnosis_response(
    subject_map: dict,
    subject: dict,
    now: Any,
    recommendations: list[dict],
    report: dict,
    chapters: list[dict],
    recent_sessions: list[dict],
    *,
    ports: Callable[[str], Any],
) -> dict:
    return {
        "scope": str(subject_map.get("scope") or "exam408"),
        "subject_id": int(subject["subject_id"]),
        "subject_code": str(subject["subject_code"]),
        "subject_name": str(subject["subject_name"]),
        "period_days": report["period_days"],
        "generated_at": ports("serialize_utc_datetime")(now),
        "primary_recommendation": recommendations[0] if recommendations else None,
        "recommendations": recommendations,
        "report": report,
        "chapters": chapters,
        "recent_sessions": recent_sessions,
    }

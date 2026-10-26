"""Ordered validation stages for submitted practice-session metadata."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any


def normalize_session_timing(
    session_meta: dict, *, ports: Callable[[str], Any],
) -> tuple[datetime, datetime, int]:
    """Resolve UTC instants before validating elapsed and reported duration."""
    started_at = ports("parse_session_datetime")(session_meta.get("started_at"))
    finished_at = ports("parse_session_datetime")(session_meta.get("finished_at"))
    if started_at is None or finished_at is None:
        raise ports("ValueError")("session.start_at / session.finished_at 必须为合法 ISO 时间")
    if finished_at < started_at:
        raise ports("ValueError")("session.finished_at 不得早于 session.started_at")

    duration_sec = session_meta.get("duration_sec")
    try:
        duration_sec = ports("int")(duration_sec) if duration_sec is not None else None
    except (ports("TypeError"), ports("ValueError")):
        raise ports("ValueError")("session.duration_sec 必须为整数")

    wall_sec = ports("max")(0, ports("int")((finished_at - started_at).total_seconds()))
    if duration_sec is None or duration_sec < 0:
        duration_sec = wall_sec
    if duration_sec > wall_sec + ports("_PRACTICE_DURATION_ROUNDING_TOLERANCE"):
        raise ports("ValueError")(
            "session.duration_sec 不得超过 started_at/finished_at 墙钟时长"
        )
    if duration_sec > ports("PRACTICE_SESSION_MAX_DURATION_SEC"):
        raise ports("ValueError")("session.duration_sec 超过允许上限")
    return started_at, finished_at, duration_sec


def normalize_session_identity(
    session_meta: dict, *, ports: Callable[[str], Any],
) -> tuple[str | None, int | None, str]:
    """Validate request identity and scope only after the timing contract."""
    request_id = ports("normalize_practice_request_id")(session_meta.get("request_id"))
    subject_id = session_meta.get("subject_id")
    try:
        subject_id = ports("int")(subject_id) if subject_id is not None else None
    except (ports("TypeError"), ports("ValueError")):
        raise ports("ValueError")("session.subject_id 必须为整数")

    mode = ports("str")(session_meta.get("mode") or "random")
    if mode not in ports("PRACTICE_ALLOWED_MODES"):
        raise ports("ValueError")("session.mode 无效")
    return request_id, subject_id, mode


def normalize_session_question_count(
    session_meta: dict, answered_count: int, *, ports: Callable[[str], Any],
) -> int:
    """Require matching answer counts while tolerating malformed question counts."""
    reported_answered_count = session_meta.get("answered_count")
    try:
        reported_answered_count = ports("int")(reported_answered_count)
    except (ports("TypeError"), ports("ValueError")) as exc:
        raise ports("ValueError")("session.answered_count 必须为整数") from exc
    if reported_answered_count != answered_count:
        raise ports("ValueError")("session.answered_count 与 answers 数量不一致")

    question_count = session_meta.get("question_count")
    try:
        question_count = (
            ports("int")(question_count) if question_count is not None else answered_count
        )
    except (ports("TypeError"), ports("ValueError")):
        question_count = answered_count
    return ports("max")(0, question_count)


def normalize_session_values(
    session_meta: dict,
    *,
    user_id: int,
    answered_count: int,
    total_correct: int,
    total_wrong: int,
    ports: Callable[[str], Any],
) -> dict:
    """Run ordered validation stages and assemble a fresh persistence payload."""
    if not session_meta:
        raise ports("ValueError")("session 不能为空")
    started_at, finished_at, duration_sec = normalize_session_timing(
        session_meta, ports=ports,
    )
    request_id, subject_id, mode = normalize_session_identity(session_meta, ports=ports)
    question_count = normalize_session_question_count(
        session_meta, answered_count, ports=ports,
    )
    return {
        "user_id": user_id,
        "subject_id": subject_id,
        "request_id": request_id,
        "mode": mode,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_sec": duration_sec,
        "question_count": question_count,
        "answered_count": ports("max")(0, answered_count),
        "correct_count": ports("max")(0, total_correct),
        "wrong_count": ports("max")(0, total_wrong),
        "status": "completed",
    }

"""Signed practice batch token contract and validation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from uuid import uuid4

from app.core.config import settings
from app.core.time_utils import utcnow
from app.services.practice.normalization import (
    PRACTICE_ALLOWED_MODES,
    normalize_practice_request_id,
    parse_session_datetime,
)


class PracticeBatchTokenError(ValueError):
    """The signed practice batch token is invalid, expired, or mismatched."""


PRACTICE_BATCH_MAX_QUESTIONS = 50
PRACTICE_BATCH_TOKEN_TTL_SEC = 24 * 60 * 60
PRACTICE_ANSWER_DURATION_TOLERANCE_SEC = 5
PRACTICE_BATCH_CLOCK_SKEW_SEC = 5 * 60
_PRACTICE_BATCH_TOKEN_VERSION = 2


def _practice_batch_signing_key() -> bytes:
    return hmac.new(
        settings.APP_SECRET.encode("utf-8"),
        b"memograd:practice-batch:v2",
        hashlib.sha256,
    ).digest()


def _urlsafe_b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _urlsafe_b64decode(text_value: str) -> bytes:
    padding = "=" * (-len(text_value) % 4)
    return base64.urlsafe_b64decode((text_value + padding).encode("ascii"))


def create_practice_batch_token(
    *,
    user_id: int,
    subject_id: int,
    mode: str,
    questions: list,
    revision_ids: dict[int, int],
    recommendation_request_id: str | None = None,
    knowledge_context: dict | None = None,
    entry_context: dict | None = None,
    sequential_reservation_request_id: str | None = None,
    submission_request_id: str | None = None,
) -> tuple[str | None, dict[int, int], str | None]:
    """Create a signed batch bound to immutable QuestionVersion ids."""
    if not questions:
        return None, {}, None
    normalized_mode = str(mode or "random")
    if normalized_mode not in PRACTICE_ALLOWED_MODES:
        raise PracticeBatchTokenError("练习模式无效")

    revisions: dict[int, int] = {}
    for question in questions:
        question_id = int(question.id)
        if question_id in revisions:
            raise PracticeBatchTokenError("练习批次包含重复题目")
        version_id = revision_ids.get(question_id)
        if not version_id:
            raise RuntimeError(
                f"题目 {question.id} 缺少可用 question_version，题目版本数据不完整"
            )
        revisions[question_id] = int(version_id)

    now = int(time.time())
    submission_request_id = str(
        submission_request_id or f"practice_{uuid4().hex}"
    ).strip()
    if not submission_request_id or len(submission_request_id) > 128:
        raise PracticeBatchTokenError("练习批次 request_id 无效")
    payload = {
        "v": _PRACTICE_BATCH_TOKEN_VERSION,
        "uid": int(user_id),
        "rid": submission_request_id,
        "rec_rid": normalize_practice_request_id(recommendation_request_id),
        "sid": int(subject_id),
        "mode": normalized_mode,
        "iat": now,
        "exp": now + PRACTICE_BATCH_TOKEN_TTL_SEC,
        "questions": [[int(q.id), revisions[int(q.id)]] for q in questions],
    }
    if knowledge_context:
        payload["knowledge_context"] = knowledge_context
    if entry_context:
        payload["entry_context"] = entry_context
    if sequential_reservation_request_id:
        payload["seq_reservation_request_id"] = str(sequential_reservation_request_id)
    body = _urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = _urlsafe_b64encode(
        hmac.new(
            _practice_batch_signing_key(), body.encode("ascii"), hashlib.sha256
        ).digest()
    )
    return f"{body}.{signature}", revisions, submission_request_id


def _decode_practice_batch_token(token: str) -> dict:
    try:
        body, signature = str(token or "").split(".", 1)
        expected = _urlsafe_b64encode(
            hmac.new(
                _practice_batch_signing_key(), body.encode("ascii"), hashlib.sha256
            ).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise PracticeBatchTokenError("练习批次签名无效")
        payload = json.loads(_urlsafe_b64decode(body).decode("utf-8"))
    except PracticeBatchTokenError:
        raise
    except Exception as exc:
        raise PracticeBatchTokenError("练习批次 token 格式无效") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("v") != _PRACTICE_BATCH_TOKEN_VERSION
    ):
        raise PracticeBatchTokenError("练习批次 token 版本无效")
    if int(payload.get("exp") or 0) < int(time.time()):
        raise PracticeBatchTokenError("练习批次已过期，请重新获取题目")
    return payload


def _validate_practice_batch_token(
    token: str,
    *,
    user_id: int,
    question_ids: list[int],
    session_meta: dict,
    answers: list[dict],
) -> tuple[dict[int, int], list[int], dict]:
    payload = _decode_practice_batch_token(token)
    if int(payload.get("uid") or 0) != int(user_id):
        raise PracticeBatchTokenError("练习批次不属于当前用户")

    raw_questions = payload.get("questions")
    if (
        not isinstance(raw_questions, list)
        or not raw_questions
        or len(raw_questions) > PRACTICE_BATCH_MAX_QUESTIONS
    ):
        raise PracticeBatchTokenError("练习批次题目列表无效")
    revisions: dict[int, int] = {}
    issued_order: list[int] = []
    try:
        for item in raw_questions:
            if not isinstance(item, list) or len(item) != 2:
                raise ValueError
            qid = int(item[0])
            revision_id = int(item[1])
            if qid <= 0 or revision_id <= 0 or qid in revisions:
                raise ValueError
            revisions[qid] = revision_id
            issued_order.append(qid)
    except (TypeError, ValueError) as exc:
        raise PracticeBatchTokenError("练习批次题目列表无效") from exc

    submitted_ids = [int(qid) for qid in question_ids]
    if len(submitted_ids) != len(issued_order) or set(submitted_ids) != set(
        issued_order
    ):
        raise PracticeBatchTokenError("提交题目与服务器下发批次不一致")

    try:
        subject_id = int(session_meta.get("subject_id"))
    except (TypeError, ValueError) as exc:
        raise PracticeBatchTokenError("练习批次缺少有效科目") from exc
    if int(payload.get("sid") or 0) != subject_id:
        raise PracticeBatchTokenError("提交科目与服务器下发批次不一致")

    mode = str(session_meta.get("mode") or "random")
    if mode not in PRACTICE_ALLOWED_MODES or str(payload.get("mode") or "") != mode:
        raise PracticeBatchTokenError("提交模式与服务器下发批次不一致")

    token_request_id = str(payload.get("rid") or "").strip()
    session_request_id = normalize_practice_request_id(session_meta.get("request_id"))
    if not token_request_id or token_request_id != session_request_id:
        raise PracticeBatchTokenError("提交 request_id 与服务器下发批次不一致")

    expected_rec_rid = normalize_practice_request_id(payload.get("rec_rid"))
    for answer in answers:
        actual_rec_rid = normalize_practice_request_id(answer.get("request_id"))
        if actual_rec_rid != expected_rec_rid:
            raise PracticeBatchTokenError("推荐反馈 request_id 与服务器下发批次不一致")

    issued_at = int(payload.get("iat") or 0)
    started_at = parse_session_datetime(session_meta.get("started_at"))
    finished_at = parse_session_datetime(session_meta.get("finished_at"))
    if issued_at and started_at is not None:
        issued_dt = datetime.utcfromtimestamp(issued_at)
        if started_at < issued_dt - timedelta(seconds=PRACTICE_BATCH_CLOCK_SKEW_SEC):
            raise PracticeBatchTokenError("练习开始时间早于题目下发时间")
    if finished_at is not None and finished_at > utcnow() + timedelta(
        seconds=PRACTICE_BATCH_CLOCK_SKEW_SEC
    ):
        raise PracticeBatchTokenError("练习结束时间明显晚于服务器时间")

    return revisions, issued_order, payload

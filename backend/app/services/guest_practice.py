"""Account-free practice batches for the mini-program review flow.

Guest batches are signed, read-only contracts over immutable question
revisions. Nothing here creates a user or writes learning data.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.core.time_utils import unix_timestamp, utcnow
from app.features.question_type import CANONICAL_TYPES
from app.models.admin import QuestionVersion
from app.models.question import Question
from app.schemas.guest import GuestPracticeQuestion, GuestPracticeQuestionsResponse
from app.services.practice.response_content import (
    ensure_true_false_options,
    sanitize_question_content,
    sanitize_question_options,
)
from app.services.practice_service import (
    get_practice_subject_tree,
    resolve_practice_subject_scope,
    resolve_subject_id_to_code,
)
from app.services.question_revision_service import (
    latest_question_revision_scope_condition,
    load_revision_kp_names,
    load_revision_views,
)

GUEST_PRACTICE_MAX_QUESTIONS = 5
GUEST_PRACTICE_TOKEN_TTL_SEC = 24 * 60 * 60
_GUEST_TOKEN_VERSION = 1


class GuestPracticeError(ValueError):
    """Invalid guest batch token or guest practice request."""


class GuestSubjectUnavailableError(GuestPracticeError):
    """The requested subject has no guest-eligible questions."""


@dataclass(frozen=True, slots=True)
class GuestPracticeBatch:
    subject_id: int
    question_ids: tuple[int, ...]
    revisions: dict[int, int]
    issued_at: int
    expires_at: int


def _signing_key() -> bytes:
    return hmac.new(
        settings.APP_SECRET.encode("utf-8"),
        b"memograd:guest-practice-batch:v1",
        hashlib.sha256,
    ).digest()


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _now_seconds() -> int:
    return int(unix_timestamp(utcnow()))


def create_guest_batch_token(
    *,
    subject_id: int,
    revisions: dict[int, int],
    now: int | None = None,
) -> tuple[str, int]:
    issued_at = _now_seconds() if now is None else int(now)
    expires_at = issued_at + GUEST_PRACTICE_TOKEN_TTL_SEC
    payload = {
        "v": _GUEST_TOKEN_VERSION,
        "sid": int(subject_id),
        "qs": [[int(qid), int(vid)] for qid, vid in revisions.items()],
        "iat": issued_at,
        "exp": expires_at,
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(_signing_key(), body, hashlib.sha256).digest()
    return f"{_b64encode(body)}.{_b64encode(signature)}", expires_at


def decode_guest_batch_token(token: str, now: int | None = None) -> GuestPracticeBatch:
    try:
        body_part, signature_part = str(token or "").split(".", 1)
        body = _b64decode(body_part)
        signature = _b64decode(signature_part)
    except (ValueError, TypeError) as exc:
        raise GuestPracticeError("体验批次无效") from exc
    expected = hmac.new(_signing_key(), body, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise GuestPracticeError("体验批次签名无效")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GuestPracticeError("体验批次内容无效") from exc
    batch = _parse_payload(payload)
    current = _now_seconds() if now is None else int(now)
    if current >= batch.expires_at or current < batch.issued_at:
        raise GuestPracticeError("体验批次已过期，请重新出题")
    return batch


def _parse_payload(payload: object) -> GuestPracticeBatch:
    if not isinstance(payload, dict) or payload.get("v") != _GUEST_TOKEN_VERSION:
        raise GuestPracticeError("体验批次版本不支持")
    raw_pairs = payload.get("qs")
    if not isinstance(raw_pairs, list) or not 0 < len(raw_pairs) <= GUEST_PRACTICE_MAX_QUESTIONS:
        raise GuestPracticeError("体验批次题目数量无效")
    revisions: dict[int, int] = {}
    for pair in raw_pairs:
        if not isinstance(pair, list) or len(pair) != 2:
            raise GuestPracticeError("体验批次题目结构无效")
        try:
            question_id, revision_id = int(pair[0]), int(pair[1])
        except (TypeError, ValueError) as exc:
            raise GuestPracticeError("体验批次题目结构无效") from exc
        if question_id <= 0 or revision_id <= 0 or question_id in revisions:
            raise GuestPracticeError("体验批次题目重复或无效")
        revisions[question_id] = revision_id
    try:
        subject_id = int(payload["sid"])
        issued_at = int(payload["iat"])
        expires_at = int(payload["exp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GuestPracticeError("体验批次元数据无效") from exc
    if subject_id <= 0 or expires_at - issued_at != GUEST_PRACTICE_TOKEN_TTL_SEC:
        raise GuestPracticeError("体验批次元数据无效")
    return GuestPracticeBatch(
        subject_id=subject_id,
        question_ids=tuple(revisions),
        revisions=revisions,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def _eligible_conditions(subject_ids: list[int]) -> list:
    return [
        Question.is_active.is_(True),
        Question.review_status == "approved",
        Question.subject_id.in_(subject_ids),
        latest_question_revision_scope_condition(subject_ids, CANONICAL_TYPES),
    ]


def _collect_subject_ids(nodes: list[dict]) -> list[int]:
    ids: list[int] = []
    stack = list(nodes or [])
    while stack:
        node = stack.pop()
        subject_id = int(node.get("subject_id") or 0)
        if subject_id > 0:
            ids.append(subject_id)
        stack.extend(node.get("children") or [])
    return ids


async def _eligible_counts(db: AsyncSession, subject_ids: list[int]) -> dict[int, int]:
    if not subject_ids:
        return {}
    statement = (
        select(Question.subject_id, func.count(Question.id))
        .where(*_eligible_conditions(subject_ids))
        .group_by(Question.subject_id)
    )
    rows = await db.execute(statement)
    return {int(subject_id): int(count) for subject_id, count in rows.all()}


def _prune_tree(nodes: list[dict], counts: dict[int, int]) -> list[dict]:
    kept: list[dict] = []
    for node in nodes or []:
        own_count = counts.get(int(node.get("subject_id") or 0), 0)
        children = _prune_tree(node.get("children") or [], counts)
        if own_count == 0 and not children:
            continue
        kept.append({**node, "children": children, "trial_question_count": own_count})
    return kept


async def load_guest_subject_tree(db: AsyncSession) -> list[dict]:
    roots = await get_practice_subject_tree(db)
    counts = await _eligible_counts(db, _collect_subject_ids(roots))
    return _prune_tree(roots, counts)


async def load_guest_questions(
    db: AsyncSession, subject_id: int
) -> GuestPracticeQuestionsResponse:
    resolved = await resolve_subject_id_to_code(db, subject_id)
    if resolved is None:
        raise GuestSubjectUnavailableError("科目不存在或暂不可体验")
    _has_children, scope_ids = await resolve_practice_subject_scope(db, subject_id, True)
    if not scope_ids:
        raise GuestSubjectUnavailableError("科目不存在或暂不可体验")
    ranked_revision = aliased(QuestionVersion)
    issued_revision = aliased(QuestionVersion)
    latest_version = (
        select(func.max(ranked_revision.version))
        .where(ranked_revision.question_id == Question.id)
        .correlate(Question)
        .scalar_subquery()
    )
    statement = (
        select(Question.id, issued_revision.id)
        .join(issued_revision, issued_revision.question_id == Question.id)
        .where(*_eligible_conditions(scope_ids))
        .where(issued_revision.version == latest_version)
        .order_by(func.random())
        .limit(GUEST_PRACTICE_MAX_QUESTIONS)
    )
    revisions = dict((await db.execute(statement)).all())
    if not revisions:
        raise GuestSubjectUnavailableError("该科目暂无可体验题目")
    items = await _build_items(db, revisions)
    if len(items) != len(revisions):
        raise GuestSubjectUnavailableError("该科目暂无可体验题目")
    token, expires_at = create_guest_batch_token(
        subject_id=subject_id, revisions=revisions
    )
    return GuestPracticeQuestionsResponse(
        questions=items,
        total=len(items),
        subject_id=int(subject_id),
        subject_name=resolved[1],
        batch_token=token,
        expires_at=expires_at,
    )


async def _build_items(
    db: AsyncSession, revisions: dict[int, int]
) -> list[GuestPracticeQuestion]:
    views = await load_revision_views(db, revisions.values())
    knowledge_points = await load_revision_kp_names(db, revisions.values())
    items: list[GuestPracticeQuestion] = []
    for question_id, revision_id in revisions.items():
        view = views.get(revision_id)
        if view is None or int(view.question_id) != int(question_id):
            continue
        items.append(
            GuestPracticeQuestion(
                id=int(view.question_id),
                question_version_id=int(view.question_version_id),
                question_version=int(view.version),
                subject_id=int(view.subject_id or 0),
                subject_code=view.subject_ref.code if view.subject_ref else "",
                subject_name=view.subject_ref.name if view.subject_ref else "",
                question_type=str(view.question_type or ""),
                content=sanitize_question_content(view.content),
                options=sanitize_question_options(
                    ensure_true_false_options(view.question_type, view.options)
                ),
                knowledge_points=knowledge_points.get(int(view.question_version_id), []),
                difficulty=int(view.difficulty or 3),
                image_url=view.image_url,
            )
        )
    return items

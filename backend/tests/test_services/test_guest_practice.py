import base64
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.schemas.guest import GuestAnswerSubmit
from app.services import guest_evaluation, guest_practice
from app.services.guest_practice import (
    GUEST_PRACTICE_MAX_QUESTIONS,
    GUEST_PRACTICE_TOKEN_TTL_SEC,
    GuestPracticeBatch,
    GuestPracticeError,
    create_guest_batch_token,
    decode_guest_batch_token,
)


def _batch(question_ids=(11, 12), now=1_700_000_000):
    revisions = {qid: qid * 10 for qid in question_ids}
    token, expires_at = create_guest_batch_token(
        subject_id=7, revisions=revisions, now=now
    )
    return token, expires_at, revisions


def _view(question_id, question_type, answer, *, content=None, options=None, analysis=None):
    return SimpleNamespace(
        question_id=question_id,
        question_version_id=question_id * 10,
        question_type=question_type,
        answer=answer,
        content=content or {"text": "题干"},
        options=options,
        analysis=analysis,
    )


def test_token_roundtrip_binds_subject_and_revisions():
    token, expires_at, revisions = _batch()
    batch = decode_guest_batch_token(token, now=1_700_000_001)
    assert batch.subject_id == 7
    assert batch.revisions == revisions
    assert batch.question_ids == (11, 12)
    assert batch.expires_at == 1_700_000_000 + GUEST_PRACTICE_TOKEN_TTL_SEC == expires_at


def test_batch_epoch_uses_utc_for_naive_database_clock(monkeypatch):
    monkeypatch.setattr(guest_practice, "utcnow", lambda: datetime(2026, 11, 5))
    assert guest_practice._now_seconds() == 1793836800


def test_token_rejects_tampering_and_expiry():
    token, _expires_at, _revisions = _batch()
    body, signature = token.split(".")
    forged = base64.urlsafe_b64encode(
        json.dumps({"v": 1, "sid": 7, "qs": [[11, 999]], "iat": 0, "exp": 9_999_999_999})
        .encode()
    ).decode().rstrip("=")
    with pytest.raises(GuestPracticeError):
        decode_guest_batch_token(f"{forged}.{signature}", now=1_700_000_001)
    with pytest.raises(GuestPracticeError):
        decode_guest_batch_token(token, now=1_700_000_000 + GUEST_PRACTICE_TOKEN_TTL_SEC + 1)
    with pytest.raises(GuestPracticeError):
        decode_guest_batch_token(token, now=1_700_000_000 + GUEST_PRACTICE_TOKEN_TTL_SEC)


def test_token_rejects_too_many_questions():
    revisions = {qid: qid for qid in range(1, GUEST_PRACTICE_MAX_QUESTIONS + 2)}
    token, _ = create_guest_batch_token(subject_id=7, revisions=revisions)
    with pytest.raises(GuestPracticeError):
        decode_guest_batch_token(token)


@pytest.mark.asyncio
async def test_evaluate_grades_objective_and_flags_subjective(monkeypatch):
    batch = GuestPracticeBatch(
        subject_id=7,
        question_ids=(11, 12, 13),
        revisions={11: 110, 12: 120, 13: 130},
        issued_at=0,
        expires_at=9_999_999_999,
    )
    views = {
        110: _view(11, "single_choice", "A"),
        120: _view(12, "multiple_choice", "AC"),
        130: _view(13, "subjective", "参考要点", analysis="解析"),
    }
    monkeypatch.setattr(
        guest_evaluation, "load_revision_views", AsyncMock(return_value=views)
    )
    db = SimpleNamespace(add=AsyncMock(), commit=AsyncMock(), execute=AsyncMock())
    result = await guest_evaluation.evaluate_guest_answers(
        db,
        batch=batch,
        answers=[
            GuestAnswerSubmit(question_id=11, user_answer="a"),
            GuestAnswerSubmit(question_id=12, user_answer="CA"),
            GuestAnswerSubmit(question_id=13, user_answer="我的解答"),
        ],
    )
    assert result.objective_total == 2
    assert result.objective_correct == 2
    assert result.objective_incorrect == 0
    assert result.subjective_total == 1
    assert result.skipped_total == 0
    assert result.items[2].reference_only is True
    assert result.items[2].is_correct is None
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_counts_skipped_and_rejects_out_of_batch(monkeypatch):
    batch = GuestPracticeBatch(
        subject_id=7,
        question_ids=(11, 12),
        revisions={11: 110, 12: 120},
        issued_at=0,
        expires_at=9_999_999_999,
    )
    monkeypatch.setattr(
        guest_evaluation,
        "load_revision_views",
        AsyncMock(return_value={110: _view(11, "single_choice", "B"),
                                120: _view(12, "subjective", "答案")}),
    )
    db = SimpleNamespace()
    result = await guest_evaluation.evaluate_guest_answers(
        db, batch=batch, answers=[GuestAnswerSubmit(question_id=11, user_answer="A")]
    )
    assert result.objective_incorrect == 1
    assert result.skipped_total == 1
    with pytest.raises(GuestPracticeError):
        await guest_evaluation.evaluate_guest_answers(
            db,
            batch=batch,
            answers=[GuestAnswerSubmit(question_id=99, user_answer="A")],
        )


@pytest.mark.parametrize(("question_type", "answer", "submitted"), [
    ("true_false", "A", "正确"),
    ("fill_blank", "42", "42"),
    ("multi_blank_choice", "①:A;②:B", "①:A;②:B"),
    ("multi_blank_multiple_choice", "①:A,C;②:B", "①:C,A;②:B"),
])
def test_guest_grading_uses_supported_objective_rules(question_type, answer, submitted):
    view = _view(
        11, question_type, answer,
        content={"text": "① ②"},
        options={"①": {"A": "甲", "B": "乙", "C": "丙"}, "②": {"A": "丁", "B": "戊"}},
    )
    assert guest_evaluation._grade_one(view, submitted) == (True, False, False)

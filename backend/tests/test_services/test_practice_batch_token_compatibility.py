"""Compatibility baseline for signed practice batch tokens.

The tests exercise the real HMAC token format and submit-side validation, but
never touch a database or grade an answer.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.practice_service import (
    PRACTICE_BATCH_MAX_QUESTIONS,
    PracticeBatchTokenError,
    _decode_practice_batch_token,
    _practice_batch_signing_key,
    _urlsafe_b64encode,
    _validate_practice_batch_token,
    create_practice_batch_token,
)


def _question(question_id: int) -> SimpleNamespace:
    return SimpleNamespace(id=question_id)


def _session_meta(
    *,
    request_id: str,
    subject_id: int = 7,
    mode: str = "random",
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "subject_id": subject_id,
        "mode": mode,
        "request_id": request_id,
        "started_at": (started_at or now).isoformat(),
        "finished_at": (finished_at or now + timedelta(seconds=30)).isoformat(),
    }


def _sign_payload(payload: dict) -> str:
    body = _urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    import hashlib
    import hmac

    signature = _urlsafe_b64encode(
        hmac.new(
            _practice_batch_signing_key(), body.encode("ascii"), hashlib.sha256
        ).digest()
    )
    return f"{body}.{signature}"


def _base_payload(token_request_id: str, questions: list[list[int]], **overrides):
    now = int(time.time())
    payload = {
        "v": 2,
        "uid": 7,
        "rid": token_request_id,
        "rec_rid": None,
        "sid": 7,
        "mode": "random",
        "iat": now,
        "exp": now + 3600,
        "questions": questions,
    }
    payload.update(overrides)
    return payload


class TestCreatePracticeBatchToken:
    def test_empty_batch_returns_empty_contract(self):
        assert create_practice_batch_token(
            user_id=7,
            subject_id=7,
            mode="random",
            questions=[],
            revision_ids={},
        ) == (None, {}, None)

    def test_token_binds_questions_to_immutable_revisions_in_issued_order(self):
        token, revisions, request_id = create_practice_batch_token(
            user_id=7,
            subject_id=7,
            mode="random",
            questions=[_question(3), _question(1)],
            revision_ids={1: 101, 3: 303},
        )

        payload = _decode_practice_batch_token(token)
        assert revisions == {3: 303, 1: 101}
        assert payload["questions"] == [[3, 303], [1, 101]]
        assert payload["rid"] == request_id
        assert payload["uid"] == 7
        assert payload["sid"] == 7
        assert payload["mode"] == "random"

    def test_duplicate_question_fails_closed(self):
        with pytest.raises(PracticeBatchTokenError, match="重复题目"):
            create_practice_batch_token(
                user_id=7,
                subject_id=7,
                mode="random",
                questions=[_question(1), _question(1)],
                revision_ids={1: 101},
            )

    def test_missing_revision_fails_closed(self):
        with pytest.raises(RuntimeError, match="question_version"):
            create_practice_batch_token(
                user_id=7,
                subject_id=7,
                mode="random",
                questions=[_question(1)],
                revision_ids={},
            )

    def test_invalid_mode_is_rejected(self):
        with pytest.raises(PracticeBatchTokenError, match="练习模式无效"):
            create_practice_batch_token(
                user_id=7,
                subject_id=7,
                mode="invalid",
                questions=[_question(1)],
                revision_ids={1: 101},
            )

    def test_optional_contexts_are_signed_only_when_present(self):
        plain, _, _ = create_practice_batch_token(
            user_id=7,
            subject_id=7,
            mode="random",
            questions=[_question(1)],
            revision_ids={1: 101},
        )
        contextual, _, _ = create_practice_batch_token(
            user_id=7,
            subject_id=7,
            mode="random",
            questions=[_question(1)],
            revision_ids={1: 101},
            recommendation_request_id="recommendation-1",
            knowledge_context={"baseline": [1, 2]},
            entry_context={"source": "dashboard"},
            sequential_reservation_request_id="sequential-1",
            submission_request_id="submission-1",
        )

        plain_payload = _decode_practice_batch_token(plain)
        context_payload = _decode_practice_batch_token(contextual)
        assert "knowledge_context" not in plain_payload
        assert "entry_context" not in plain_payload
        assert "seq_reservation_request_id" not in plain_payload
        assert context_payload["rec_rid"] == "recommendation-1"
        assert context_payload["knowledge_context"] == {"baseline": [1, 2]}
        assert context_payload["entry_context"] == {"source": "dashboard"}
        assert context_payload["seq_reservation_request_id"] == "sequential-1"
        assert context_payload["rid"] == "submission-1"


class TestDecodePracticeBatchToken:
    def test_tampered_signature_is_rejected(self):
        token, _, _ = create_practice_batch_token(
            user_id=7,
            subject_id=7,
            mode="random",
            questions=[_question(1)],
            revision_ids={1: 101},
        )
        body, _signature = token.split(".", 1)

        with pytest.raises(PracticeBatchTokenError, match="签名无效"):
            _decode_practice_batch_token(f"{body}.tampered")

    def test_invalid_format_is_rejected(self):
        with pytest.raises(PracticeBatchTokenError, match="格式无效"):
            _decode_practice_batch_token("not-a-token")

    def test_wrong_version_is_rejected(self):
        token = _sign_payload(_base_payload("request-1", [[1, 101]], v=1))

        with pytest.raises(PracticeBatchTokenError, match="版本无效"):
            _decode_practice_batch_token(token)

    def test_expired_token_is_rejected(self):
        payload = _base_payload("request-1", [[1, 101]])
        payload["exp"] = int(time.time()) - 1
        token = _sign_payload(payload)

        with pytest.raises(PracticeBatchTokenError, match="已过期"):
            _decode_practice_batch_token(token)


class TestValidatePracticeBatchToken:
    def _validated(self, token, **overrides):
        meta = _session_meta(request_id="request-1")
        meta.update(overrides)
        return _validate_practice_batch_token(
            token,
            user_id=7,
            question_ids=[1, 2],
            session_meta=meta,
            answers=[],
        )

    def _token(self, questions=None, **overrides):
        return _sign_payload(
            _base_payload("request-1", questions or [[1, 101], [2, 102]], **overrides)
        )

    def test_valid_token_returns_revisions_order_and_payload(self):
        revisions, order, payload = self._validated(self._token())

        assert revisions == {1: 101, 2: 102}
        assert order == [1, 2]
        assert payload["rid"] == "request-1"

    def test_user_subject_mode_and_request_must_match(self):
        token = self._token()
        with pytest.raises(PracticeBatchTokenError, match="不属于当前用户"):
            _validate_practice_batch_token(
                token,
                user_id=8,
                question_ids=[1, 2],
                session_meta=_session_meta(request_id="request-1"),
                answers=[],
            )
        with pytest.raises(PracticeBatchTokenError, match="提交科目"):
            self._validated(token, subject_id=8)
        with pytest.raises(PracticeBatchTokenError, match="提交模式"):
            self._validated(token, mode="smart")
        with pytest.raises(PracticeBatchTokenError, match="提交 request_id"):
            self._validated(token, request_id="other")

    def test_submitted_question_set_must_match_issued_batch(self):
        token = self._token()
        meta = _session_meta(request_id="request-1")

        with pytest.raises(PracticeBatchTokenError, match="题目与服务器下发批次不一致"):
            _validate_practice_batch_token(
                token,
                user_id=7,
                question_ids=[1],
                session_meta=meta,
                answers=[],
            )

    def test_invalid_question_shapes_are_rejected(self):
        for questions in ([[1]], [[0, 101]], [[1, 0]]):
            token = self._token(questions=questions)
            with pytest.raises(PracticeBatchTokenError, match="题目列表无效"):
                self._validated(token)

    def test_batch_size_is_bounded(self):
        questions = [[index, 1000 + index] for index in range(1, 51)]
        token = self._token(questions=questions)
        meta = _session_meta(request_id="request-1")

        revisions, _, _ = _validate_practice_batch_token(
            token,
            user_id=7,
            question_ids=[item[0] for item in questions],
            session_meta=meta,
            answers=[],
        )
        assert len(revisions) == PRACTICE_BATCH_MAX_QUESTIONS

        questions.append([51, 1051])
        token = self._token(questions=questions)
        with pytest.raises(PracticeBatchTokenError, match="题目列表无效"):
            _validate_practice_batch_token(
                token,
                user_id=7,
                question_ids=[item[0] for item in questions],
                session_meta=meta,
                answers=[],
            )

    def test_answer_recommendation_request_must_match(self):
        token = self._token(rec_rid="recommendation-1")
        meta = _session_meta(request_id="request-1")

        with pytest.raises(PracticeBatchTokenError, match="推荐反馈 request_id"):
            _validate_practice_batch_token(
                token,
                user_id=7,
                question_ids=[1, 2],
                session_meta=meta,
                answers=[{"question_id": 1, "request_id": "other"}],
            )

    def test_started_at_cannot_predate_issuance_beyond_clock_skew(self):
        issued_at = int(time.time())
        token = self._token(iat=issued_at)
        too_early = datetime.fromtimestamp(issued_at, timezone.utc) - timedelta(
            seconds=301
        )
        meta = _session_meta(
            request_id="request-1",
            started_at=too_early,
            finished_at=too_early + timedelta(seconds=30),
        )

        with pytest.raises(PracticeBatchTokenError, match="开始时间早于"):
            _validate_practice_batch_token(
                token,
                user_id=7,
                question_ids=[1, 2],
                session_meta=meta,
                answers=[],
            )

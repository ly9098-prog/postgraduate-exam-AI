"""Real compatibility baseline for study hub plan token issue/validate cycle."""

from __future__ import annotations

import pytest

from app.services.study_hub_plan_token import (
    issue_plan_task_token,
    validate_plan_task_token,
)


def _issue(**overrides):
    defaults = dict(
        user_id=1, plan_date="2026-10-24", task_key="review", subject_id=2,
        mode="random", count=10,
    )
    defaults.update(overrides)
    return issue_plan_task_token(**defaults)


class TestIssuePlanTaskToken:
    def test_returns_non_empty_string(self):
        token = _issue()
        assert isinstance(token, str)
        assert "." in token

    def test_different_users_different_tokens(self):
        t1 = _issue(user_id=1)
        t2 = _issue(user_id=2)
        assert t1 != t2

    def test_same_params_same_token(self):
        t1 = _issue()
        t2 = _issue()
        assert t1 == t2


class TestValidatePlanTaskToken:
    def test_valid_token_matches_request(self):
        token = _issue(user_id=1, subject_id=2, mode="random", count=10)
        result = validate_plan_task_token(
            token, user_id=1, subject_id=2, mode="random", count=10,
        )
        assert result is not None
        assert result["source"] == "home_today_plan"
        assert result["plan_date"] == "2026-10-24"

    def test_none_token_returns_none(self):
        result = validate_plan_task_token(None, user_id=1, subject_id=2, mode="random", count=10)
        assert result is None

    def test_garbage_token_returns_none(self):
        result = validate_plan_task_token("garbage", user_id=1, subject_id=2, mode="random", count=10)
        assert result is None

    def test_wrong_user_returns_none(self):
        token = _issue(user_id=1)
        result = validate_plan_task_token(token, user_id=2, subject_id=2, mode="random", count=10)
        assert result is None

    def test_wrong_subject_returns_none(self):
        token = _issue(subject_id=2)
        result = validate_plan_task_token(token, user_id=1, subject_id=3, mode="random", count=10)
        assert result is None

    def test_wrong_mode_returns_none(self):
        token = _issue(mode="random")
        result = validate_plan_task_token(token, user_id=1, subject_id=2, mode="exam", count=10)
        assert result is None

    def test_wrong_count_returns_none(self):
        token = _issue(count=10)
        result = validate_plan_task_token(token, user_id=1, subject_id=2, mode="random", count=20)
        assert result is None

    def test_wrong_knowledge_point_returns_none(self):
        token = _issue(knowledge_point_id=5)
        result = validate_plan_task_token(
            token, user_id=1, subject_id=2, mode="random", count=10,
            knowledge_point_id=6,
        )
        assert result is None

    def test_wrong_descendants_flag_returns_none(self):
        token = _issue(include_descendants=False)
        result = validate_plan_task_token(
            token, user_id=1, subject_id=2, mode="random", count=10,
            include_descendants=True,
        )
        assert result is None

    def test_question_ids_digest_match(self):
        token = _issue(question_ids="1,2,3")
        result = validate_plan_task_token(
            token, user_id=1, subject_id=2, mode="random", count=10,
            question_ids="1,2,3",
        )
        assert result is not None

    def test_question_ids_digest_mismatch(self):
        token = _issue(question_ids="1,2,3")
        result = validate_plan_task_token(
            token, user_id=1, subject_id=2, mode="random", count=10,
            question_ids="4,5,6",
        )
        assert result is None

    def test_tampered_signature_returns_none(self):
        token = _issue()
        body, _sig = token.split(".", 1)
        tampered = f"{body}.AAAA"
        result = validate_plan_task_token(tampered, user_id=1, subject_id=2, mode="random", count=10)
        assert result is None

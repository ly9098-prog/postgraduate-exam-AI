"""Stage 11 刷题系统 — 单元测试（mock DB session）。"""
import asyncio
import hashlib
import hmac
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure all ORM models are registered so Subject's string relationships
# (practice_records, answer_behaviors, review_schedules, ...) resolve at
# mapper configuration time (see app/models/admin.py Subject).
from app.models.answer_behavior import AnswerBehavior  # noqa: F401
from app.models.import_batch_job import ImportBatchJob  # noqa: F401
from app.models.knowledge_edge import KnowledgeEdge  # noqa: F401
from app.models.knowledge_point import KnowledgePoint  # noqa: F401
from app.models.pomodoro import PomodoroSession  # noqa: F401
from app.models.practice_record import PracticeRecord  # noqa: F401
from app.models.question import Question
from app.models.recommendation_log import RecommendationLog  # noqa: F401
from app.models.recommendation_metrics_daily import (
    RecommendationMetricsDaily,  # noqa: F401
)
from app.models.review_scheduler import ReviewSchedule  # noqa: F401
from app.models.tag import Tag  # noqa: F401
from app.models.user_knowledge_state import UserKnowledgeState  # noqa: F401

# --- helpers ---

def _make_mock_db():
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    db.rollback = AsyncMock()
    db.flush = AsyncMock()
    # _china_date_expr awaits db.connection() to pick the date dialect.
    db.connection = AsyncMock()
    bind = MagicMock()
    bind.sync_connection.dialect.name = "sqlite"
    db.connection.return_value = bind
    # Leitner 取题 / sequential reset 走 await db.scalar(...)。
    db.scalar = AsyncMock(return_value=0)
    return db


def _make_execute_result(**methods):
    mock_result = MagicMock()
    for method, value in methods.items():
        if method == "scalars":
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = value
            mock_result.scalars.return_value = mock_scalars
        elif method == "all":
            mock_result.all.return_value = value
        elif method == "one":
            mock_result.one.return_value = value
        else:
            getattr(mock_result, method).return_value = value
    return mock_result


def _make_question(id=1, subject_id=1, question_type="single_choice",
                   answer="A", analysis="求导得 2x", knowledge_points=None,
                   is_active=True):
    q = MagicMock(spec=Question)
    q.id = id
    q.subject_id = subject_id
    q.question_type = question_type
    q.content = {"stem": "f(x)=x^2, f'(x)=?"}
    q.options = {"A": "2x", "B": "x", "C": "x^2", "D": "2"}
    q.answer = answer
    q.analysis = analysis
    q.knowledge_points = knowledge_points or ["导数"]
    q.difficulty = 2
    q.is_active = is_active
    return q


def _run(coro):
    return asyncio.run(coro)


def _make_batch_token(user_id=1, pairs=((1, 900001),), subject_id=1, mode="random"):
    """Sign a practice batch token with the production key/format."""
    import json
    import time
    import uuid

    import app.services.practice_service as ps

    rid = f"practice_{uuid.uuid4().hex}"
    payload = {
        "v": ps._PRACTICE_BATCH_TOKEN_VERSION,
        "uid": user_id,
        "rid": rid,
        "rec_rid": None,
        "sid": subject_id,
        "mode": mode,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "questions": [list(pair) for pair in pairs],
    }
    body = ps._urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )
    signature = ps._urlsafe_b64encode(
        hmac.new(
            ps._practice_batch_signing_key(), body.encode("ascii"), hashlib.sha256
        ).digest()
    )
    return body + "." + signature, rid


def _make_batch_db(views, *, record_id=77):
    """Mock db prepared for batch_submit_answers runs (no real revision rows)."""
    db = _make_mock_db()
    db.get = AsyncMock(return_value=None)

    async def _execute(*_args, **_kwargs):
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        result.scalars.return_value.first.return_value = None
        result.scalar.return_value = None
        result.scalar_one.return_value = None
        result.scalar_one_or_none.return_value = None
        result.all.return_value = []
        result.one.return_value = (0, 0)
        return result

    db.execute = AsyncMock(side_effect=_execute)
    db.scalar = AsyncMock(return_value=None)

    counter = [0]

    def _add(obj):
        if type(obj).__name__ == "PracticeRecord":
            counter[0] += 1
            obj.id = record_id + counter[0]

    db.add = _add

    views_by_revision = {}
    for v in views:
        v.question_id = v.id
        v.question_version_id = 900000 + v.id
        v.subject_id = v.subject_id or 1
        views_by_revision[v.question_version_id] = v
    return db, views_by_revision


def _submit_batch(db, views_by_revision, answers, *, user_id=1, mode="random"):
    """Run batch_submit_answers against a signed token; returns result."""
    from datetime import datetime, timedelta, timezone

    from app.services import practice_service

    pairs = [(v.id, v.question_version_id) for v in views_by_revision.values()]
    token, rid = _make_batch_token(user_id=user_id, pairs=pairs, mode=mode)
    start = datetime.now(timezone.utc)
    finished = start + timedelta(seconds=30)

    with patch(
        "app.services.question_revision_service.load_revision_views",
        new_callable=AsyncMock,
        return_value=views_by_revision,
    ), patch(
        "app.services.question_revision_service.load_revision_kp_names",
        new_callable=AsyncMock,
        return_value={},
    ):
        return _run(practice_service.batch_submit_answers(
            db,
            user_id=user_id,
            answers=answers,
            session_meta={
                "subject_id": 1,
                "mode": mode,
                "request_id": rid,
                "started_at": start.isoformat(),
                "finished_at": finished.isoformat(),
                "duration_sec": 30,
                "answered_count": len(answers),
            },
            skipped_question_ids=[],
            batch_token=token,
        ))


# --- get_practice_questions ---

class TestGetPracticeQuestions:

    @staticmethod
    def _side_effect_once(questions):
        """First db.execute returns questions, all subsequent return empty."""
        first = _make_execute_result(scalars=questions)
        empty = _make_execute_result(scalars=[])
        called = [False]
        def _side_effect(*a, **kw):
            if not called[0]:
                called[0] = True
                return first
            return empty
        return _side_effect

    @staticmethod
    def _make_db_for_list_query(questions):
        """Mock db for get_practice_questions 单测。

        db.execute 首次返回 questions、后续为空；db.scalar 首次（Leitner
        count / sequential reset）返回 0，其后返回 None——顺序模式的
        reservation 循环以 scalar 的候选探测结果退出，恒非 None 的 mock 会让
        该防御性重试变成无限循环。
        """
        db = _make_mock_db()
        db.execute.side_effect = TestGetPracticeQuestions._side_effect_once(questions)
        scalar_results = [0, None]

        async def _scalar(*_args, **_kwargs):
            return scalar_results.pop(0) if len(scalar_results) > 1 else None

        db.scalar = AsyncMock(side_effect=_scalar)
        return db

    def test_random_mode(self):
        from app.services.practice_service import get_practice_questions
        db = self._make_db_for_list_query([_make_question(1), _make_question(2)])
        with patch("app.services.practice_service.resolve_subject_ids", new_callable=AsyncMock, return_value=[1]):
            result = _run(get_practice_questions(db, user_id=1, subject_code="math2", count=5, mode="random"))
        assert len(result) == 2
        assert result[0].id == 1

    def test_sequential_mode(self):
        """顺序模式委托给 sequential_service（db mock 无法模拟其原子预留语义）。"""
        from app.services.practice_service import get_practice_questions
        q1, q2 = _make_question(1), _make_question(2)
        db = _make_mock_db()
        with patch(
            "app.services.practice_service.get_sequential_practice_questions",
            new_callable=AsyncMock,
            return_value=([q1, q2], {"total_questions": 2, "completed_questions": 0}),
        ), patch(
            "app.services.practice_service.resolve_subject_ids",
            new_callable=AsyncMock,
            return_value=[1],
        ):
            result = _run(get_practice_questions(db, user_id=1, subject_code="math2", count=5, mode="sequential"))
        assert len(result) == 2

    def test_filter_by_knowledge_point(self):
        from app.services.practice_service import get_practice_questions
        db = self._make_db_for_list_query([_make_question(1, knowledge_points=["导数", "极限"])])
        with patch("app.services.practice_service.resolve_subject_ids", new_callable=AsyncMock, return_value=[1]):
            result = _run(get_practice_questions(
                db, user_id=1, subject_code="math2", count=5, knowledge_points=["导数"]
            ))
        assert len(result) == 1

    def test_exclude_answered(self):
        from app.services.practice_service import get_practice_questions
        db = self._make_db_for_list_query([_make_question(2)])
        with patch("app.services.practice_service.resolve_subject_ids", new_callable=AsyncMock, return_value=[1]):
            result = _run(get_practice_questions(
                db, user_id=1, subject_code="math2", count=5, exclude_answered=True
            ))
        assert len(result) == 1

    def test_empty_result(self):
        from app.services.practice_service import get_practice_questions
        db = self._make_db_for_list_query([])
        with patch("app.services.practice_service.resolve_subject_ids", new_callable=AsyncMock, return_value=[1]):
            result = _run(get_practice_questions(db, user_id=1, subject_code="math2", count=5))
        assert result == []


# --- multi blank answer helpers ---

class TestMultiBlankAnswerHelpers:
    def test_normalize_blank_choice_answer(self):
        from app.features.multi_blank_choice import parse_multi_blank_answer

        parsed, _ = parse_multi_blank_answer("①:A;②:C")
        assert parsed == {"①": "A", "②": "C"}
        parsed, _ = parse_multi_blank_answer("①：a；②：c")
        assert parsed == {"①": "A", "②": "C"}

    def test_multi_blank_answer_order_insensitive(self):
        from app.utils.answer_normalizer import is_answer_correct

        assert is_answer_correct("②:C;①:A", "①:A;②:C", "multi_blank_choice") is True

    def test_multi_blank_answer_rejects_partial_or_wrong(self):
        from app.utils.answer_normalizer import is_answer_correct

        assert is_answer_correct("①:A", "①:A;②:C", "multi_blank_choice") is False
        assert is_answer_correct("①:A;②:B", "①:A;②:C", "multi_blank_choice") is False


# --- submit_answer ---

class TestSubmitAnswer:
    """提交链路测试。

    单题 submit_answer 已被签名批次的 batch_submit_answers 取代（提交绑定
    不可变 revision），评分/规范化语义通过批次路径验证。
    """

    def test_correct_answer(self):
        db, views = _make_batch_db([_make_question(1, answer="A")])

        with patch(
            "app.services.wrong_question_service.record_wrong", new_callable=AsyncMock
        ):
            result = _submit_batch(
                db, views, [{"question_id": 1, "user_answer": "A", "used_time": 10}]
            )
        assert result["total_correct"] == 1
        assert result["results"][0]["correct_answer"] == "A"
        assert result["results"][0]["is_wrong_added"] is False

    def test_wrong_answer(self):
        db, views = _make_batch_db([_make_question(1, answer="A")])

        wq = MagicMock()
        wq.id = 55
        with patch(
            "app.services.wrong_question_service.record_wrong",
            new_callable=AsyncMock,
            return_value=wq,
        ), patch(
            "app.services.error_diagnosis_service.record_error_event",
            new_callable=AsyncMock,
            return_value=MagicMock(
                id=1,
                wrong_question_id=55,
                question_id=1,
                question_version_id=900001,
                practice_record_id=78,
                user_confirmed_at=None,
                user_primary_type=None,
                ai_status=None,
                ai_primary_type=None,
                ai_secondary_types=None,
            ),
        ):
            result = _submit_batch(
                db, views, [{"question_id": 1, "user_answer": "B", "used_time": 10}]
            )
        assert result["total_wrong"] == 1
        assert result["results"][0]["correct_answer"] == "A"
        assert result["results"][0]["is_wrong_added"] is True
        assert result["results"][0]["wrong_question_id"] == 55

    def test_case_insensitive(self):
        db, views = _make_batch_db([_make_question(1, answer="A")])

        with patch(
            "app.services.wrong_question_service.record_wrong", new_callable=AsyncMock
        ):
            result = _submit_batch(
                db, views, [{"question_id": 1, "user_answer": "a", "used_time": 10}]
            )
        assert result["total_correct"] == 1

    def test_whitespace_trimmed(self):
        db, views = _make_batch_db([_make_question(1, answer="A")])

        with patch(
            "app.services.wrong_question_service.record_wrong", new_callable=AsyncMock
        ):
            result = _submit_batch(
                db, views, [{"question_id": 1, "user_answer": "  A  ", "used_time": 10}]
            )
        assert result["total_correct"] == 1

    def test_used_time_optional(self):
        db, views = _make_batch_db([_make_question(1, answer="A")])

        with patch(
            "app.services.wrong_question_service.record_wrong", new_callable=AsyncMock
        ):
            result = _submit_batch(db, views, [{"question_id": 1, "user_answer": "A"}])
        assert result["total_correct"] == 1

    def test_creates_practice_record(self):
        db, views = _make_batch_db([_make_question(1, answer="A")])

        with patch(
            "app.services.wrong_question_service.record_wrong", new_callable=AsyncMock
        ):
            result = _submit_batch(
                db, views, [{"question_id": 1, "user_answer": "A", "used_time": 10}]
            )
        assert "record_id" in result["results"][0]

    def test_multi_blank_choice_order_insensitive_submit(self):
        db, views = _make_batch_db(
            [_make_question(1, question_type="multi_blank_choice", answer="①:A;②:C")]
        )

        with patch(
            "app.services.wrong_question_service.record_wrong", new_callable=AsyncMock
        ):
            result = _submit_batch(
                db,
                views,
                [{"question_id": 1, "user_answer": "②:C;①:A", "used_time": 10}],
            )
        assert result["total_correct"] == 1
        assert result["results"][0]["is_wrong_added"] is False

    def test_multi_blank_choice_partial_submit_is_wrong(self):
        db, views = _make_batch_db(
            [_make_question(1, question_type="multi_blank_choice", answer="①:A;②:C")]
        )

        wq = MagicMock()
        wq.id = 55
        with patch(
            "app.services.wrong_question_service.record_wrong",
            new_callable=AsyncMock,
            return_value=wq,
        ), patch(
            "app.services.error_diagnosis_service.record_error_event",
            new_callable=AsyncMock,
            return_value=MagicMock(
                id=1,
                wrong_question_id=55,
                question_id=1,
                question_version_id=900001,
                practice_record_id=78,
                user_confirmed_at=None,
                user_primary_type=None,
                ai_status=None,
                ai_primary_type=None,
                ai_secondary_types=None,
            ),
        ):
            result = _submit_batch(
                db, views, [{"question_id": 1, "user_answer": "①:A", "used_time": 10}]
            )
        assert result["total_wrong"] == 1
        assert result["results"][0]["is_wrong_added"] is True


# --- batch_submit_answers ---

class TestBatchSubmit:
    def test_batch_submit(self):
        db, views = _make_batch_db(
            [_make_question(1, answer="A"), _make_question(2, answer="B")]
        )

        wq = MagicMock()
        wq.id = 55
        with patch(
            "app.services.wrong_question_service.record_wrong",
            new_callable=AsyncMock,
            return_value=wq,
        ), patch(
            "app.services.error_diagnosis_service.record_error_event",
            new_callable=AsyncMock,
            return_value=MagicMock(
                id=1,
                wrong_question_id=55,
                question_id=2,
                question_version_id=900002,
                practice_record_id=79,
                user_confirmed_at=None,
                user_primary_type=None,
                ai_status=None,
                ai_primary_type=None,
                ai_secondary_types=None,
            ),
        ):
            result = _submit_batch(db, views, [
                {"question_id": 1, "user_answer": "A", "used_time": 5},
                {"question_id": 2, "user_answer": "C", "used_time": 5},
            ])
        assert result["total_correct"] == 1
        assert result["total_wrong"] == 1
        assert len(result["results"]) == 2

    def test_batch_missing_question(self):
        """token 引用的 revision 缺失 → 拒绝提交（批次完整性校验）。"""
        from datetime import datetime, timedelta, timezone

        from app.services import practice_service
        from app.services.practice_service import PracticeBatchTokenError

        db, views = _make_batch_db([_make_question(1, answer="A")])

        token, _rid = _make_batch_token(user_id=1, pairs=((1, 900001), (999, 900999)))
        start = datetime.now(timezone.utc)
        with patch(
            "app.services.question_revision_service.load_revision_views",
            new_callable=AsyncMock,
            return_value={900001: views[900001]},
        ):
            with pytest.raises((PracticeBatchTokenError, ValueError)):
                _run(practice_service.batch_submit_answers(
                    db,
                    user_id=1,
                    answers=[
                        {"question_id": 1, "user_answer": "A"},
                        {"question_id": 999, "user_answer": "B"},
                    ],
                    session_meta={
                        "subject_id": 1,
                        "mode": "random",
                        "request_id": "practice_missing_probe",
                        "started_at": start.isoformat(),
                        "finished_at": (start + timedelta(seconds=5)).isoformat(),
                        "answered_count": 2,
                    },
                    skipped_question_ids=[],
                    batch_token=token,
                ))


# --- get_practice_stats ---

class TestPracticeStats:
    def test_stats_with_data(self):
        from app.services.practice_service import get_practice_stats

        db = _make_mock_db()
        db.execute.side_effect = [
            # Total count + correct (base query)
            _make_execute_result(one=(10, 7)),
            # By subject
            _make_execute_result(all=[]),
            # Daily stats
            _make_execute_result(all=[]),
            # Streak query
            _make_execute_result(all=[]),
        ]

        result = _run(get_practice_stats(db, user_id=1, days=7))
        assert result["total_answered"] == 10
        assert result["total_correct"] == 7
        assert result["accuracy"] == 0.7
        assert result["current_streak"] == 0

    def test_stats_empty(self):
        from app.services.practice_service import get_practice_stats

        db = _make_mock_db()
        db.execute.side_effect = [
            _make_execute_result(one=(0, 0)),
            _make_execute_result(all=[]),
            _make_execute_result(all=[]),
            _make_execute_result(all=[]),
        ]

        result = _run(get_practice_stats(db, user_id=1))
        assert result["total_answered"] == 0
        assert result["total_correct"] == 0
        assert result["accuracy"] == 0.0

    def test_stats_by_subject(self):
        from app.services.practice_service import get_practice_stats

        db = _make_mock_db()
        db.execute.side_effect = [
            _make_execute_result(one=(5, 4)),
            _make_execute_result(all=[(1, "math2", "数学二", 5, 4)]),
            _make_execute_result(all=[]),
            _make_execute_result(all=[]),
        ]

        result = _run(get_practice_stats(db, user_id=1))
        by_code = {s["subject_code"]: s for s in result["by_subject"]}
        assert by_code["math2"]["answered"] == 5
        assert by_code["math2"]["accuracy"] == 0.8


# --- streak calculation ---

class TestStreak:
    def test_no_records(self):
        from app.services.practice_service import _calc_streak

        db = _make_mock_db()
        db.execute.return_value = _make_execute_result(all=[])

        streak = _run(_calc_streak(db, user_id=1))
        assert streak == 0

    def test_consecutive_days(self):
        from app.services.practice_service import _calc_streak

        db = _make_mock_db()
        today = date.today()
        dates = [(today,), (today - timedelta(days=1),)]
        db.execute.return_value = _make_execute_result(all=dates)

        streak = _run(_calc_streak(db, user_id=1))
        assert streak == 2

    def test_gap_resets_streak(self):
        from app.services.practice_service import _calc_streak

        db = _make_mock_db()
        today = date.today()
        dates = [(today - timedelta(days=2),)]
        db.execute.return_value = _make_execute_result(all=dates)

        streak = _run(_calc_streak(db, user_id=1))
        assert streak == 0


# ── 父级科目聚合刷题测试 ─────────────────────────────────


class TestRoundRobinMerge:
    """纯函数单元测试：轮询合并逻辑（_round_robin_merge）。"""

    @staticmethod
    def _make_item(id_val):
        obj = MagicMock()
        obj.id = id_val
        return obj

    def test_balanced_distribution(self):
        """4 个非空桶，count=5，各桶题数差值 ≤ 1。"""
        from app.services.practice_service import _round_robin_merge

        buckets = [
            [self._make_item(1), self._make_item(2), self._make_item(3), self._make_item(4), self._make_item(5)],
            [self._make_item(6), self._make_item(7), self._make_item(8), self._make_item(9), self._make_item(10)],
            [self._make_item(11), self._make_item(12), self._make_item(13), self._make_item(14), self._make_item(15)],
            [self._make_item(16), self._make_item(17), self._make_item(18), self._make_item(19), self._make_item(20)],
        ]

        result = _round_robin_merge(buckets, count=5)
        assert len(result) == 5

        # 各桶在结果中的题数
        from collections import Counter
        bucket_counts = Counter()
        for i, bucket in enumerate(buckets):
            ids = {item.id for item in bucket}
            bucket_counts[i] = sum(1 for item in result if item.id in ids)

        counts = list(bucket_counts.values())
        # 5 题分 4 桶，合理分布为 2/1/1/1
        assert sum(counts) == 5
        assert max(counts) - min(counts) <= 1, f"桶间差值超过 1: {counts}"

    def test_empty_buckets_skipped(self):
        """空桶自动跳过。"""
        from app.services.practice_service import _round_robin_merge

        buckets = [
            [self._make_item(1), self._make_item(2), self._make_item(3)],
            [],
            [self._make_item(4), self._make_item(5), self._make_item(6)],
        ]

        result = _round_robin_merge(buckets, count=4)
        assert len(result) == 4

    def test_underfilled_bucket(self):
        """某个桶不足时，仍有其他桶补齐。"""
        from app.services.practice_service import _round_robin_merge

        buckets = [
            [self._make_item(1)],  # 只有 1 题
            [self._make_item(2), self._make_item(3), self._make_item(4), self._make_item(5)],
            [self._make_item(6), self._make_item(7), self._make_item(8), self._make_item(9)],
        ]

        result = _round_robin_merge(buckets, count=5)
        assert len(result) == 5
        # 三个桶都应出现
        bucket_ids = [{item.id for item in b} for b in buckets]
        for ids in bucket_ids:
            assert any(item.id in ids for item in result), f"桶 {ids} 在结果中缺失"

    def test_no_duplicates(self):
        """结果中无重复项。"""
        from app.services.practice_service import _round_robin_merge

        buckets = [
            [self._make_item(1), self._make_item(2), self._make_item(3)],
            [self._make_item(4), self._make_item(5), self._make_item(6)],
        ]

        result = _round_robin_merge(buckets, count=10)
        ids = [item.id for item in result]
        assert len(ids) == len(set(ids)), "结果中有重复"

    def test_all_buckets_empty(self):
        """所有桶为空时返回空列表。"""
        from app.services.practice_service import _round_robin_merge

        assert _round_robin_merge([], count=5) == []
        assert _round_robin_merge([[], []], count=5) == []


class TestRoundRobinMergeWithMetadata:
    """轮询合并带 metadata（smart 模式用）。"""

    @staticmethod
    def _make_item(id_val):
        obj = MagicMock()
        obj.id = id_val
        return obj

    def test_metadata_preserved(self):
        """验证 metadata 与题目 ID 一一对应且不丢失。"""
        from app.services.practice_service import _round_robin_merge_with_metadata

        buckets = [
            [(self._make_item(1), {"reason": "a1", "score": 0.9}),
             (self._make_item(2), {"reason": "a2", "score": 0.8})],
            [(self._make_item(3), {"reason": "b1", "score": 0.7}),
             (self._make_item(4), {"reason": "b2", "score": 0.6})],
        ]

        questions, metadata = _round_robin_merge_with_metadata(buckets, count=4)
        assert len(questions) == 4
        assert len(metadata) == 4
        assert metadata[1]["reason"] == "a1"
        assert metadata[1]["score"] == 0.9
        assert metadata[3]["reason"] == "b1"

    def test_partial_merge_keeps_metadata(self):
        """部分合并时 metadata 仍正确关联。"""
        from app.services.practice_service import _round_robin_merge_with_metadata

        buckets = [
            [(self._make_item(1), {"reason": "a"}),
             (self._make_item(2), {"reason": "b"})],
            [(self._make_item(3), {"reason": "c"})],
        ]

        questions, metadata = _round_robin_merge_with_metadata(buckets, count=2)
        assert len(questions) == 2
        assert len(metadata) == 2


# ── 科目作用域解析 ────────────────────────────────────


class TestResolvePracticeSubjectScope:
    """resolve_practice_subject_scope 单元测试。

    科目记录使用 canonical 408 code：学生端范围解析
    （``is_study_subject_enabled`` / ``select_study_subject_records``）只放行
    canonical 408 目录与显式额外科目，通用占位 code 会被过滤掉。
    """

    def _make_subject(self, id, code, name, parent_id=None, level=1,
                      sort_order=0, is_active=True):
        s = MagicMock()
        s.id = id
        s.code = code
        s.name = name
        s.parent_id = parent_id
        s.level = level
        s.sort_order = sort_order
        s.is_active = is_active
        return s

    def _setup_db(self, scope_func, db_subjects):
        """创建 mock DB，模拟 resolve_practice_subject_scope 所需的调用。

        resolve_practice_subject_scope 会做：
        1. db.get(Subject, subject_id) → 返回目标科目
        2. db.execute(select Subject).scalars().all() → 返回全部科目
        """
        async def fake_get(model, subject_id):
            for s in db_subjects:
                if s.id == subject_id:
                    return s
            return None

        db = MagicMock()
        db.get = AsyncMock(side_effect=fake_get)

        # 模拟 db.execute → scalars → all (resolved_to = AsyncMock)
        all_result = MagicMock()
        scalars_result = MagicMock()
        scalars_result.all.return_value = db_subjects
        all_result.scalars.return_value = scalars_result
        all_result.all.return_value = []

        async def fake_execute(stmt, *a, **kw):
            return all_result

        db.execute = AsyncMock(side_effect=fake_execute)
        return db

    def test_parent_with_children_include_true(self):
        """父级 + include_children=true 返回自身及所有后代。"""
        from app.services.practice_service import resolve_practice_subject_scope

        subjects = [
            self._make_subject(1, "exam408", "计算机", parent_id=None, level=1),
            self._make_subject(2, "data_structure", "数据结构", parent_id=1, level=2, sort_order=10),
            self._make_subject(3, "computer_organization", "组成原理", parent_id=1, level=2, sort_order=20),
            self._make_subject(4, "operating_system", "操作系统", parent_id=1, level=2, sort_order=30),
            self._make_subject(5, "computer_network", "计算机网络", parent_id=1, level=2, sort_order=40),
        ]
        db = self._setup_db(resolve_practice_subject_scope, subjects)

        has_children, ids = _run(resolve_practice_subject_scope(db, 1, include_children=True))
        assert has_children is True
        assert set(ids) == {1, 2, 3, 4, 5}

    def test_parent_with_children_include_false(self):
        """父级 + include_children=false 只返回自身。"""
        from app.services.practice_service import resolve_practice_subject_scope

        subjects = [
            self._make_subject(1, "exam408", "计算机", parent_id=None, level=1),
            self._make_subject(2, "data_structure", "数据结构", parent_id=1, level=2),
        ]
        db = self._setup_db(resolve_practice_subject_scope, subjects)

        has_children, ids = _run(resolve_practice_subject_scope(db, 1, include_children=False))
        assert has_children is True
        assert ids == [1]

    def test_leaf_subject_any_mode(self):
        """叶子科目无论 include_children 如何都只返回自身。"""
        from app.services.practice_service import resolve_practice_subject_scope

        subjects = [
            self._make_subject(1, "exam408", "计算机", parent_id=None, level=1),
            self._make_subject(2, "data_structure", "数据结构", parent_id=1, level=2),
        ]
        db = self._setup_db(resolve_practice_subject_scope, subjects)

        # 叶子 + include_children=false
        has_children, ids = _run(resolve_practice_subject_scope(db, 2, include_children=False))
        assert has_children is False
        assert ids == [2]

        # 叶子 + include_children=true
        has_children, ids = _run(resolve_practice_subject_scope(db, 2, include_children=True))
        assert has_children is False
        assert ids == [2]

    def test_disabled_children_excluded(self):
        """停用的后代不进入聚合范围。"""
        from app.services.practice_service import resolve_practice_subject_scope

        subjects = [
            self._make_subject(1, "exam408", "计算机", parent_id=None, level=1),
            self._make_subject(2, "data_structure", "数据结构", parent_id=1, level=2, sort_order=10, is_active=True),
            self._make_subject(3, "computer_organization", "组成原理", parent_id=1, level=2, sort_order=20, is_active=False),
        ]
        db = self._setup_db(resolve_practice_subject_scope, subjects)

        has_children, ids = _run(resolve_practice_subject_scope(db, 1, include_children=True))
        assert has_children is True  # data_structure 是启用的
        assert 3 not in ids  # computer_organization 停用，不包含

    def test_subject_not_found(self):
        """不存在的科目返回空。"""
        from app.services.practice_service import resolve_practice_subject_scope

        db = MagicMock()
        db.get = AsyncMock(return_value=None)

        has_children, ids = _run(resolve_practice_subject_scope(db, 999, include_children=True))
        assert has_children is False
        assert ids == []


# ── 随机模式聚合刷题 ──────────────────────────────────


class TestGetAggregatedRandomQuestions:
    """随机模式聚合刷题服务层测试。"""

    def test_single_subject_returns_directly(self):
        """scope 为单个 subject_id 时直接返回结果。"""
        from app.services.practice_service import get_aggregated_random_questions

        db = MagicMock()
        q = MagicMock(spec=Question)
        q.id = 1
        q.subject_id = 10

        with patch(
            "app.services.practice_service._get_questions_with_leitner",
            new_callable=AsyncMock,
            return_value=[q],
        ):
            result = _run(get_aggregated_random_questions(
                db, user_id=1, subject_code="cs",
                subject_ids=[10], count=5,
            ))
            assert len(result) == 1

    def test_multiple_subjects_round_robin_distribution(self):
        """多个子科目时轮询分配。"""
        from app.services.practice_service import get_aggregated_random_questions

        db = MagicMock()
        # 模拟 3 个科目的 pool：每科 6 题
        all_questions = []
        for subject_id, start in [(10, 1), (20, 100), (30, 200)]:
            for i in range(6):
                q = MagicMock(spec=Question)
                q.id = start + i
                q.subject_id = subject_id
                all_questions.append(q)

        # _get_questions_with_leitner 对每个 subject_id 各自返回相应题目
        async def _fake_get_leitner(db_inner, user_id, base_conditions, mode, count, **kw):
            # base_conditions 中包含 subject_id == sid 的条件
            for cond in base_conditions:
                if hasattr(cond, 'right') and hasattr(cond.right, 'value'):
                    target_sid = cond.right.value
                    return [q for q in all_questions if q.subject_id == target_sid][:count]
            return []

        with patch(
            "app.services.practice_service._get_questions_with_leitner",
            new_callable=AsyncMock,
            side_effect=_fake_get_leitner,
        ):
            result = _run(get_aggregated_random_questions(
                db, user_id=1, subject_code="cs",
                subject_ids=[10, 20, 30], count=5,
            ))
            assert len(result) == 5
            # 验证结果包含多个科目的题
            subj_in_result = {q.subject_id for q in result}
            assert len(subj_in_result) >= 2, "应覆盖多个子科目"


class TestGetAggregatedSmartQuestions:
    """智能模式聚合刷题服务层测试。"""

    def _mock_subject(self, id, code):
        s = MagicMock()
        s.id = id
        s.code = code
        return s

    def test_single_subject_passthrough(self):
        """单个 subject_id 时直接返回。"""
        from app.services.practice_service import get_aggregated_smart_questions

        db = MagicMock()
        q = MagicMock(spec=Question)
        q.id = 1
        q.subject_id = 10

        # mock Subject query for code resolution
        subj_result = MagicMock()
        subj_result.scalars.return_value.all.return_value = [self._mock_subject(10, "ds")]
        db.execute = AsyncMock(return_value=subj_result)

        with patch(
            "app.services.practice_service.get_smart_practice_questions",
            new_callable=AsyncMock,
            return_value=([q], {1: {"reason": "test"}}),
        ):
            questions, metadata = _run(get_aggregated_smart_questions(
                db, user_id=1, subject_code="cs",
                subject_ids=[10], count=5,
            ))
            assert len(questions) == 1
            assert metadata[1]["reason"] == "test"

    def test_multiple_subjects_merge_metadata(self):
        """多科目时 metadata 随轮询合并保留。"""
        from app.services.practice_service import get_aggregated_smart_questions

        db = MagicMock()
        # mock Subject query
        subj_result = MagicMock()
        subj_result.scalars.return_value.all.return_value = [
            self._mock_subject(10, "ds"),
            self._mock_subject(20, "os"),
        ]
        db.execute = AsyncMock(return_value=subj_result)

        # 每个科目各 3 题
        all_questions = {10: [], 20: []}
        all_metadata = {}
        for sid, code, id_start in [(10, "ds", 1), (20, "os", 100)]:
            for i in range(3):
                q = MagicMock(spec=Question)
                q.id = id_start + i
                q.subject_id = sid
                all_questions[sid].append(q)
                all_metadata[q.id] = {"reason": f"subj{sid}_q{q.id}"}

        # get_smart_practice_questions 对每个 code 返回对应题目
        async def _fake_smart(**kw):
            subject = kw.get("subject_code", "")
            if subject == "ds":
                return all_questions[10][:], {q.id: all_metadata[q.id] for q in all_questions[10]}
            elif subject == "os":
                return all_questions[20][:], {q.id: all_metadata[q.id] for q in all_questions[20]}
            return [], {}

        with patch(
            "app.services.practice_service.get_smart_practice_questions",
            new_callable=AsyncMock,
            side_effect=_fake_smart,
        ):
            merged_qs, merged_meta = _run(get_aggregated_smart_questions(
                db, user_id=1, subject_code="cs",
                subject_ids=[10, 20], count=4,
            ))
            assert len(merged_qs) <= 4
            assert len(merged_meta) == len(merged_qs)
            # metadata 内容保持正确
            for q in merged_qs:
                assert q.id in merged_meta
                assert merged_meta[q.id]["reason"] == f"subj{q.subject_id}_q{q.id}"


# ── include_descendants 参数 ──────────────────────────


class TestResolveSubjectIdsIncludeDescendants:
    """resolve_subject_ids 的 include_descendants 参数测试。"""

    def _make_subject(self, id, code, parent_id=None, level=1,
                      sort_order=0, is_active=True):
        s = MagicMock()
        s.id = id
        s.code = code
        s.parent_id = parent_id
        s.level = level
        s.sort_order = sort_order
        s.is_active = is_active
        return s

    def test_include_descendants_false_returns_exact(self):
        """include_descendants=False 只返回当前 subject_id。"""
        from app.services.admin_subject_service import resolve_subject_ids

        db = MagicMock()
        db.get = AsyncMock(return_value=self._make_subject(10, "ds", parent_id=1))

        with patch(
            "app.services.admin_subject_service.resolve_subject_id",
            new_callable=AsyncMock,
            return_value=10,
        ):
            result = _run(resolve_subject_ids(db, "ds", include_descendants=False))
            assert result == [10]

    def test_include_descendants_true_includes_children(self):
        """include_descendants=True（默认）包含后代。"""
        from app.services.admin_subject_service import resolve_subject_ids

        subjects = [
            self._make_subject(1, "cs", parent_id=None),
            self._make_subject(10, "ds", parent_id=1),
            self._make_subject(20, "co", parent_id=1),
        ]

        db = MagicMock()
        # resolve_subject_id → 1
        with patch(
            "app.services.admin_subject_service.resolve_subject_id",
            new_callable=AsyncMock,
            return_value=1,
        ):
            # mock all subjects query (AsyncMock for await)
            all_result = MagicMock()
            all_result.scalars.return_value.all.return_value = subjects

            async def fake_execute(stmt, *a, **kw):
                return all_result

            db.execute = AsyncMock(side_effect=fake_execute)

            result = _run(resolve_subject_ids(db, "cs", include_descendants=True))
            assert set(result) == {1, 10, 20}


# ── resolve_subject_ids 默认兼容性 ───────────────────


def test_resolve_subject_ids_default_include_descendants():
    """resolve_subject_ids 无 include_descendants 参数时保持向后兼容。"""
    from app.services.admin_subject_service import resolve_subject_ids

    db = MagicMock()
    with patch(
        "app.services.admin_subject_service.resolve_subject_id",
        new_callable=AsyncMock,
        return_value=1,
    ):
        all_result = MagicMock()
        all_result.scalars.return_value.all.return_value = []

        async def fake_execute(stmt, *a, **kw):
            return all_result

        db.execute = AsyncMock(side_effect=fake_execute)

        # 不传 include_descendants → 应正常工作
        result = _run(resolve_subject_ids(db, "cs"))
        assert result == [1]


# ── 对抗性测试：聚合均衡 ──────────────────────────────


class TestAggregatedBalance:
    """对抗性测试：验证聚合刷题在各种极端场景下的均衡保证。"""

    @staticmethod
    def _make_q(id_val, subject_id):
        q = MagicMock(spec=Question)
        q.id = id_val
        q.subject_id = subject_id
        return q

    # ── round-robin 纯函数对抗性测试 ──

    def test_round_robin_4_buckets_count_5_distribution(self):
        """4 个非空桶，count=5，分布必须为 2/1/1/1（差值 ≤ 1）。"""
        from app.services.practice_service import _round_robin_merge

        buckets = [
            [self._make_q(i, 10) for i in range(1, 21)],
            [self._make_q(i, 20) for i in range(21, 41)],
            [self._make_q(i, 30) for i in range(41, 61)],
            [self._make_q(i, 40) for i in range(61, 81)],
        ]

        for _ in range(50):  # 多次运行验证稳定性
            result = _round_robin_merge(buckets, count=5, randomize_order=True)
            assert len(result) == 5
            # 计算每桶分布
            from collections import Counter
            bucket_counts = Counter()
            for i, bucket in enumerate(buckets):
                ids = {q.id for q in bucket}
                bucket_counts[i] = sum(1 for q in result if q.id in ids)
            counts = list(bucket_counts.values())
            assert max(counts) - min(counts) <= 1, f"差值超过 1: {counts}"

    def test_round_robin_count_0(self):
        """count=0 返回空列表。"""
        from app.services.practice_service import _round_robin_merge
        result = _round_robin_merge([[1, 2, 3]], count=0)
        assert result == []

    def test_round_robin_count_exceeds_total(self):
        """count 大于全部候选时返回全部去重候选。"""
        from app.services.practice_service import _round_robin_merge
        items = [self._make_q(1, 10), self._make_q(2, 10)]
        result = _round_robin_merge([items], count=100)
        assert len(result) == 2

    def test_round_robin_duplicate_ids_across_buckets(self):
        """不同桶出现相同 question_id 时只保留第一个。"""
        from app.services.practice_service import _round_robin_merge
        q = self._make_q(1, 10)
        buckets = [[q], [self._make_q(1, 20)]]  # 相同 id 1
        result = _round_robin_merge(buckets, count=5)
        ids = [item.id for item in result]
        assert ids == [1]  # 只保留第一个桶的

    def test_round_robin_input_not_mutated(self):
        """输入桶列表不被原地修改。"""
        from app.services.practice_service import _round_robin_merge
        q1, q2 = self._make_q(1, 10), self._make_q(2, 20)
        buckets = [[q1], [q2]]
        original_ids = [id(b) for b in buckets]
        _round_robin_merge(buckets, count=2, randomize_order=False)
        assert [id(b) for b in buckets] == original_ids

    # ── random 聚合对抗性测试 ──

    def test_random_aggregation_4_subjects_adversarial(self):
        """4 个启用子科目各 10 题，count=5，必须覆盖全部 4 科。"""
        from app.services.practice_service import get_aggregated_random_questions

        db = MagicMock()
        # 每科 10 题
        all_questions = {}
        for sid in [10, 20, 30, 40]:
            all_questions[sid] = [self._make_q(sid * 100 + i, sid) for i in range(10)]

        # 模拟 _get_questions_with_leitner 按 subject_id 返回相应题目
        async def fake_leitner(db_inner, user_id, base_conditions, mode, count, **kw):
            for cond in base_conditions:
                if hasattr(cond, 'right') and hasattr(cond.right, 'value'):
                    sid = cond.right.value
                    return all_questions.get(sid, [])[:count]
            return []

        with patch(
            "app.services.practice_service._get_questions_with_leitner",
            new_callable=AsyncMock,
            side_effect=fake_leitner,
        ):
            for _ in range(20):  # 多次验证稳定性
                result = _run(get_aggregated_random_questions(
                    db, user_id=1, subject_code="cs",
                    subject_ids=[10, 20, 30, 40], count=5,
                ))
                assert len(result) == 5
                subj_ids_in_result = {q.subject_id for q in result}
                assert len(subj_ids_in_result) == 4, f"应覆盖 4 科，实际: {subj_ids_in_result}"
                # 分布差值不超过 1
                from collections import Counter
                dist = Counter(q.subject_id for q in result)
                counts = list(dist.values())
                assert max(counts) - min(counts) <= 1, f"差值超过 1: {counts}"

    def test_random_aggregation_some_subjects_empty(self):
        """部分子科目无题时自动跳过，不缺科目。"""
        from app.services.practice_service import get_aggregated_random_questions

        db = MagicMock()
        # 只有 2 个科目有题
        questions_10 = [self._make_q(i, 10) for i in range(1, 11)]
        questions_30 = [self._make_q(i, 30) for i in range(101, 111)]

        async def fake_leitner(db_inner, user_id, base_conditions, mode, count, **kw):
            for cond in base_conditions:
                if hasattr(cond, 'right') and hasattr(cond.right, 'value'):
                    sid = cond.right.value
                    if sid == 10:
                        return questions_10[:count]
                    elif sid == 30:
                        return questions_30[:count]
            return []

        with patch(
            "app.services.practice_service._get_questions_with_leitner",
            new_callable=AsyncMock,
            side_effect=fake_leitner,
        ):
            result = _run(get_aggregated_random_questions(
                db, user_id=1, subject_code="cs",
                subject_ids=[10, 20, 30, 40], count=5,
            ))
            assert len(result) == 5
            subj_ids = {q.subject_id for q in result}
            assert 20 not in subj_ids  # 无题科目
            assert 40 not in subj_ids
            assert len(subj_ids) == 2  # 只有两科有题
            # 分布应尽量均衡
            from collections import Counter
            dist = Counter(q.subject_id for q in result)
            counts = list(dist.values())
            assert max(counts) - min(counts) <= 1, f"差值超过 1: {counts}"

    # ── smart 聚合对抗性测试 ──

    def test_smart_aggregation_3_subjects_adversarial(self):
        """3 个科目各有 smart 候选，各科推荐分数显著不同时仍被均衡覆盖。"""
        from app.services.practice_service import get_aggregated_smart_questions

        db = MagicMock()
        # Mock Subject query
        subj_result = MagicMock()
        subj_result.scalars.return_value.all.return_value = [
            self._make_q(10, 10) if False else MagicMock(id=10, code="ds"),
            self._make_q(20, 20) if False else MagicMock(id=20, code="os"),
            self._make_q(30, 30) if False else MagicMock(id=30, code="cn"),
        ]
        # Fix mock subjects
        subj_result.scalars.return_value.all.return_value = [
            type('s', (), {'id': 10, 'code': 'ds'})(),
            type('s', (), {'id': 20, 'code': 'os'})(),
            type('s', (), {'id': 30, 'code': 'cn'})(),
        ]
        # Actually use SimpleNamespace
        from types import SimpleNamespace
        mock_subjects = [
            SimpleNamespace(id=10, code='ds'),
            SimpleNamespace(id=20, code='os'),
            SimpleNamespace(id=30, code='cn'),
        ]
        subj_result.scalars.return_value.all.return_value = mock_subjects
        db.execute = AsyncMock(return_value=subj_result)

        # 每科各 10 题，但第一个科目的推荐分数显著更高（对抗单次全局 top-K）
        # smart 返回的 metadata 包含 recommend_score
        smart_output = {}
        for sid, code in [(10, 'ds'), (20, 'os'), (30, 'cn')]:
            qs = []
            meta = {}
            base_score = 0.95 if sid == 10 else 0.3
            for i in range(10):
                q = MagicMock(spec=Question)
                q.id = sid * 100 + i
                q.subject_id = sid
                qs.append(q)
                meta[q.id] = {
                    "recommend_score": base_score - i * 0.01,
                    "recommend_reason": "test",
                    "strategy": "smart_vector",
                    "similarity": base_score - i * 0.01,
                }
            smart_output[code] = (qs, meta)

        async def fake_smart(**kw):
            subj = kw.get("subject_code", "")
            return smart_output.get(subj, ([], {}))

        with patch(
            "app.services.practice_service.get_smart_practice_questions",
            new_callable=AsyncMock,
            side_effect=fake_smart,
        ):
            merged_qs, merged_meta = _run(get_aggregated_smart_questions(
                db, user_id=1, subject_code="cs",
                subject_ids=[10, 20, 30], count=6,
            ))
            assert len(merged_qs) == 6
            # 验证覆盖全部 3 科
            subj_set = {q.subject_id for q in merged_qs}
            assert len(subj_set) == 3, f"应覆盖 3 科，实际: {subj_set}"

            # 验证 metadata 对应正确
            for q in merged_qs:
                assert q.id in merged_meta
                assert merged_meta[q.id]["strategy"] == "smart_vector"
                assert merged_meta[q.id]["recommend_reason"] == "test"

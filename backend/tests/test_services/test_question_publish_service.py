"""Stage 10 发布服务 — 单元测试（mock DB session）。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.features.question_publish_service import (
    _migrate_old_approved,
    approve_and_publish,
    get_publish_history,
    publish_questions,
    publish_single_question,
)

_NEXT_QUESTION_ID = 0


def _next_qid():
    global _NEXT_QUESTION_ID
    _NEXT_QUESTION_ID += 1
    return _NEXT_QUESTION_ID


# --- helpers ---

def _make_qi_mock(qi_id=1, status="approved", question_id=None, subject="math2",
                  question_type="single_choice", source_type="manual", source_file="test.pdf",
                  batch_id="BATCH_1", parsed_content=None, parsed_options=None,
                  parsed_answer="A", parsed_analysis="analysis", raw_data=None,
                  ai_metadata=None, ai_generated=False):
    qi = MagicMock()
    qi.id = qi_id
    qi.status = status
    qi.question_id = question_id
    qi.subject = subject
    qi.question_type = question_type
    qi.source_type = source_type
    qi.source_file = source_file
    qi.batch_id = batch_id
    qi.parsed_content = parsed_content or {"text": "设函数 f(x)=x^2，求 f'(x)。"}
    qi.parsed_options = parsed_options or {"A": "2x", "B": "x", "C": "x^2", "D": "2"}
    qi.parsed_answer = parsed_answer
    qi.parsed_analysis = parsed_analysis
    qi.raw_data = raw_data or {"stem": "test"}
    qi.ai_metadata = ai_metadata or {}
    qi.ai_generated = ai_generated
    return qi


def _make_mock_db():
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    async def _refresh(obj):
        if hasattr(obj, "id") and obj.id is None:
            obj.id = _next_qid()

    db.refresh = _refresh
    db.commit = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.rollback = AsyncMock()
    return db


def _make_execute_result(**methods):
    mock_result = MagicMock()
    for method, value in methods.items():
        if method == "scalars":
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = value
            mock_result.scalars.return_value = mock_scalars
        else:
            getattr(mock_result, method).return_value = value
    return mock_result


def _make_pipeline_result(is_valid=True, subject="math2", stem="设函数 f(x)=x^2，求 f'(x)。",
                          question_fields=None, errors=None, warnings=None,
                          stem_hash="abc123def456"):
    return {
        "source_type": "manual",
        "normalized": {
            "subject": subject,
            "stem": stem,
            "question_type": "single_choice",
            "answer": "A",
            "options": [{"key": "A", "text": "2x"}],
            "analysis": "analysis",
            "question_hash": "hash123",
        },
        "is_valid": is_valid,
        "errors": errors or [],
        "warnings": warnings or [],
        "stem_hash": stem_hash,
        "question_fields": question_fields or {
            "subject": subject,
            "question_type": "single_choice",
            "content": {"text": stem},
            "options": [{"key": "A", "text": "2x"}],
            "answer": "A",
            "analysis": "analysis",
            "knowledge_points": ["导数"],
            "difficulty": 3,
            "question_hash": "hash123",
        },
    }


# --- _migrate_old_approved ---

class TestMigrateOldApproved:
    def test_migrates_records_with_question_id(self):
        db = _make_mock_db()
        qis = [_make_qi_mock(qi_id=1, status="approved", question_id=100)]
        # First query: approved with question_id; second query: approved without question_id (orphans)
        db.execute.side_effect = [
            _make_execute_result(scalars=qis),  # has question_id
            _make_execute_result(scalars=[]),   # orphans (none)
        ]

        count = asyncio.run(_migrate_old_approved(db))

        assert count == 1
        assert qis[0].status == "published"

    def test_no_old_records(self):
        db = _make_mock_db()
        db.execute.side_effect = [
            _make_execute_result(scalars=[]),  # has question_id
            _make_execute_result(scalars=[]),  # orphans
        ]

        count = asyncio.run(_migrate_old_approved(db))

        assert count == 0
    def test_migration_queries_only_required_columns(self):
        db = _make_mock_db()
        db.execute.side_effect = [
            _make_execute_result(scalars=[]),  # has question_id
            _make_execute_result(scalars=[]),  # orphans
        ]

        count = asyncio.run(_migrate_old_approved(db))

        assert count == 0
        for call in db.execute.call_args_list:
            query_text = str(call.args[0])
            assert "reject_reason" not in query_text
            assert "reviewed_by" not in query_text
            assert "reviewed_at" not in query_text


# --- publish_single_question ---

class TestPublishSingleQuestion:
    def test_publish_success(self):
        db = _make_mock_db()
        qi = _make_qi_mock()

        with patch(
            "app.features.question_publish_service.process_question_pipeline",
            return_value=_make_pipeline_result(),
        ), patch(
            "app.features.question_publish_service._find_duplicate_by_hash",
            return_value=None,
        ), patch(
            "app.features.question_publish_service._find_duplicate_by_stem_similarity",
            return_value=None,
        ):
            result = asyncio.run(publish_single_question(db, qi))

        assert result["status"] == "published"
        assert result["id"] == 1
        assert result["question_id"] is not None
        assert qi.status == "published"
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    def test_duplicate_skip(self):
        db = _make_mock_db()
        qi = _make_qi_mock()
        dup_q = MagicMock()
        dup_q.id = 99

        with patch(
            "app.features.question_publish_service.process_question_pipeline",
            return_value=_make_pipeline_result(),
        ), patch(
            "app.features.question_publish_service._find_duplicate_by_hash",
            return_value=dup_q,
        ):
            result = asyncio.run(publish_single_question(db, qi))

        assert result["status"] == "duplicate"
        assert result["question_id"] == 99
        assert result["reason"] == "question_hash collision"
        db.add.assert_not_called()

    def test_invalid_data(self):
        db = _make_mock_db()
        qi = _make_qi_mock()

        with patch(
            "app.features.question_publish_service.process_question_pipeline",
            return_value=_make_pipeline_result(is_valid=False, errors=["stem_empty"], question_fields=None),
        ):
            result = asyncio.run(publish_single_question(db, qi))

        assert result["status"] == "failed"
        assert "stem_empty" in result["reason"]
        db.add.assert_not_called()

    def test_not_approved(self):
        db = _make_mock_db()
        qi = _make_qi_mock(status="pending")

        result = asyncio.run(publish_single_question(db, qi))

        assert result["status"] == "failed"
        assert "非 approved" in result["reason"]

    def test_already_published(self):
        db = _make_mock_db()
        qi = _make_qi_mock(status="published", question_id=100)

        result = asyncio.run(publish_single_question(db, qi))

        assert result["status"] == "failed"
        assert result["reason"] == "已发布"


# --- publish_questions ---

class TestPublishQuestions:
    def test_publish_by_ids(self):
        db = _make_mock_db()
        qis = [
            _make_qi_mock(qi_id=1),
            _make_qi_mock(qi_id=2),
        ]
        db.execute.side_effect = [
            _make_execute_result(scalars=[]),  # _migrate: has question_id
            _make_execute_result(scalars=[]),  # _migrate: orphans
            _make_execute_result(scalars=qis),   # select approved records
        ]

        with patch(
            "app.features.question_publish_service.process_question_pipeline",
            return_value=_make_pipeline_result(),
        ), patch(
            "app.features.question_publish_service._find_duplicate_by_hash",
            return_value=None,
        ), patch(
            "app.features.question_publish_service._find_duplicate_by_stem_similarity",
            return_value=None,
        ):
            result = asyncio.run(publish_questions(db, question_ids=[1, 2]))

        assert result.total == 2
        assert result.published == 2
        assert result.duplicates == 0
        assert result.failed == 0
        db.commit.assert_awaited_once()

    def test_publish_by_batch_id(self):
        db = _make_mock_db()
        qis = [_make_qi_mock(qi_id=1, batch_id="BATCH_X")]
        db.execute.side_effect = [
            _make_execute_result(scalars=[]),  # _migrate: has question_id
            _make_execute_result(scalars=[]),  # _migrate: orphans
            _make_execute_result(scalars=qis),
        ]

        with patch(
            "app.features.question_publish_service.process_question_pipeline",
            return_value=_make_pipeline_result(),
        ), patch(
            "app.features.question_publish_service._find_duplicate_by_hash",
            return_value=None,
        ), patch(
            "app.features.question_publish_service._find_duplicate_by_stem_similarity",
            return_value=None,
        ):
            result = asyncio.run(publish_questions(db, batch_id="BATCH_X"))

        assert result.total == 1
        assert result.published == 1

    def test_partial_duplicates(self):
        db = _make_mock_db()
        qis = [
            _make_qi_mock(qi_id=1),
            _make_qi_mock(qi_id=2),
        ]
        dup_q = MagicMock()
        dup_q.id = 99

        db.execute.side_effect = [
            _make_execute_result(scalars=[]),  # _migrate: has question_id
            _make_execute_result(scalars=[]),  # _migrate: orphans
            _make_execute_result(scalars=qis),
        ]

        pipeline_results = iter([_make_pipeline_result(), _make_pipeline_result()])
        dup_results = iter([None, dup_q])  # first: no dup, second: dup

        def mock_pipeline(*args, **kwargs):
            return next(pipeline_results)

        async def mock_find_dup(*args, **kwargs):
            return next(dup_results)

        with patch(
            "app.features.question_publish_service.process_question_pipeline",
            side_effect=mock_pipeline,
        ), patch(
            "app.features.question_publish_service._find_duplicate_by_hash",
            side_effect=mock_find_dup,
        ), patch(
            "app.features.question_publish_service._find_duplicate_by_stem_similarity",
            return_value=None,
        ):
            result = asyncio.run(publish_questions(db, question_ids=[1, 2]))

        assert result.total == 2
        assert result.published == 1
        assert result.duplicates == 1
        assert result.failed == 0

    def test_empty_id_list(self):
        db = _make_mock_db()
        db.execute.side_effect = [
            _make_execute_result(scalars=[]),  # _migrate: has question_id
            _make_execute_result(scalars=[]),  # _migrate: orphans
            _make_execute_result(scalars=[]),  # select
        ]

        result = asyncio.run(publish_questions(db, question_ids=[]))

        assert result.total == 0

    def test_skips_non_approved_in_batch(self):
        db = _make_mock_db()
        qis = [_make_qi_mock(qi_id=1, status="approved")]
        # Only approved records are selected; pending/rejected are filtered by query

        db.execute.side_effect = [
            _make_execute_result(scalars=[]),  # _migrate: has question_id
            _make_execute_result(scalars=[]),  # _migrate: orphans
            _make_execute_result(scalars=qis),
        ]

        with patch(
            "app.features.question_publish_service.process_question_pipeline",
            return_value=_make_pipeline_result(),
        ), patch(
            "app.features.question_publish_service._find_duplicate_by_hash",
            return_value=None,
        ), patch(
            "app.features.question_publish_service._find_duplicate_by_stem_similarity",
            return_value=None,
        ):
            result = asyncio.run(publish_questions(db, question_ids=[1, 2, 3]))

        # Only 1 approved record selected
        assert result.total == 1
        assert result.published == 1


# --- approve_and_publish ---

class TestApproveAndPublish:
    def test_approve_and_publish_pending(self):
        db = _make_mock_db()
        qi = _make_qi_mock(qi_id=1, status="pending")
        db.execute.side_effect = [
            _make_execute_result(scalars=[]),   # _migrate: has question_id
            _make_execute_result(scalars=[]),   # _migrate: orphans
            _make_execute_result(scalars=[qi]),  # select records
        ]

        with patch(
            "app.features.question_publish_service.process_question_pipeline",
            return_value=_make_pipeline_result(),
        ), patch(
            "app.features.question_publish_service._find_duplicate_by_hash",
            return_value=None,
        ), patch(
            "app.features.question_publish_service._find_duplicate_by_stem_similarity",
            return_value=None,
        ):
            result = asyncio.run(approve_and_publish(db, question_ids=[1]))

        assert result.total == 1
        assert result.approved == 1
        assert result.published == 1
        assert qi.status == "published"

    def test_approve_and_publish_already_approved(self):
        db = _make_mock_db()
        qi = _make_qi_mock(qi_id=1, status="approved")
        db.execute.side_effect = [
            _make_execute_result(scalars=[]),   # _migrate: has question_id
            _make_execute_result(scalars=[]),   # _migrate: orphans
            _make_execute_result(scalars=[qi]),
        ]

        with patch(
            "app.features.question_publish_service.process_question_pipeline",
            return_value=_make_pipeline_result(),
        ), patch(
            "app.features.question_publish_service._find_duplicate_by_hash",
            return_value=None,
        ), patch(
            "app.features.question_publish_service._find_duplicate_by_stem_similarity",
            return_value=None,
        ):
            result = asyncio.run(approve_and_publish(db, question_ids=[1]))

        assert result.approved == 0  # already approved, not counted
        assert result.published == 1

    def test_approve_and_publish_rejected(self):
        db = _make_mock_db()
        qi = _make_qi_mock(qi_id=1, status="rejected")
        db.execute.side_effect = [
            _make_execute_result(scalars=[]),   # _migrate: has question_id
            _make_execute_result(scalars=[]),   # _migrate: orphans
            _make_execute_result(scalars=[qi]),
        ]

        result = asyncio.run(approve_and_publish(db, question_ids=[1]))

        assert result.failed == 1
        assert "已拒绝" in result.details[0].reason

    def test_approve_and_publish_already_published(self):
        db = _make_mock_db()
        qi = _make_qi_mock(qi_id=1, status="published", question_id=100)
        db.execute.side_effect = [
            _make_execute_result(scalars=[]),   # _migrate: has question_id
            _make_execute_result(scalars=[]),   # _migrate: orphans
            _make_execute_result(scalars=[qi]),
        ]

        result = asyncio.run(approve_and_publish(db, question_ids=[1]))

        assert result.failed == 1
        assert result.details[0].reason == "已发布"

    def test_approve_and_publish_invalid_data(self):
        db = _make_mock_db()
        qi = _make_qi_mock(qi_id=1, status="pending")
        db.execute.side_effect = [
            _make_execute_result(scalars=[]),   # _migrate: has question_id
            _make_execute_result(scalars=[]),   # _migrate: orphans
            _make_execute_result(scalars=[qi]),
        ]

        with patch(
            "app.features.question_publish_service.process_question_pipeline",
            return_value=_make_pipeline_result(is_valid=False, errors=["stem_empty"], question_fields=None),
        ):
            result = asyncio.run(approve_and_publish(db, question_ids=[1]))

        assert result.failed == 1
        assert "stem_empty" in result.details[0].reason

    def test_approve_and_publish_empty_ids(self):
        db = _make_mock_db()
        db.execute.side_effect = [
            _make_execute_result(scalars=[]),  # _migrate: has question_id
            _make_execute_result(scalars=[]),  # _migrate: orphans
        ]

        result = asyncio.run(approve_and_publish(db, question_ids=[]))

        assert result.total == 0

    def test_approve_and_publish_mixed(self):
        db = _make_mock_db()
        qis = [
            _make_qi_mock(qi_id=1, status="pending"),
            _make_qi_mock(qi_id=2, status="approved"),
            _make_qi_mock(qi_id=3, status="rejected"),
        ]
        db.execute.side_effect = [
            _make_execute_result(scalars=[]),    # _migrate: has question_id
            _make_execute_result(scalars=[]),    # _migrate: orphans
            _make_execute_result(scalars=qis),
        ]

        dup_q = MagicMock()
        dup_q.id = 99

        # qi 1 (pending): pipeline called for validation + publish (2 calls)
        # qi 2 (approved): pipeline called for publish only (1 call)
        # qi 3 (rejected): skipped, no pipeline calls
        pipeline_returns = iter([
            _make_pipeline_result(),  # qi 1 validate
            _make_pipeline_result(),  # qi 1 publish
            _make_pipeline_result(),  # qi 2 publish
        ])
        dup_returns = iter([None, dup_q])  # qi 1 publish: no dup, qi 2 publish: dup

        def mock_pipeline(*args, **kwargs):
            return next(pipeline_returns)

        async def mock_find_dup(*args, **kwargs):
            return next(dup_returns)

        with patch(
            "app.features.question_publish_service.process_question_pipeline",
            side_effect=mock_pipeline,
        ), patch(
            "app.features.question_publish_service._find_duplicate_by_hash",
            side_effect=mock_find_dup,
        ), patch(
            "app.features.question_publish_service._find_duplicate_by_stem_similarity",
            return_value=None,
        ):
            result = asyncio.run(approve_and_publish(db, question_ids=[1, 2, 3]))

        assert result.total == 3
        assert result.approved == 1  # only qi 1 was pending → approved
        assert result.published == 1  # qi 1 published
        assert result.duplicates == 1  # qi 2 duplicate
        assert result.failed == 1  # qi 3 rejected


# --- get_publish_history ---

class TestGetPublishHistory:
    def test_history_with_items(self):
        db = _make_mock_db()
        from datetime import datetime

        now = datetime(2025, 5, 24, 10, 0, 0)
        batch_rows = [
            SimpleNamespace(batch_id="BATCH_1", published_at=now, total=3),
        ]
        # Production SQL returns 3-element tuples: (batch_id, status, count)
        stats_rows = [
            ("BATCH_1", "published", 2),
            ("BATCH_1", "duplicate", 1),
        ]

        db.execute.side_effect = [
            _make_execute_result(scalar=1),       # count
            _make_execute_result(all=batch_rows),  # batch query
            _make_execute_result(all=stats_rows),  # stats query
        ]

        result = asyncio.run(get_publish_history(db))

        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].batch_id == "BATCH_1"
        assert result.items[0].published == 2
        assert result.items[0].duplicates == 1
        assert result.page == 1
        assert result.page_size == 20

    def test_history_empty(self):
        db = _make_mock_db()
        db.execute.side_effect = [
            _make_execute_result(scalar=0),   # count
            _make_execute_result(all=[]),     # batch query
        ]

        result = asyncio.run(get_publish_history(db))

        assert result.total == 0
        assert result.items == []

    def test_history_pagination(self):
        db = _make_mock_db()
        from datetime import datetime

        now = datetime(2025, 5, 24, 10, 0, 0)
        batch_rows = [SimpleNamespace(batch_id="BATCH_2", published_at=now, total=1)]
        # Production SQL returns 3-element tuples: (batch_id, status, count)
        stats_rows = [("BATCH_2", "published", 1)]

        db.execute.side_effect = [
            _make_execute_result(scalar=5),       # count
            _make_execute_result(all=batch_rows),  # batch query
            _make_execute_result(all=stats_rows),  # stats query
        ]

        result = asyncio.run(get_publish_history(db, page=2, page_size=1))

        assert result.total == 5
        assert result.page == 2
        assert result.page_size == 1
        assert len(result.items) == 1

    def test_history_multi_batch(self):
        """Multi-batch: verify per-batch stats are correctly aggregated (P0 regression)."""
        db = _make_mock_db()
        from datetime import datetime

        now1 = datetime(2025, 5, 24, 10, 0, 0)
        now2 = datetime(2025, 5, 25, 11, 0, 0)
        batch_rows = [
            SimpleNamespace(batch_id="BATCH_A", published_at=now2, total=5),
            SimpleNamespace(batch_id="BATCH_B", published_at=now1, total=3),
        ]
        # Each batch has its own stats — must not cross-contaminate
        stats_rows = [
            ("BATCH_A", "published", 4),
            ("BATCH_A", "duplicate", 1),
            ("BATCH_B", "published", 2),
            ("BATCH_B", "failed", 1),
        ]

        db.execute.side_effect = [
            _make_execute_result(scalar=2),       # count
            _make_execute_result(all=batch_rows),  # batch query
            _make_execute_result(all=stats_rows),  # stats query
        ]

        result = asyncio.run(get_publish_history(db, page=1, page_size=10))

        assert result.total == 2
        assert len(result.items) == 2
        # BATCH_A: 4 published, 1 duplicate
        assert result.items[0].batch_id == "BATCH_A"
        assert result.items[0].published == 4
        assert result.items[0].duplicates == 1
        assert result.items[0].failed == 0
        # BATCH_B: 2 published, 1 failed — NOT contaminated by BATCH_A's stats
        assert result.items[1].batch_id == "BATCH_B"
        assert result.items[1].published == 2
        assert result.items[1].duplicates == 0
        assert result.items[1].failed == 1

"""Stage 7 审核系统 — 单元测试（mock DB session）。"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.features.review_service import (
    _options_to_dict,
    fix_question,
    get_review_queue,
    submit_to_review,
)

# Ensure all ORM models are registered so Subject's string relationships
# (practice_records, answer_behaviors, review_schedules, ...) resolve at
# mapper configuration time (see app/models/admin.py Subject).
from app.models.answer_behavior import AnswerBehavior  # noqa: F401
from app.models.import_batch_job import ImportBatchJob  # noqa: F401
from app.models.knowledge_edge import KnowledgeEdge  # noqa: F401
from app.models.knowledge_point import KnowledgePoint  # noqa: F401
from app.models.pomodoro import PomodoroSession  # noqa: F401
from app.models.practice_record import PracticeRecord  # noqa: F401
from app.models.recommendation_log import RecommendationLog  # noqa: F401
from app.models.recommendation_metrics_daily import (
    RecommendationMetricsDaily,  # noqa: F401
)
from app.models.review_scheduler import ReviewSchedule  # noqa: F401
from app.models.tag import Tag  # noqa: F401
from app.models.user_knowledge_state import UserKnowledgeState  # noqa: F401

# --- helpers ---

def _make_question(overrides=None):
    """构造一道 Stage5 标准化题目。"""
    q = {
        "stem": "设函数 f(x) = x^2，求 f'(x)。",
        "options": [
            {"key": "A", "text": "2x"},
            {"key": "B", "text": "x"},
            {"key": "C", "text": "x^2"},
            {"key": "D", "text": "2"},
        ],
        "answer": "A",
        "analysis": "求导得 2x",
        "question_type": "single_choice",
        "subject_id": 1,
        "confidence_score": 0.85,
        "is_valid": True,
        "errors": [],
        "warnings": [],
        "source": {"file": "test.pdf", "page": 1, "type": "pdf"},
        "knowledge_points": ["导数"],
        "difficulty": 2,
        "stem_hash": "abc12345",
    }
    if overrides:
        q.update(overrides)
    return q


def _make_mock_db():
    """创建一个 mock AsyncSession。"""
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock(return_value=_make_execute_result(scalar_one_or_none=None, all=[]))
    return db


def _make_execute_result(**methods):
    """构造 mock execute 返回值，methods 如 scalar=..., scalars=..., scalar_one_or_none=..."""
    mock_result = MagicMock()
    for method, value in methods.items():
        if method == "scalars":
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = value
            mock_result.scalars.return_value = mock_scalars
        else:
            getattr(mock_result, method).return_value = value
    return mock_result


def _mock_execute_sequence(db, *results):
    """配置 db.execute 按顺序返回不同结果。每个 result 是一个 dict，如 {scalar: 3} 或 {scalars: [...]}。"""
    db.execute.side_effect = [_make_execute_result(**r) for r in results]


# --- _options_to_dict ---

class TestOptionsToDict:
    def test_empty(self):
        assert _options_to_dict([]) is None

    def test_standard(self):
        opts = [{"key": "A", "text": "2x"}, {"key": "B", "text": "x"}]
        assert _options_to_dict(opts) == {"A": "2x", "B": "x"}

    def test_missing_key(self):
        opts = [{"key": "", "text": "text"}, {"key": "A", "text": "valid"}]
        assert _options_to_dict(opts) == {"A": "valid"}

    def test_missing_text(self):
        opts = [{"key": "A", "text": ""}]
        assert _options_to_dict(opts) is None

    def test_lowercase_key(self):
        opts = [{"key": "a", "text": "value"}]
        assert _options_to_dict(opts) == {"A": "value"}


# --- submit_to_review ---

class TestSubmitToReview:

    def _setup(self):
        db = _make_mock_db()
        added = []

        def _add(obj):
            obj.id = len(added) + 1
            added.append(obj)

        db.add.side_effect = _add
        return db, added

    def test_writes_single_question(self):
        db, added = self._setup()
        q = _make_question()

        result = asyncio.run(submit_to_review(
            db, [q],
            {"source_type": "pdf", "source_file": "test.pdf", "subject_id": 1},
        ))

        assert result["total"] == 1
        assert result["written"] == 1
        assert result["skipped"] == 0
        assert result["batch_id"].startswith("REVIEW_")
        assert len(result["items"]) == 1
        assert result["items"][0]["status"] == "pending"
        assert result["items"][0]["stem_preview"] == q["stem"]
        assert result["items"][0]["confidence_score"] == 0.85
        assert result["items"][0]["has_issues"] is False

        assert len(added) == 1
        qi = added[0]
        assert qi.batch_id == result["batch_id"]
        assert qi.source_type == "pdf"
        assert qi.source_file == "test.pdf"
        assert qi.parsed_content == {"text": q["stem"]}
        assert qi.parsed_options == {"A": "2x", "B": "x", "C": "x^2", "D": "2"}
        assert qi.parsed_answer == "A"
        assert qi.parsed_analysis == "求导得 2x"
        assert qi.status == "pending"
        assert qi.ai_confidence == 0.85
        assert qi.created_at == qi.updated_at
        assert isinstance(qi.created_at, datetime)
        assert datetime.now(timezone.utc).replace(tzinfo=None) - qi.created_at < timedelta(seconds=5)
        assert qi.ai_metadata["is_valid"] is True
        assert qi.ai_metadata["stem_hash"] == "abc12345"
        db.commit.assert_awaited_once()

    def test_writes_multiple_questions(self):
        db, added = self._setup()
        questions = [
            _make_question(),
            _make_question({"stem": "第二题题干", "confidence_score": 0.5}),
        ]

        result = asyncio.run(submit_to_review(db, questions))

        assert result["total"] == 2
        assert result["written"] == 2
        assert result["skipped"] == 0
        assert len(result["items"]) == 2
        assert len(added) == 2
        assert added[1].ai_confidence == 0.5
        assert db.commit.call_count == 1

    def test_skips_empty_stem(self):
        db, added = self._setup()
        questions = [
            _make_question({"stem": ""}),
            _make_question({"stem": "   "}),
            _make_question(),
        ]

        result = asyncio.run(submit_to_review(db, questions))

        assert result["total"] == 3
        assert result["written"] == 1
        assert result["skipped"] == 2
        assert len(added) == 1

    def test_empty_stem_with_raw_text_enters_review(self):
        db, added = self._setup()
        raw_text = "OCR 原文仍有内容，应进入人工审核。"
        q = _make_question({"stem": "", "raw_text": raw_text})

        result = asyncio.run(submit_to_review(db, [q]))

        assert result["total"] == 1
        assert result["written"] == 1
        assert result["skipped"] == 0
        assert result["items"][0]["status"] == "pending"
        assert result["items"][0]["stem_preview"] == raw_text
        assert result["items"][0]["confidence_score"] == 0
        assert result["items"][0]["has_issues"] is True

        assert len(added) == 1
        qi = added[0]
        assert qi.status == "pending"
        assert qi.parsed_content == {"text": raw_text}
        assert qi.ai_confidence == 0
        assert qi.ai_metadata["is_valid"] is False
        assert "empty_stem_raw_text_fallback" in qi.ai_metadata["errors"]
        assert "题干为空，已用 OCR 原文进入待审核区" in qi.ai_metadata["warnings"]

    def test_empty_stem_with_raw_question_text_enters_review(self):
        db, added = self._setup()
        raw_text = "raw_question_text 原文"
        q = _make_question({"stem": "   ", "raw_question_text": raw_text})

        result = asyncio.run(submit_to_review(db, [q]))

        assert result["written"] == 1
        assert result["skipped"] == 0
        assert added[0].parsed_content == {"text": raw_text}

    def test_skips_non_dict(self):
        db, added = self._setup()

        result = asyncio.run(submit_to_review(db, ["not_a_dict", _make_question()]))

        assert result["total"] == 2
        assert result["written"] == 1
        assert result["skipped"] == 1

    def test_empty_list(self):
        db = _make_mock_db()

        result = asyncio.run(submit_to_review(db, []))

        assert result["total"] == 0
        assert result["written"] == 0
        assert result["skipped"] == 0
        assert result["items"] == []
        db.add.assert_not_called()
        db.commit.assert_awaited_once()

    def test_has_issues_when_invalid(self):
        db, added = self._setup()
        q = _make_question({"is_valid": False, "errors": ["missing_answer"]})

        result = asyncio.run(submit_to_review(db, [q]))

        assert result["items"][0]["has_issues"] is True
        assert added[0].ai_metadata["is_valid"] is False
        assert added[0].ai_metadata["errors"] == ["missing_answer"]

    def test_null_batch_meta(self):
        db, added = self._setup()

        result = asyncio.run(submit_to_review(db, [_make_question()], None))

        assert result["batch_id"].startswith("REVIEW_")
        assert added[0].source_type == "pdf"

    def test_multi_blank_choice_preserves_blank_option_groups(self):
        db, added = self._setup()
        groups = [
            {
                "id": "1",
                "options": [
                    {"key": "A", "text": "n+1"},
                    {"key": "B", "text": "n"},
                    {"key": "C", "text": "n−1"},
                    {"key": "D", "text": "1"},
                ],
            },
            {
                "id": "2",
                "options": [
                    {"key": "A", "text": "n+1"},
                    {"key": "B", "text": "n"},
                    {"key": "C", "text": "n−1"},
                    {"key": "D", "text": "1"},
                ],
            },
        ]
        q = _make_question({
            "stem": "若系统有 n 个进程，则就绪队列中进程的个数最多有（1）个；阻塞队列中进程的个数最多有（2）个。",
            "options": [],
            "answer": "",
            "question_type": "multi_blank_choice",
            "blank_option_groups": groups,
        })

        result = asyncio.run(submit_to_review(db, [q]))

        assert result["written"] == 1
        assert added[0].question_type == "multi_blank_choice"
        assert added[0].parsed_options is None
        assert added[0].parsed_answer is None
        assert added[0].parsed_content == {
            "text": q["stem"],
            "blank_option_groups": groups,
        }
        assert added[0].raw_data["blank_option_groups"] == groups

    def test_multi_blank_choice_logs_group_summary(self, caplog):
        db, added = self._setup()
        q = _make_question({
            "question_type": "multi_blank_choice",
            "options": [],
            "blank_option_groups": [
                {"id": 1, "options": {"A": "a1", "B": "b1", "C": "c1", "D": "d1"}},
            ],
        })

        with caplog.at_level("INFO", logger="app.features.review_service"):
            asyncio.run(submit_to_review(db, [q]))

        assert added[0].parsed_options is None
        records = [
            record for record in caplog.records
            if record.message == "multi_blank_choice review item imported"
        ]
        assert len(records) == 1
        assert records[0].import_id == added[0].id
        assert records[0].question_type == "multi_blank_choice"
        assert records[0].blank_option_group_count == 1
        assert records[0].blank_option_groups == [{"id": 1, "option_keys": ["A", "B", "C", "D"]}]
        assert records[0].raw_data_has_blank_option_groups is True

    def test_stem_preview_truncation(self):
        db, added = self._setup()
        long_stem = "A" * 60
        q = _make_question({"stem": long_stem})

        result = asyncio.run(submit_to_review(db, [q]))

        assert result["items"][0]["stem_preview"] == "A" * 50 + "..."

    def test_risk_flags_written_to_ai_metadata(self):
        """P1-2: 上游 stage 写入的 risk_flags 透传到 ai_metadata.risk_flags，
        前端审核页据此打风险徽章。值域见
        prompts/tasks/ocr_book_pdf_non_question_filter_plan.md §11.3。"""
        db, added = self._setup()
        q = _make_question({
            "risk_flags": ["no_exercise_regions", "low_confidence"],
        })

        asyncio.run(submit_to_review(db, [q]))

        assert added[0].ai_metadata["risk_flags"] == [
            "no_exercise_regions", "low_confidence",
        ]

    def test_empty_risk_flags_stored_as_none(self):
        """无风险时 ai_metadata.risk_flags=None，减少 JSON 体积。"""
        db, added = self._setup()
        q = _make_question()  # 没传 risk_flags

        asyncio.run(submit_to_review(db, [q]))

        assert added[0].ai_metadata["risk_flags"] is None

    def test_duplicate_risk_flags_deduplicated_preserving_order(self):
        """同一 flag 被多个 stage 重复写入时去重并保序。"""
        db, added = self._setup()
        q = _make_question({
            "risk_flags": [
                "low_confidence",
                "no_exercise_regions",
                "low_confidence",  # 重复
                "book_pdf_prose_like",
            ],
        })

        asyncio.run(submit_to_review(db, [q]))

        assert added[0].ai_metadata["risk_flags"] == [
            "low_confidence", "no_exercise_regions", "book_pdf_prose_like",
        ]

    def test_p1b_batched_commit_and_expunge(self):
        """P1-B: 大批量题目应分批 commit + 精确 expunge，避免 ORM 对象
        在 session identity map 里累积导致 raw_data 长期驻留。
        隐患③：用 db.expunge(qi) 只剔除本批写入条目，不影响调用方持有的
        其他 ORM 实例。"""
        from app.features.review_service import _REVIEW_COMMIT_BATCH_SIZE

        db, added = self._setup()
        db.expunge = MagicMock()
        db.expunge_all = MagicMock()  # 断言不再被调用

        # 105 道题：50 + 50 + 5 → 应 commit 3 次，expunge 各条目共 105 次
        questions = [
            _make_question({"stem": f"题目 {i}", "stem_hash": f"h{i:04d}"})
            for i in range(105)
        ]

        result = asyncio.run(submit_to_review(db, questions))

        assert result["written"] == 105
        assert len(added) == 105

        # commit 次数 = ceil(105/50) = 3（两次满 batch + 一次尾部）
        expected_commits = -(-105 // _REVIEW_COMMIT_BATCH_SIZE)
        assert db.commit.call_count == expected_commits == 3
        # 每条 qi 都应被精确 expunge 一次（且只一次），共 105 次
        assert db.expunge.call_count == 105
        # 不应再使用 expunge_all（会误清调用方的其他 ORM 实例）
        db.expunge_all.assert_not_called()
        # 顺序：传入的 qi 应等于 added，确认按写入顺序剔除
        expunged_ids = [call.args[0].id for call in db.expunge.call_args_list]
        assert expunged_ids == [qi.id for qi in added]

    def test_p1b_exact_batch_size_no_extra_commit(self):
        """P1-B: 题目数恰好等于 batch_size 整数倍时，只 commit batch_size 次。"""
        from app.features.review_service import _REVIEW_COMMIT_BATCH_SIZE

        db, added = self._setup()
        db.expunge = MagicMock()
        db.expunge_all = MagicMock()

        questions = [_make_question({"stem": f"q{i}", "stem_hash": f"h{i:04d}"})
                     for i in range(_REVIEW_COMMIT_BATCH_SIZE)]

        result = asyncio.run(submit_to_review(db, questions))

        assert result["written"] == _REVIEW_COMMIT_BATCH_SIZE
        # 50 道题：满 batch commit 一次，尾部空 commit 一次保证事务关闭
        assert db.commit.call_count == 2
        # expunge 50 次（满 batch 的每条 qi 各一次）
        assert db.expunge.call_count == _REVIEW_COMMIT_BATCH_SIZE
        db.expunge_all.assert_not_called()

    def test_p1b_mid_batch_failure_cleans_orphan_batch(self):
        """隐患② 修复：第二批 commit 失败时，应 best-effort 按 batch_id
        清理已 commit 的孤儿记录，并把异常往上抛。"""
        db, added = self._setup()
        db.expunge = MagicMock()
        db.rollback = AsyncMock()

        # 第一次 commit 成功；第二次抛异常；第三次（清理 orphan 的 commit）
        # 必须能被 await（不是 side_effect 队列剩下的元素）
        commit_calls = {"count": 0}

        async def _commit_side_effect():
            commit_calls["count"] += 1
            if commit_calls["count"] == 2:
                raise RuntimeError("simulated DB failure mid-batch")

        db.commit = AsyncMock(side_effect=_commit_side_effect)

        # 105 道题：第一批 50 道 commit 成功后第二批触发失败
        questions = [
            _make_question({"stem": f"题目 {i}", "stem_hash": f"h{i:04d}"})
            for i in range(105)
        ]

        with pytest.raises(RuntimeError, match="simulated DB failure"):
            asyncio.run(submit_to_review(db, questions))

        # rollback 应被调用一次（清理失败事务）
        db.rollback.assert_awaited_once()
        # cleanup DELETE: db.execute 应被以 Delete 语句额外调一次
        # （之前已有 _batch_find_duplicate_questions / _batch_find_duplicate_imports
        # 的 select 调用，但都是空 hash 所以不触发；这里只断言 execute 至少
        # 被调用一次且最后一次是删除）
        from sqlalchemy.sql.dml import Delete
        delete_calls = [
            call for call in db.execute.call_args_list
            if call.args and isinstance(call.args[0], Delete)
        ]
        assert len(delete_calls) == 1
        # commit 累计 3 次：第一批成功 + 第二批抛错 + 清理后的 commit
        assert commit_calls["count"] == 3


# --- get_review_queue ---

class TestGetReviewQueue:
    def _make_qi(self, id, confidence=0.5, status="pending"):
        """构造一个 mock QuestionImport。"""
        qi = MagicMock()
        qi.id = id
        qi.batch_id = f"BATCH_{id}"
        qi.source_type = "pdf"
        qi.source_file = "test.pdf"
        qi.subject_id = 1
        qi.question_type = "single_choice"
        qi.parsed_content = {"text": f"stem_{id}"}
        qi.parsed_options = {"A": "opt"}
        qi.parsed_answer = "A"
        qi.parsed_analysis = "analysis"
        qi.status = status
        qi.ai_confidence = confidence
        qi.review_note = None
        qi.ai_metadata = {"errors": [], "warnings": []}
        qi.created_at = MagicMock()
        return qi

    def test_returns_items_sorted_by_confidence(self):
        db = _make_mock_db()
        qis = [
            self._make_qi(1, confidence=0.9),
            self._make_qi(2, confidence=0.3),
            self._make_qi(3, confidence=0.6),
        ]
        _mock_execute_sequence(db, {"scalar": 3}, {"scalars": qis})

        result = asyncio.run(get_review_queue(db))

        assert result["total"] == 3
        assert len(result["items"]) == 3
        assert result["page"] == 1
        assert result["page_size"] == 20

    def test_filter_by_status(self):
        db = _make_mock_db()
        qis = [self._make_qi(1, status="approved")]
        _mock_execute_sequence(db, {"scalar": 1}, {"scalars": qis})

        result = asyncio.run(get_review_queue(db, status="approved"))

        assert result["total"] == 1
        assert result["items"][0]["status"] == "approved"

    def test_filter_by_min_confidence(self):
        db = _make_mock_db()
        qis = [self._make_qi(1, confidence=0.8)]
        _mock_execute_sequence(db, {"scalar": 1}, {"scalars": qis})

        result = asyncio.run(get_review_queue(db, min_confidence=0.5))

        assert result["total"] == 1

    def test_pagination(self):
        db = _make_mock_db()
        qis = [self._make_qi(i) for i in range(1, 6)]
        _mock_execute_sequence(db, {"scalar": 5}, {"scalars": qis[:3]})

        result = asyncio.run(get_review_queue(db, page=1, page_size=3))

        assert result["total"] == 5
        assert result["page"] == 1
        assert result["page_size"] == 3
        assert len(result["items"]) == 3

    def test_empty_queue(self):
        db = _make_mock_db()
        _mock_execute_sequence(db, {"scalar": 0}, {"scalars": []})

        result = asyncio.run(get_review_queue(db))

        assert result["total"] == 0
        assert result["items"] == []

    def test_errors_from_ai_metadata(self):
        db = _make_mock_db()
        qi = self._make_qi(1)
        qi.ai_metadata = {"errors": ["stem_empty"], "warnings": ["low_confidence"]}
        _mock_execute_sequence(db, {"scalar": 1}, {"scalars": [qi]})

        result = asyncio.run(get_review_queue(db))

        assert result["items"][0]["errors"] == ["stem_empty"]
        assert result["items"][0]["warnings"] == ["low_confidence"]

    def test_non_dict_ai_metadata(self):
        db = _make_mock_db()
        qi = self._make_qi(1)
        qi.ai_metadata = "not_a_dict"
        _mock_execute_sequence(db, {"scalar": 1}, {"scalars": [qi]})

        result = asyncio.run(get_review_queue(db))

        assert result["items"][0]["errors"] == []
        assert result["items"][0]["warnings"] == []


# --- fix_question ---

class TestFixQuestion:
    def _make_qi_mock(self, status="pending"):
        qi = MagicMock()
        qi.id = 1
        qi.batch_id = "BATCH_1"
        qi.status = status
        qi.parsed_content = {"text": "old stem"}
        qi.parsed_options = {"A": "old"}
        qi.parsed_answer = "A"
        qi.parsed_analysis = "old analysis"
        return qi

    def test_fix_stem(self):
        db = _make_mock_db()
        qi = self._make_qi_mock()
        _mock_execute_sequence(db, {"scalar_one_or_none": qi})

        result = asyncio.run(fix_question(db, 1, {"stem": "new stem"}))

        assert result["id"] == 1
        assert result["status"] == "pending"
        assert result["updated_fields"] == ["stem"]
        assert qi.parsed_content == {"text": "new stem"}
        db.commit.assert_awaited_once()

    def test_fix_options(self):
        db = _make_mock_db()
        qi = self._make_qi_mock()
        _mock_execute_sequence(db, {"scalar_one_or_none": qi})

        result = asyncio.run(fix_question(db, 1, {"options": [{"key": "A", "text": "new opt"}]}))

        assert result["updated_fields"] == ["options"]
        assert qi.parsed_options == {"A": "new opt"}

    def test_fix_answer(self):
        db = _make_mock_db()
        qi = self._make_qi_mock()
        _mock_execute_sequence(db, {"scalar_one_or_none": qi})

        result = asyncio.run(fix_question(db, 1, {"answer": "B"}))

        assert result["updated_fields"] == ["answer"]
        assert qi.parsed_answer == "B"

    def test_fix_analysis(self):
        db = _make_mock_db()
        qi = self._make_qi_mock()
        _mock_execute_sequence(db, {"scalar_one_or_none": qi})

        result = asyncio.run(fix_question(db, 1, {"analysis": "new analysis"}))

        assert result["updated_fields"] == ["analysis"]
        assert qi.parsed_analysis == "new analysis"

    def test_fix_multiple_fields(self):
        db = _make_mock_db()
        qi = self._make_qi_mock()
        _mock_execute_sequence(db, {"scalar_one_or_none": qi})

        result = asyncio.run(fix_question(db, 1, {
            "stem": "new stem",
            "answer": "C",
            "analysis": "new analysis",
        }))

        assert set(result["updated_fields"]) == {"stem", "answer", "analysis"}
        assert qi.parsed_content == {"text": "new stem"}
        assert qi.parsed_answer == "C"
        assert qi.parsed_analysis == "new analysis"

    def test_empty_fixes(self):
        db = _make_mock_db()
        qi = self._make_qi_mock()
        _mock_execute_sequence(db, {"scalar_one_or_none": qi})

        result = asyncio.run(fix_question(db, 1, {}))

        assert result["updated_fields"] == []
        db.commit.assert_awaited_once()

    def test_not_found(self):
        db = _make_mock_db()
        _mock_execute_sequence(db, {"scalar_one_or_none": None})

        with pytest.raises(ValueError, match="导入记录不存在"):
            asyncio.run(fix_question(db, 999, {"stem": "x"}))

    def test_not_pending(self):
        db = _make_mock_db()
        qi = self._make_qi_mock(status="approved")
        _mock_execute_sequence(db, {"scalar_one_or_none": qi})

        with pytest.raises(ValueError, match="仅支持修改 pending 状态的记录"):
            asyncio.run(fix_question(db, 1, {"stem": "x"}))

    def test_fix_none_values(self):
        db = _make_mock_db()
        qi = self._make_qi_mock()
        _mock_execute_sequence(db, {"scalar_one_or_none": qi})

        result = asyncio.run(fix_question(db, 1, {
            "stem": None,
            "options": None,
            "answer": None,
            "analysis": None,
        }))

        assert result["updated_fields"] == []

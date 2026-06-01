"""Stage 7 审核系统 — 单元测试（mock DB session）。"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.features.review_service import (
    _options_to_dict,
    submit_to_review,
    get_review_queue,
    fix_question,
)


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
        "subject": "math2",
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
    db.execute = AsyncMock(return_value=_make_execute_result(scalar_one_or_none=None))
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
            {"source_type": "pdf", "source_file": "test.pdf", "subject": "math2"},
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

    def test_null_options(self):
        db, added = self._setup()
        q = _make_question({"options": None, "question_type": "fill_blank"})

        result = asyncio.run(submit_to_review(db, [q]))

        assert result["written"] == 1
        assert added[0].parsed_options is None

    def test_stem_preview_truncation(self):
        db, added = self._setup()
        long_stem = "A" * 60
        q = _make_question({"stem": long_stem})

        result = asyncio.run(submit_to_review(db, [q]))

        assert result["items"][0]["stem_preview"] == "A" * 50 + "..."


# --- get_review_queue ---

class TestGetReviewQueue:
    def _make_qi(self, id, confidence=0.5, status="pending"):
        """构造一个 mock QuestionImport。"""
        qi = MagicMock()
        qi.id = id
        qi.batch_id = f"BATCH_{id}"
        qi.source_type = "pdf"
        qi.source_file = "test.pdf"
        qi.subject = "math2"
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

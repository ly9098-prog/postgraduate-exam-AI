"""考试服务纯函数兼容基线。

覆盖 exam_service 中可脱离数据库独立测试的纯规则：
- _money：金额舍入
- _elapsed_seconds：耗时秒数计算
- _student_content：学生可见内容清洗
- _student_options：选项文本归一化
- _history_row_to_item：历史行投影
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from app.services.exam_service import (
    _elapsed_seconds,
    _history_row_to_item,
    _money,
    _student_content,
    _student_options,
)


class TestMoney:
    """_money 将任意值舍入到两位小数。"""

    def test_none_returns_zero(self) -> None:
        assert _money(None) == 0.0

    def test_integer(self) -> None:
        assert _money(5) == 5.0

    def test_rounds_two_decimals(self) -> None:
        assert _money(3.14159) == 3.14

    def test_string_numeric(self) -> None:
        assert _money("2.5") == 2.5

    def test_decimal(self) -> None:
        assert _money(Decimal("1.999")) == 2.0


class TestElapsedSeconds:
    """_elapsed_seconds 计算非负耗时秒数。"""

    def test_zero_when_same_time(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0)
        assert _elapsed_seconds(now, now) == 0

    def test_positive_difference(self) -> None:
        started = datetime(2026, 1, 1, 12, 0, 0)
        now = datetime(2026, 1, 1, 12, 0, 30)
        assert _elapsed_seconds(started, now) == 30

    def test_clamped_to_zero_when_negative(self) -> None:
        started = datetime(2026, 1, 1, 12, 0, 30)
        now = datetime(2026, 1, 1, 12, 0, 0)
        assert _elapsed_seconds(started, now) == 0

    def test_uses_utcnow_when_now_omitted(self) -> None:
        result = _elapsed_seconds(datetime(2020, 1, 1))
        assert isinstance(result, int)
        assert result >= 0


class TestStudentContent:
    """_student_content 清除内部字段并保留学生可见内容。"""

    def test_none_returns_empty_dict(self) -> None:
        assert _student_content(None) == {}

    def test_non_dict_returns_empty_dict(self) -> None:
        assert _student_content("string") == {}  # type: ignore[arg-type]
        assert _student_content(42) == {}  # type: ignore[arg-type]

    def test_strips_internal_keys(self) -> None:
        content = {
            "text": "题干",
            "source_snapshot_url": "https://example.com/snap.png",
            "source_snapshot_full_page": True,
            "visual_regions": [{"x": 1}],
            "visual_region_ids": [1, 2],
        }
        result = _student_content(content)
        assert "source_snapshot_url" not in result
        assert "source_snapshot_full_page" not in result
        assert "visual_regions" not in result
        assert "visual_region_ids" not in result
        assert result["text"] == "题干"

    def test_preserves_student_visible_keys(self) -> None:
        content = {"text": "题干", "segments": [{"type": "text", "content": "hello"}]}
        result = _student_content(content)
        assert result["text"] == "题干"
        assert "segments" in result


class TestStudentOptions:
    """_student_options 归一化选项文本换行和空白。"""

    def test_none_returns_empty_dict(self) -> None:
        assert _student_options(None) == {}

    def test_non_dict_returns_empty_dict(self) -> None:
        assert _student_options("string") == {}  # type: ignore[arg-type]

    def test_dict_value_with_text_normalizes_newlines(self) -> None:
        options = {"A": {"text": "line1\r\nline2  extra"}}
        result = _student_options(options)
        assert result["A"]["text"] == "line1  line2  extra"

    def test_dict_value_with_value_key(self) -> None:
        options = {"A": {"value": "raw\rvalue"}}
        result = _student_options(options)
        assert result["A"]["text"] == "raw value"

    def test_string_value_normalizes(self) -> None:
        options = {"A": "text\r\nwith  spaces"}
        result = _student_options(options)
        assert result["A"] == "text  with  spaces"

    def test_non_string_non_dict_value_preserved(self) -> None:
        options = {"A": 42, "B": True}
        result = _student_options(options)
        assert result["A"] == 42
        assert result["B"] is True

    def test_empty_dict(self) -> None:
        assert _student_options({}) == {}


class TestHistoryRowToItem:
    """_history_row_to_item 将历史行投影为前端展示字典。"""

    def _make_row(
        self,
        *,
        attempt_id: int = 1,
        paper_id: int = 10,
        paper_title: str | None = "测试卷",
        paper_type: str | None = "mock_choice",
        year: int | None = 2026,
        status: str = "submitted",
        started_at: datetime | None = None,
        submitted_at: datetime | None = None,
        duration_sec: int = 600,
        question_count: int = 10,
        answered_count: int = 8,
        correct_count: int = 6,
        choice_score: float = 12.0,
        total_choice_score: float = 20.0,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            attempt_id=attempt_id,
            paper_id=paper_id,
            paper_title=paper_title,
            paper_type=paper_type,
            year=year,
            status=status,
            started_at=started_at,
            submitted_at=submitted_at,
            duration_sec=duration_sec,
            question_count=question_count,
            answered_count=answered_count,
            correct_count=correct_count,
            choice_score=choice_score,
            total_choice_score=total_choice_score,
        )

    def test_basic_projection(self) -> None:
        row = self._make_row()
        item = _history_row_to_item(row)
        assert item["attempt_id"] == 1
        assert item["paper_id"] == 10
        assert item["paper_title"] == "测试卷"
        assert item["question_count"] == 10
        assert item["answered_count"] == 8
        assert item["correct_count"] == 6
        assert item["wrong_count"] == 2
        assert item["unanswered_count"] == 2
        assert item["accuracy"] == 0.6

    def test_zero_question_count_accuracy_zero(self) -> None:
        row = self._make_row(question_count=0, answered_count=0, correct_count=0)
        item = _history_row_to_item(row)
        assert item["accuracy"] == 0.0
        assert item["question_count"] == 0

    def test_none_paper_title_falls_back(self) -> None:
        row = self._make_row(paper_title=None, paper_id=42)
        item = _history_row_to_item(row)
        assert item["paper_title"] == "试卷 #42"

    def test_none_paper_type_falls_back(self) -> None:
        row = self._make_row(paper_type=None)
        item = _history_row_to_item(row)
        assert item["paper_type"] == "mock_choice"

    def test_correct_clamped_to_answered(self) -> None:
        row = self._make_row(answered_count=5, correct_count=10)
        item = _history_row_to_item(row)
        assert item["correct_count"] == 5

    def test_answered_clamped_to_question_count(self) -> None:
        row = self._make_row(question_count=5, answered_count=10)
        item = _history_row_to_item(row)
        assert item["answered_count"] == 5

    def test_money_rounding(self) -> None:
        row = self._make_row(choice_score=12.345, total_choice_score=20.678)
        item = _history_row_to_item(row)
        assert item["choice_score"] == 12.35
        assert item["total_choice_score"] == 20.68

    def test_negative_counts_clamped_to_zero(self) -> None:
        row = self._make_row(
            question_count=-1, answered_count=-1, correct_count=-1, duration_sec=-1
        )
        item = _history_row_to_item(row)
        assert item["question_count"] == 0
        assert item["answered_count"] == 0
        assert item["correct_count"] == 0
        # duration_sec uses int(x or 0), so -1 passes through
        assert item["duration_sec"] == -1

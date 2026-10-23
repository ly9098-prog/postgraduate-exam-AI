"""Tests for similarity matcher."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.features.global_hash_index import GlobalHashIndex
from app.features.similarity_matcher import (
    _compute_similarity,
    _find_best_match,
    match_similar_questions,
)

# ---------------------------------------------------------------------------
# Similarity computation tests
# ---------------------------------------------------------------------------


class TestComputeSimilarity:
    def test_identical_strings(self):
        assert _compute_similarity("hello world", "hello world") == 1.0

    def test_identical_with_whitespace_diff(self):
        assert _compute_similarity("hello world", "hello  world") == 1.0

    def test_similar_strings(self):
        ratio = _compute_similarity(
            "下列关于数据结构的说法正确的是",
            "下列关于数据结构的说法正确的是哪个",
        )
        assert ratio > 0.85

    def test_different_strings(self):
        ratio = _compute_similarity(
            "下列关于数据结构的说法正确的是",
            "操作系统中进程调度的基本单位是",
        )
        assert ratio < 0.5

    def test_empty_string(self):
        assert _compute_similarity("", "hello") == 0.0
        assert _compute_similarity("hello", "") == 0.0

    def test_none_handling(self):
        assert _compute_similarity(None, "hello") == 0.0


# ---------------------------------------------------------------------------
# Best match tests
# ---------------------------------------------------------------------------


class TestFindBestMatch:
    def _make_bank(self):
        return [
            {"id": 1, "stem": "下列关于数据结构的说法正确的是", "options": {"A": "集合", "B": "关系"}, "answer": "C"},
            {"id": 2, "stem": "操作系统中进程调度的基本单位是", "options": {"A": "进程", "B": "线程"}, "answer": "B"},
            {"id": 3, "stem": "TCP协议的三次握手过程中第二次握手的标志位是", "options": {"A": "SYN", "B": "ACK"}, "answer": "A"},
        ]

    def test_exact_match(self):
        bank = self._make_bank()
        result = _find_best_match("下列关于数据结构的说法正确的是", bank, 0.85)
        assert result is not None
        assert result["matched_question_id"] == 1
        assert result["similarity_ratio"] == 1.0

    def test_similar_match_above_threshold(self):
        bank = self._make_bank()
        # OCR garbled version
        result = _find_best_match("下列关于数据结枃的说法正确的是", bank, 0.85)
        assert result is not None
        assert result["matched_question_id"] == 1
        assert result["similarity_ratio"] >= 0.85

    def test_no_match_below_threshold(self):
        bank = self._make_bank()
        result = _find_best_match("这是一道完全不同的题目", bank, 0.85)
        assert result is None

    def test_empty_bank(self):
        result = _find_best_match("任意题目", [], 0.85)
        assert result is None

    def test_suggestion_format(self):
        bank = self._make_bank()
        result = _find_best_match("下列关于数据结构的说法正确的是", bank, 0.85)
        assert result["source"] == "question_bank"
        assert "suggested_stem" in result
        assert "suggested_options" in result
        assert "suggested_answer" in result


# ---------------------------------------------------------------------------
# Integration tests (mocked DB)
# ---------------------------------------------------------------------------


class TestMatchSimilarQuestions:
    @pytest.mark.asyncio
    async def test_disabled_skips_all(self):
        questions = [{"stem": "test", "subject": "math2"}]
        result = await match_similar_questions(questions, db=None, config={"enabled": False})
        assert result["skipped_reason"] == "disabled"
        assert result["stats"]["matched_count"] == 0

    @pytest.mark.asyncio
    async def test_no_db_skips(self):
        questions = [{"stem": "test", "subject": "math2"}]
        result = await match_similar_questions(questions, db=None, config={"enabled": True})
        assert result["skipped_reason"] == "no_db_session"

    @pytest.mark.asyncio
    async def test_match_found(self):
        questions = [{
            "stem": "下列关于数据结构的说法正确的是",
            "subject": "exam408",
        }]

        bank = [{
            "id": 42,
            "stem": "下列关于数据结构的说法正确的是",
            "options": {"A": "集合", "B": "关系", "C": "两者", "D": "都不对"},
            "answer": "C",
        }]

        mock_db = AsyncMock()

        with patch(
            "app.features.similarity_matcher._load_subject_questions",
            new_callable=AsyncMock,
            return_value=bank,
        ):
            result = await match_similar_questions(questions, db=mock_db, config={
                "enabled": True,
                "similarity_threshold": 0.85,
            })

        assert result["stats"]["matched_count"] == 1
        assert result["questions"][0]["similarity_suggestion"]["matched_question_id"] == 42
        assert result["questions"][0]["similarity_suggestion"]["similarity_ratio"] == 1.0

    @pytest.mark.asyncio
    async def test_no_match_when_different(self):
        questions = [{
            "stem": "这是一道完全不同的题目关于物理学",
            "subject": "exam408",
        }]

        mock_row = MagicMock()
        mock_row.id = 10
        mock_row.content = {"text": "操作系统中进程的基本状态有哪些"}
        mock_row.options = {"A": "就绪", "B": "运行"}
        mock_row.answer = "A"

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await match_similar_questions(questions, db=mock_db, config={
            "enabled": True,
            "similarity_threshold": 0.85,
        })

        assert result["stats"]["matched_count"] == 0
        assert "similarity_suggestion" not in result["questions"][0]

    @pytest.mark.asyncio
    async def test_empty_subject_skips_question(self):
        questions = [{"stem": "some stem", "subject": ""}]

        mock_db = AsyncMock()
        result = await match_similar_questions(questions, db=mock_db, config={"enabled": True})
        assert result["stats"]["matched_count"] == 0
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_bank_no_error(self):
        questions = [{"stem": "任意题目", "subject": "math2"}]

        mock_result = MagicMock()
        mock_result.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await match_similar_questions(questions, db=mock_db, config={"enabled": True})
        assert result["stats"]["matched_count"] == 0

    @pytest.mark.asyncio
    async def test_subject_cache_reused(self):
        """Same subject resolves once and scans the bank only once."""
        questions = [
            {"stem": "题目一", "subject": "math2"},
            {"stem": "题目二", "subject": "math2"},
        ]

        mock_result = MagicMock()
        mock_result.all.return_value = []

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        await match_similar_questions(questions, db=mock_db, config={"enabled": True})
        assert mock_db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_ocr_garbled_matches_original(self):
        """OCR garbled text should still match the original."""
        questions = [{
            "stem": "下列关于数据结枃的说法正碓的是",  # 结枃=结构, 正碓=正确
            "subject": "exam408",
        }]

        bank = [{
            "id": 99,
            "stem": "下列关于数据结构的说法正确的是",
            "options": {"A": "a", "B": "b"},
            "answer": "A",
        }]

        mock_db = AsyncMock()

        with patch(
            "app.features.similarity_matcher._load_subject_questions",
            new_callable=AsyncMock,
            return_value=bank,
        ):
            result = await match_similar_questions(questions, db=mock_db, config={
                "enabled": True,
                "similarity_threshold": 0.85,
            })

        assert result["stats"]["matched_count"] == 1
        suggestion = result["questions"][0]["similarity_suggestion"]
        assert suggestion["matched_question_id"] == 99
        assert suggestion["similarity_ratio"] >= 0.85


# ---------------------------------------------------------------------------
# P2-4: GlobalHashIndex injection — hash 命中走严格匹配，跳过 difflib 扫描
# ---------------------------------------------------------------------------


class TestHashIndexInjection:
    """注入 hash_index 后：命中即 ratio=1.0 强匹配；miss 走 SQL 兜底（不再扫 subject 全表）。"""

    @pytest.mark.asyncio
    async def test_hash_hit_runs_only_payload_query(self):
        questions = [{
            "stem": "题目原文一致",
            "subject": "exam408",
            "options": [{"key": "A", "text": "a"}, {"key": "B", "text": "b"}],
            "answer": "A",
        }]

        # 注入 stub index：lookup_question 直接命中 question_id=42
        index = GlobalHashIndex()
        index._loaded = True  # 跳过 load
        index.lookup_question = AsyncMock(return_value=42)

        # _load_question_payload 会跑一条 SQL 拿题目展示字段
        mock_row = MagicMock()
        mock_row.__iter__ = lambda self: iter((
            {"text": "题目原文一致"},  # content
            {"A": "a"},                # options
            "A",                       # answer
        ))
        # SQLAlchemy Row 支持 unpacking (content, options, answer) = row
        mock_payload_row = ({"text": "题目原文一致"}, {"A": "a"}, "A")

        mock_payload_result = MagicMock()
        mock_payload_result.first.return_value = mock_payload_row

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_payload_result)

        result = await match_similar_questions(
            questions,
            db=mock_db,
            config={"enabled": True, "similarity_threshold": 0.85},
            hash_index=index,
        )

        # hash 命中
        assert result["stats"]["hash_hit_count"] == 1
        assert result["stats"]["matched_count"] == 1
        suggestion = result["questions"][0]["similarity_suggestion"]
        assert suggestion["matched_question_id"] == 42
        assert suggestion["similarity_ratio"] == 1.0
        assert suggestion["source"] == "question_bank_hash"

        # 没扫 subject 全表（_load_subject_questions 不应调用）
        assert mock_db.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_hash_miss_falls_back_to_nothing_when_index_present(self):
        """注入 index 但 hash miss 时不再做 difflib fallback（避免每 chunk 重扫题库）。"""
        questions = [{
            "stem": "miss 的题",
            "subject": "exam408",
            "options": [{"key": "A", "text": "a"}],
            "answer": "A",
        }]

        index = GlobalHashIndex()
        index._loaded = True
        index.lookup_question = AsyncMock(return_value=None)  # miss

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()

        result = await match_similar_questions(
            questions,
            db=mock_db,
            config={"enabled": True, "similarity_threshold": 0.85},
            hash_index=index,
        )

        assert result["stats"]["hash_hit_count"] == 0
        assert result["stats"]["matched_count"] == 0
        # 不再做 subject 全表加载（_load_subject_questions 应未被调用）
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_legacy_difflib_path_still_works_without_index(self):
        """没注入 index 时仍跑旧的 subject 全表 difflib（行为零变化）。"""
        questions = [{
            "stem": "OCR 题干内容大致相同",
            "subject": "exam408",
        }]

        bank = [{
            "id": 7,
            "stem": "OCR 题干内容大致相同",
            "options": {"A": "x"},
            "answer": "A",
        }]

        mock_db = AsyncMock()

        with patch(
            "app.features.similarity_matcher._load_subject_questions",
            new_callable=AsyncMock,
            return_value=bank,
        ):
            result = await match_similar_questions(
                questions,
                db=mock_db,
                config={"enabled": True, "similarity_threshold": 0.85},
                hash_index=None,
            )

        assert result["stats"]["hash_hit_count"] == 0
        assert result["stats"]["matched_count"] == 1
        assert result["questions"][0]["similarity_suggestion"]["source"] == "question_bank"

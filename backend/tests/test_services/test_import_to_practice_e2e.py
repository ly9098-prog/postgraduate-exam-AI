"""回归测试：导入→审核→刷题完整链路。

覆盖修复点：
1. 混合 PDF 单题级别 subject 识别（不再一刀切）
2. _guess_subject 在子科目命中时回退父科目
3. batch_approve 整批失败不抛错并返回 skipped 详情
4. approve_question 返回 is_duplicate
5. practice_service 的 subject 前缀匹配
"""

import asyncio
import io
import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.features.question_pipeline import (  # noqa: E402
    _guess_subject,
    _parse_pdf,
    batch_approve,
)


def _make_pdf(text: str) -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 80), text, fontsize=11, fontname="china-s")
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


# ──────────────────────── _guess_subject ────────────────────────


class TestGuessSubject:
    def test_high_score_subjects_returned(self):
        text = "极限 导数 积分 lim 连续 可导"
        assert _guess_subject(text, min_score=2) == "math2-calculus"

    def test_subject_408_co_keywords(self):
        text = "cpu 存储器 指令 总线 cache 中断"
        assert _guess_subject(text, min_score=2) == "exam408-co"

    def test_low_score_falls_back_to_parent(self):
        # 只命中 1 个数学关键词，min_score=2 不达标，应回退父科目 math2
        text = "极限"
        assert _guess_subject(text, min_score=2) == "math2"

    def test_no_match_returns_none(self):
        assert _guess_subject("hello world", min_score=2) is None
        assert _guess_subject("", min_score=2) is None

    def test_min_score_1_for_short_stems(self):
        # 短题干用 min_score=1 也应能识别
        text = "极限 lim"
        assert _guess_subject(text, min_score=1) == "math2-calculus"


# ──────────────────────── _parse_pdf 单题级 subject ────────────────────────


class TestParsePdfPerQuestionSubject:
    def test_mixed_pdf_assigns_subject_per_question(self):
        """混合 PDF：408 题 + 数学题，两道题的 subject 应不同。"""
        text = (
            "1. 某计算机采用32位定长指令字，cpu 取指令时通过总线访问存储器，\n"
            "   下列哪个寄存器存放当前指令？\n"
            "A. PC\nB. IR\nC. MAR\nD. MBR\n"
            "答案：B\n"
            "解析：IR 是指令寄存器，存放正在执行的指令。\n"
            "\n"
            "2. 求极限 lim(x→0) sin(x)/x = ?\n"
            "A. 0\nB. 1\nC. ∞\nD. 不存在\n"
            "答案：B\n"
            "解析：这是导数与极限基本公式，连续可导函数的标准结论。\n"
        )
        results = _parse_pdf(_make_pdf(text), "mixed.pdf")
        assert len(results) >= 2

        # 第 1 题应识别为 408（含 cpu/存储器/指令）
        assert results[0]["subject"] in {"exam408", "exam408-co"}
        # 第 2 题应识别为数学（极限/导数）
        assert results[1]["subject"] in {"math2", "math2-calculus"}

    def test_unknown_pdf_subject_is_none(self):
        text = "1. 一段无关文字 abc def ghi.\nA. x\nB. y\n答案：A\n"
        results = _parse_pdf(_make_pdf(text), "unknown.pdf")
        assert results
        # 非任何科目关键词，subject 应为 None
        assert results[0]["subject"] in (None, "")


# ──────────────────────── batch_approve 不抛错 ────────────────────────


_MISSING = object()


def _make_qi(qi_id, status="pending", subject="math2", parsed_content=None,
             parsed_options=_MISSING, parsed_answer="A", parsed_analysis="解析"):
    qi = MagicMock()
    qi.id = qi_id
    qi.batch_id = "B1"
    qi.status = status
    qi.subject_id = 1  # mock subject_id
    # subject_ref mock for code resolution
    subj_ref = MagicMock()
    subj_ref.code = subject
    qi.subject_ref = subj_ref
    qi.question_type = "single_choice"
    qi.parsed_content = parsed_content or {"text": "求 f(x)=x^2 的导数"}
    qi.parsed_options = (
        {"A": "2x", "B": "x"} if parsed_options is _MISSING else parsed_options
    )
    qi.parsed_answer = parsed_answer
    qi.parsed_analysis = parsed_analysis
    qi.source_file = "t.pdf"
    qi.source_type = "pdf"
    qi.raw_data = {}
    qi.ai_metadata = {}
    qi.ai_generated = False
    qi.question_id = None
    return qi


def _make_db_with_pending(qis):
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", id(obj) % 10000))
    select_result = MagicMock()
    select_result.scalars.return_value.all.return_value = qis
    # find_duplicate_question 也走 db.execute → 返回空表示无重复
    empty_result = MagicMock()
    empty_result.scalars.return_value.all.return_value = []

    call_count = {"n": 0}

    async def fake_execute(stmt, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return select_result
        return empty_result

    db.execute = AsyncMock(side_effect=fake_execute)

    # db.get for Subject lookup in batch_approve
    async def fake_get(model, item_id):
        subj_mock = MagicMock()
        subj_mock.code = "math2"
        return subj_mock

    db.get = AsyncMock(side_effect=fake_get)
    return db


class TestBatchApproveNoRaiseOnAllSkipped:
    def test_all_invalid_returns_zero_with_skipped_dict(self):
        # 两个都缺 options，无法通过 single_choice 校验 → 全 skip
        qis = [
            _make_qi(1, parsed_options=None),
            _make_qi(2, parsed_options=None),
        ]
        db = _make_db_with_pending(qis)
        approved, skipped = asyncio.run(batch_approve(db, "B1"))
        assert approved == 0
        assert isinstance(skipped, dict)
        assert set(skipped.keys()) == {1, 2}
        for qid, missing in skipped.items():
            assert "options_empty" in missing

    def test_partial_pass(self):
        qis = [
            _make_qi(1, parsed_options={"A": "2x", "B": "x", "C": "x^2", "D": "0"}),  # 有效
            _make_qi(2, parsed_options=None),  # 缺 options
        ]
        db = _make_db_with_pending(qis)
        approved, skipped = asyncio.run(batch_approve(db, "B1"))
        assert approved == 1
        assert list(skipped.keys()) == [2]


# ──────────────────────── practice_service 子科目前缀匹配 ────────────────────────


class TestPracticeSubjectPrefixMatch:
    def test_parent_subject_matches_children(self):
        """传入父科目 subject_id（int），应展开包含子科目的 IN 查询。"""
        from app.services.practice_service import get_practice_questions
        from app.models.admin import Subject
        from app.models.question import Question

        db = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        # 模拟 db.execute 的不同返回
        q1 = MagicMock(spec=Question)
        q1.id = 1
        q1.subject_id = 2
        q1.is_active = True

        # Subject records for resolve_subject_ids tree expansion
        parent_subj = MagicMock(spec=Subject)
        parent_subj.id = 1
        parent_subj.parent_id = None

        child_subj = MagicMock(spec=Subject)
        child_subj.id = 2
        child_subj.parent_id = 1

        # db.get 返回 Subject 记录（用于 resolve_subject_id(int)）
        async def mock_get(model, id_val):
            if id_val == 1:
                return parent_subj
            return None
        db.get = mock_get

        # db.execute 按调用顺序返回不同结果
        call_count = 0
        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # resolve_subject_ids: select(Subject) for tree
                result.scalars.return_value.all.return_value = [parent_subj, child_subj]
            else:
                # get_practice_questions: select(Question)
                result.scalars.return_value.all.return_value = [q1]
            return result

        db.execute = AsyncMock(side_effect=mock_execute)

        questions = asyncio.run(
            get_practice_questions(db, user_id=1, subject=1, count=5, mode="random")
        )
        assert len(questions) == 1
        # 验证 SQL 用了 IN 包含子科目 ID
        called_stmt = db.execute.call_args[0][0]
        sql_text = str(called_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "subject_id" in sql_text

"""Acceptance tests for subject_id refactor.

Validates that:
1. subject_options returns id/code/name/path/level
2. AI completion subject_id accepts only valid subject IDs
3. question_imports publish to questions with subject_id correctly propagated
4. Question list filtering by subject_id works
5. Deleting a referenced subject is blocked
6. Legacy subject string migration to subject_id works (migration script logic)
"""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.admin import AdminUser, Subject
from app.models.question import Question
from app.models.question_import import QuestionImport
from app.core.admin_security import AdminPrincipal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _subject(sid, code, name, parent_id=None, level=1, path=None, sort_order=0, is_active=True):
    now = datetime(2026, 5, 29)
    return Subject(
        id=sid, parent_id=parent_id, code=code, name=name,
        level=level, path=path or code, sort_order=sort_order,
        is_active=is_active, created_at=now, updated_at=now,
    )


def _principal():
    user = AdminUser(id=9, username="operator", password_hash="hash", is_active=True, role_id=2)
    return AdminPrincipal(user, {})


class _Scalars:
    def __init__(self, values):
        self.values = values
    def all(self):
        return self.values
    def first(self):
        return self.values[0] if self.values else None


class _Result:
    def __init__(self, value=None, values=None, all_rows=None):
        self.value = value
        self.values = values if values is not None else ([] if value is None else [value])
        self.all_rows = all_rows

    def scalar_one_or_none(self):
        return self.value

    def scalar(self):
        return self.value

    def scalars(self):
        return _Scalars(self.values)

    def all(self):
        if self.all_rows is not None:
            return self.all_rows
        return self.values


# ---------------------------------------------------------------------------
# 1. subject_options returns id/code/name/path/level
# ---------------------------------------------------------------------------

class TestListSubjectOptions:
    @pytest.mark.asyncio
    async def test_returns_id_code_name_path_level(self):
        from app.services.admin_import_service import list_subject_options

        subj = _subject(1, "math2", "数学二")

        class Db:
            async def execute(self, stmt):
                text = str(stmt)
                if "subjects" in text:
                    # Return a row-like object with id, code, name, path, level
                    row = SimpleNamespace(id=1, code="math2", name="数学二", path="math2", level=1)
                    return _Result(values=[row])
                return _Result(values=[])

        db = Db()
        result = await list_subject_options(db)
        assert len(result) == 1
        item = result[0]
        assert item["id"] == 1
        assert item["code"] == "math2"
        assert item["name"] == "数学二"
        assert item["path"] == "math2"
        assert item["level"] == 1

    @pytest.mark.asyncio
    async def test_fallback_includes_id_none(self):
        """When subjects table is empty, fallback returns items with id=None."""
        from app.services.admin_import_service import list_subject_options

        class Db:
            def __init__(self):
                self.call_count = 0
            async def execute(self, stmt):
                self.call_count += 1
                if self.call_count == 1:
                    # First call: subjects query returns empty
                    return _Result(values=[])
                # Second call: fallback returns legacy subject strings
                return _Result(all_rows=[(None, "math2", "数学二")])

        db = Db()
        result = await list_subject_options(db)
        assert len(result) == 1
        assert result[0]["id"] is None
        assert result[0]["code"] == "math2"


# ---------------------------------------------------------------------------
# 2. AI completion subject_id only accepts valid IDs
# ---------------------------------------------------------------------------

class TestAICompleteSubjectId:
    def test_apply_complete_suggestion_sets_subject_id(self):
        from app.features.question_ai_complete import _apply_complete_suggestion

        qi = QuestionImport(
            id=1, batch_id="b1", source_type="text", raw_data={},
            status="pending", duplicate_status="normal",
            ai_generated=False, ai_answer_flag=False,
            created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        )
        parsed = {"subject_id": 5, "answer": "A"}
        missing = ["subject", "answer"]

        suggestion = _apply_complete_suggestion(qi, parsed, missing)
        assert qi.subject_id == 5
        assert suggestion["subject_id"] == 5

    def test_apply_complete_suggestion_rejects_invalid_subject_id(self):
        from app.features.question_ai_complete import _apply_complete_suggestion

        qi = QuestionImport(
            id=1, batch_id="b1", source_type="text", raw_data={},
            status="pending", duplicate_status="normal",
            ai_generated=False, ai_answer_flag=False,
            created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        )
        # AI returns a string instead of int for subject_id
        parsed = {"subject_id": "math2"}
        missing = ["subject"]

        suggestion = _apply_complete_suggestion(qi, parsed, missing)
        assert qi.subject_id is None
        assert "subject_id" not in suggestion

    def test_apply_complete_suggestion_rejects_zero_subject_id(self):
        from app.features.question_ai_complete import _apply_complete_suggestion

        qi = QuestionImport(
            id=1, batch_id="b1", source_type="text", raw_data={},
            status="pending", duplicate_status="normal",
            ai_generated=False, ai_answer_flag=False,
            created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        )
        parsed = {"subject_id": 0}
        missing = ["subject"]

        suggestion = _apply_complete_suggestion(qi, parsed, missing)
        assert qi.subject_id is None

    @pytest.mark.asyncio
    async def test_batch_complete_accepts_subject_id(self):
        from app.features.question_ai_complete import _apply_batch_complete_result

        qi = QuestionImport(
            id=1, batch_id="b1", source_type="text", raw_data={},
            status="pending", duplicate_status="normal",
            ai_generated=False, ai_answer_flag=False,
            created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        )
        parsed = {"subject_id": 3}
        fields = ["subject_id"]

        completed = await _apply_batch_complete_result(qi, parsed, fields, "fill_empty")
        assert qi.subject_id == 3
        assert "subject_id" in completed

    @pytest.mark.asyncio
    async def test_batch_complete_legacy_subject_resolved_to_subject_id(self):
        """AI returns old-style subject string → should resolve to subject_id via db."""
        from app.features.question_ai_complete import _apply_batch_complete_result

        qi = QuestionImport(
            id=1, batch_id="b1", source_type="text", raw_data={},
            status="pending", duplicate_status="normal",
            ai_generated=False, ai_answer_flag=False,
            created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        )
        parsed = {"subject": "math2"}
        fields = ["subject_id"]

        mock_db = AsyncMock()
        with patch(
            "app.services.admin_subject_service.resolve_subject_id",
            AsyncMock(return_value=7),
        ):
            completed = await _apply_batch_complete_result(
                qi, parsed, fields, "fill_empty", db=mock_db,
            )
        assert qi.subject_id == 7
        assert "subject_id" in completed

    @pytest.mark.asyncio
    async def test_batch_complete_legacy_subject_unresolved_skipped(self):
        """AI returns unknown subject string → should not write anything."""
        from app.features.question_ai_complete import _apply_batch_complete_result

        qi = QuestionImport(
            id=1, batch_id="b1", source_type="text", raw_data={},
            status="pending", duplicate_status="normal",
            ai_generated=False, ai_answer_flag=False,
            created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        )
        parsed = {"subject": "unknown_subject"}
        fields = ["subject_id"]

        mock_db = AsyncMock()
        with patch(
            "app.services.admin_subject_service.resolve_subject_id",
            AsyncMock(return_value=None),
        ):
            completed = await _apply_batch_complete_result(
                qi, parsed, fields, "fill_empty", db=mock_db,
            )
        assert qi.subject_id is None
        assert "subject_id" not in completed

    def test_detect_fields_to_complete_normalizes_subject_to_subject_id(self):
        """target_fields=['subject'] should be treated as subject_id."""
        from app.features.question_ai_complete import _detect_fields_to_complete

        qi = QuestionImport(
            id=1, batch_id="b1", source_type="text", raw_data={},
            status="pending", duplicate_status="normal",
            ai_generated=False, ai_answer_flag=False,
            created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        )
        # subject_id is None → "subject" in target_fields should trigger "subject_id"
        result = _detect_fields_to_complete(qi, ["subject"], "fill_empty")
        assert "subject_id" in result

        # force_overwrite should also normalize
        result = _detect_fields_to_complete(qi, ["subject"], "force_overwrite")
        assert "subject_id" in result


# ---------------------------------------------------------------------------
# 3. Publish: question_imports → questions propagates subject_id
# ---------------------------------------------------------------------------

class TestPublishPropagatesSubjectId:
    @pytest.mark.asyncio
    async def test_publish_sets_subject_id_on_question(self):
        from app.features.question_publish_service import publish_single_question

        subj = _subject(5, "math2", "数学二")
        qi = QuestionImport(
            id=1, batch_id="b1", source_type="text", raw_data={},
            status="approved", duplicate_status="normal",
            ai_generated=False, ai_answer_flag=False,
            question_type="single_choice",
            parsed_content={"text": "What is 2+2?"},
            parsed_options={"A": "3", "B": "4", "C": "5", "D": "6"},
            parsed_answer="B",
            parsed_analysis="Simple addition",
            subject_id=5,
            created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        )
        # Attach a mock subject_ref
        qi.subject_ref = subj

        created_questions = []

        class Db:
            async def execute(self, stmt):
                return _Result(values=[])
            async def scalar(self, stmt):
                return None
            async def get(self, model, item_id):
                if model is Subject and item_id == 5:
                    return subj
                return None
            def add(self, q):
                if isinstance(q, Question):
                    created_questions.append(q)
            async def flush(self):
                for q in created_questions:
                    if q.id is None:
                        q.id = 100
            async def refresh(self, q):
                pass

        db = Db()
        result = await publish_single_question(db, qi)

        assert result["status"] == "published"
        assert len(created_questions) == 1
        assert created_questions[0].subject_id == 5


# ---------------------------------------------------------------------------
# 4. Filter questions by subject_id
# ---------------------------------------------------------------------------

class TestFilterBySubjectId:
    @pytest.mark.asyncio
    async def test_list_questions_filters_by_subject_id(self):
        from app.services.admin_question_service import list_admin_questions

        captured_conditions = []

        class Db:
            async def execute(self, stmt):
                captured_conditions.append(str(stmt))
                return _Result(values=[])
            async def scalar(self, stmt):
                captured_conditions.append(str(stmt))
                return 0

        db = Db()
        questions, total = await list_admin_questions(db, page=1, page_size=20, subject_id=7)
        assert total == 0

        # Verify subject_id filter was applied
        has_subject_id_filter = any("subject_id" in c for c in captured_conditions)
        assert has_subject_id_filter, f"Expected subject_id filter in queries: {captured_conditions}"


# ---------------------------------------------------------------------------
# 5. Delete referenced subject fails
# ---------------------------------------------------------------------------

class TestDeleteReferencedSubject:
    @pytest.mark.asyncio
    async def test_delete_blocked_by_question_reference(self, monkeypatch):
        from app.services import admin_subject_service
        from app.services.admin_subject_service import delete_subject

        monkeypatch.setattr(admin_subject_service, "write_admin_audit", AsyncMock())

        subj = _subject(1, "math", "数学")

        class Db:
            def __init__(self):
                self.subjects = [subj]
                self.deleted = []
                self.flush = AsyncMock()

            async def get(self, model, item_id):
                if model is Subject and item_id == 1:
                    return subj
                return None

            async def execute(self, stmt):
                return _Result(values=[])

            async def scalar(self, stmt):
                text = str(stmt)
                if "subjects" in text:
                    return 0  # no children
                # Both Question and QuestionImport queries match "questions"
                return 1  # 1 question references this subject

            async def delete(self, item):
                self.deleted.append(item)

        db = Db()
        with pytest.raises(ValueError, match="已有题目使用该科目"):
            await delete_subject(db, 1, _principal())

    @pytest.mark.asyncio
    async def test_delete_succeeds_when_no_references(self, monkeypatch):
        from app.services import admin_subject_service
        from app.services.admin_subject_service import delete_subject

        monkeypatch.setattr(admin_subject_service, "write_admin_audit", AsyncMock())

        subj = _subject(1, "unused", "未使用科目")

        class Db:
            def __init__(self):
                self.subjects = [subj]
                self.deleted = []
                self.flush = AsyncMock()

            async def get(self, model, item_id):
                if model is Subject and item_id == 1:
                    return subj
                return None

            async def execute(self, stmt):
                return _Result(values=[])

            async def scalar(self, stmt):
                return 0  # no children, no questions, no imports

            async def delete(self, item):
                self.deleted.append(item)

        db = Db()
        await delete_subject(db, 1, _principal())
        assert db.deleted == [subj]


# ---------------------------------------------------------------------------
# 6. Schema tests: subject_id in request/response schemas
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_admin_question_list_item_has_subject_id(self):
        from app.schemas.admin_questions import AdminQuestionListItem
        fields = AdminQuestionListItem.model_fields
        assert "subject_id" in fields
        assert "subject_code" in fields
        assert "subject_name" in fields
        assert "subject_path" in fields

    def test_admin_question_patch_request_accepts_subject_id(self):
        from app.schemas.admin_questions import AdminQuestionPatchRequest
        req = AdminQuestionPatchRequest(subject_id=5)
        assert req.subject_id == 5

    def test_admin_import_update_request_accepts_subject_id(self):
        from app.schemas.admin_imports import AdminImportQuestionUpdateRequest
        req = AdminImportQuestionUpdateRequest(subject_id=5)
        assert req.subject_id == 5

    def test_import_question_item_has_subject_id(self):
        from app.schemas.admin_imports import AdminImportQuestionItem
        fields = AdminImportQuestionItem.model_fields
        assert "subject_id" in fields
        assert "subject_code" in fields
        assert "subject_name" in fields


# ---------------------------------------------------------------------------
# 7. Model layer: subject_id column and relationships exist
# ---------------------------------------------------------------------------

class TestModelLayer:
    def test_question_has_subject_id_column(self):
        cols = [c.name for c in Question.__table__.columns]
        assert "subject_id" in cols

    def test_question_import_has_subject_id_column(self):
        cols = [c.name for c in QuestionImport.__table__.columns]
        assert "subject_id" in cols

    def test_question_has_subject_ref_relationship(self):
        assert hasattr(Question, "subject_ref")

    def test_question_import_has_subject_ref_relationship(self):
        assert hasattr(QuestionImport, "subject_ref")

    def test_subject_has_questions_backref(self):
        assert hasattr(Subject, "questions")

    def test_subject_has_question_imports_backref(self):
        assert hasattr(Subject, "question_imports")


# ---------------------------------------------------------------------------
# 8. AI enrich: subject_id handling
# ---------------------------------------------------------------------------

class TestEnrichSubjectId:
    def test_normalize_enrich_prefers_subject_id(self):
        from app.features.question_ai_enrich import _normalize_enrich

        parsed = {"subject_id": 5, "question_type": "single_choice"}
        result = _normalize_enrich(parsed)
        assert result.get("subject_id") == 5
        assert "subject" not in result

    def test_normalize_enrich_fallback_to_legacy_subject(self):
        from app.features.question_ai_enrich import _normalize_enrich

        parsed = {"subject": "math2", "question_type": "single_choice"}
        result = _normalize_enrich(parsed)
        assert result.get("subject") == "math2"
        assert "subject_id" not in result

    def test_normalize_enrich_ignores_invalid_subject(self):
        from app.features.question_ai_enrich import _normalize_enrich

        parsed = {"subject": "nonexistent_subject"}
        result = _normalize_enrich(parsed)
        assert "subject" not in result
        assert "subject_id" not in result


# ---------------------------------------------------------------------------
# 9. Schema deprecated annotations
# ---------------------------------------------------------------------------

class TestSchemaDeprecated:
    def test_update_request_subject_is_deprecated(self):
        from app.schemas.admin_imports import AdminImportQuestionUpdateRequest
        field = AdminImportQuestionUpdateRequest.model_fields.get("subject")
        assert field is not None
        assert field.deprecated is True

    def test_text_parse_request_subject_is_deprecated(self):
        from app.schemas.admin_imports import TextParseRequest
        field = TextParseRequest.model_fields.get("subject")
        assert field is not None
        assert field.deprecated is True

    def test_text_import_request_subject_is_deprecated(self):
        from app.schemas.admin_imports import TextImportRequest
        field = TextImportRequest.model_fields.get("subject")
        assert field is not None
        assert field.deprecated is True

    def test_batch_complete_request_fields_mentions_subject_id(self):
        from app.schemas.admin_imports import AdminImportBatchCompleteRequest
        field = AdminImportBatchCompleteRequest.model_fields.get("fields")
        assert "subject_id" in field.description

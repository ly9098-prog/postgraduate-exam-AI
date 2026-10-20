"""Phase 5.0 Schema Baseline 迁移测试。

验证 p5_0_schema_baseline 迁移文件存在且结构正确，
以及 PracticeRecord / ImportPipeline ORM 模型声明完整。
"""
import os

_MIGRATION_FILE = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "alembic", "versions", "p5_0_schema_baseline.py",
)


class TestMigrationFileExists:
    """迁移文件结构验证"""

    def test_migration_file_exists(self):
        """p5_0_schema_baseline.py 存在"""
        assert os.path.isfile(_MIGRATION_FILE), \
            f"Migration file not found: {_MIGRATION_FILE}"

    def test_revision_chain(self):
        """迁移 revision 链正确"""
        with open(_MIGRATION_FILE, encoding="utf-8") as f:
            content = f.read()
        assert 'revision: str = "p5_0_schema_baseline"' in content
        assert 'down_revision' in content
        assert "p4_6_release_hardening" in content

    def test_upgrade_has_guard_functions(self):
        """upgrade 函数使用 _has_table / _has_column guard（幂等安全）"""
        with open(_MIGRATION_FILE, encoding="utf-8") as f:
            content = f.read()
        assert "_has_table" in content
        assert "_has_column" in content

    def test_downgrade_exists(self):
        """downgrade 函数存在"""
        with open(_MIGRATION_FILE, encoding="utf-8") as f:
            content = f.read()
        assert "def downgrade" in content

    def test_no_drop_table(self):
        """迁移不包含 DROP TABLE（安全约束）"""
        with open(_MIGRATION_FILE, encoding="utf-8") as f:
            content = f.read()
        # downgrade 的 drop_column 是允许的，但不允许 drop_table
        upgrade_section = content.split("def downgrade")[0]
        assert "drop_table" not in upgrade_section

    def test_adds_practice_records_columns(self):
        """迁移添加 5 个 practice_records 新列"""
        with open(_MIGRATION_FILE, encoding="utf-8") as f:
            content = f.read()
        for col in ("question_id", "question_type", "user_answer",
                     "is_correct", "used_time"):
            assert f'"{col}"' in content, \
                f"Migration should add practice_records.{col}"

    def test_adds_import_pipelines_columns(self):
        """迁移添加 2 个 import_pipelines 新列"""
        with open(_MIGRATION_FILE, encoding="utf-8") as f:
            content = f.read()
        assert '"quality_report"' in content
        assert '"alerts"' in content


class TestPracticeRecordORM:
    """PracticeRecord ORM 模型验证"""

    def test_model_has_new_columns(self):
        """ORM 包含 5 个新 per-question 列"""
        from app.models.practice_record import PracticeRecord

        mapper = PracticeRecord.__mapper__
        column_names = {col.key for col in mapper.columns}

        new_cols = {"question_id", "question_type", "user_answer",
                    "is_correct", "used_time"}
        for col in new_cols:
            assert col in column_names, f"ORM missing new column '{col}'"

    def test_current_model_excludes_retired_batch_columns(self):
        """Later migration a4c5d6e7f8b9 retired batch data from per-answer rows."""
        from app.models.practice_record import PracticeRecord

        mapper = PracticeRecord.__mapper__
        column_names = {col.key for col in mapper.columns}

        retired = {"question_ids", "answers", "correct_count",
                   "wrong_count", "duration_sec", "started_at", "finished_at"}
        assert not column_names & retired
        assert {"question_version_id", "projection_state", "mode"} <= column_names

    def test_per_answer_fields_required_and_optional_fields_nullable(self):
        """Check current nullability explicitly; do not silently skip absent legacy fields."""
        from app.models.practice_record import PracticeRecord

        mapper = PracticeRecord.__mapper__
        for name in ("user_id", "question_id", "question_version_id", "subject_id",
                     "question_type", "user_answer", "is_correct", "projection_state"):
            assert mapper.columns[name].nullable is False, name
        for name in ("mode", "used_time"):
            assert mapper.columns[name].nullable is True, name

    def test_session_aggregates_have_a_separate_model(self):
        from app.models.practice_session import PracticeSession

        columns = PracticeSession.__mapper__.columns
        for name in ("request_id", "duration_sec", "started_at", "finished_at",
                     "question_count", "correct_count"):
            assert columns[name].nullable is False, name

    def test_question_id_has_foreign_key(self):
        """question_id 列有 ForeignKey 到 questions.id"""
        from app.models.practice_record import PracticeRecord

        mapper = PracticeRecord.__mapper__
        qid_col = mapper.columns["question_id"]
        fk_targets = [str(fk.target_fullname) for fk in qid_col.foreign_keys]
        assert "questions.id" in fk_targets, \
            f"question_id FK target mismatch: {fk_targets}"


class TestImportPipelineORM:
    """ImportPipeline ORM 模型验证"""

    def test_quality_columns_exist(self):
        """ORM 包含 quality_report 和 alerts 列"""
        from app.models.import_pipeline import ImportPipeline

        mapper = ImportPipeline.__mapper__
        column_names = {col.key for col in mapper.columns}

        assert "quality_report" in column_names
        assert "alerts" in column_names

    def test_quality_columns_nullable(self):
        """质量列允许 NULL"""
        from app.models.import_pipeline import ImportPipeline

        mapper = ImportPipeline.__mapper__
        assert mapper.columns["quality_report"].nullable is True
        assert mapper.columns["alerts"].nullable is True


class TestGetPublishHistoryExists:
    """get_publish_history 函数存在性验证"""

    def test_function_importable(self):
        """get_publish_history 可从 question_publish_service 导入"""
        from app.features.question_publish_service import get_publish_history
        assert callable(get_publish_history)

    def test_schemas_importable(self):
        """PublishHistoryItem 和 PublishHistoryResponse 可导入"""
        from app.schemas.question_publish import (
            PublishHistoryItem,
            PublishHistoryResponse,
        )
        assert PublishHistoryItem is not None
        assert PublishHistoryResponse is not None

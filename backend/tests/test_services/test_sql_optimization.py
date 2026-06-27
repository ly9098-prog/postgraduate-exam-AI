"""Tests for SQL logging and question_imports query optimization.

Covers:
1. Default SQL_ECHO / SQL_LOG_LEVEL / SLOW_QUERY_MS settings
2. Slow query SQL truncation
3. question_imports list query excludes large columns
4. question_imports detail still returns full fields
"""

from __future__ import annotations

from app.core.config import settings
from app.services.admin_import_service import _LIST_COLUMNS


# ── Settings defaults ───────────────────────────────────────


def test_sql_echo_default_false():
    """SQL_ECHO 默认应为 False，避免生产环境 SQL 刷屏."""
    assert settings.SQL_ECHO is False


def test_sql_log_level_default_warning():
    """SQL_LOG_LEVEL 默认应为 WARNING."""
    assert settings.SQL_LOG_LEVEL == "WARNING"


def test_slow_query_ms_default_500():
    """SLOW_QUERY_MS 默认应为 500ms."""
    assert settings.SLOW_QUERY_MS == 500


# ── Slow query SQL truncation ───────────────────────────────


def _format_slow_query_sql(statement: str, max_len: int = 1200) -> str:
    """Replicate the compaction + truncation logic from database.py."""
    compact_sql = " ".join(statement.split())
    if len(compact_sql) > max_len:
        compact_sql = compact_sql[:max_len] + "..."
    return compact_sql


def test_slow_query_truncates_long_sql():
    """超长 SQL 应被压缩空白并截断."""
    long_sql = "SELECT   *   FROM   question_imports   WHERE   status   =   :status   ORDER   BY   created_at   DESC" + "   AND   x   =   y" * 200
    result = _format_slow_query_sql(long_sql, max_len=100)
    assert len(result) <= 100 + 3  # 100 + "..."
    assert result.endswith("...")
    # 空白已被压缩
    assert "  " not in result


def test_slow_query_preserves_short_sql():
    """短 SQL 不应被截断."""
    sql = "SELECT 1"
    result = _format_slow_query_sql(sql)
    assert result == "SELECT 1"


def test_slow_query_compacts_whitespace():
    """空白压缩应正常工作."""
    messy = "SELECT  * \n FROM  users \n WHERE id = :id"
    result = _format_slow_query_sql(messy)
    assert "  " not in result
    assert "\n" not in result
    assert result == "SELECT * FROM users WHERE id = :id"


# ── List query column selection ─────────────────────────────


def _list_column_names() -> set[str]:
    """Get the column names / labels from _LIST_COLUMNS."""
    names: set[str] = set()
    for col in _LIST_COLUMNS:
        name = getattr(col, "key", None) or getattr(col, "name", None)
        if name is not None:
            names.add(name)
    return names


EXCLUDED_LIST_COLUMNS = {
    "raw_data",
    "parsed_content",  # list uses content_preview (substr) instead
    "parsed_options",
    "parsed_analysis",
}

DETAIL_LARGE_COLUMNS = {
    "raw_data",
    "parsed_content",
    "parsed_options",
    "parsed_analysis",
}


def test_list_query_excludes_large_columns():
    """列表查询不应包含 raw_data / parsed_content / parsed_options / parsed_analysis 等大字段."""
    col_names = _list_column_names()
    for large in EXCLUDED_LIST_COLUMNS:
        assert large not in col_names, f"{large} should not be in list query columns"


def test_list_query_includes_content_preview():
    """列表查询应包含 content_preview (substr of parsed_content)."""
    col_names = _list_column_names()
    assert "content_preview" in col_names, "list query should include content_preview"


def test_list_query_includes_essential_fields():
    """列表查询应包含 id / status / batch_id 等必要字段."""
    col_names = _list_column_names()
    essentials = {"id", "status", "batch_id", "created_at", "updated_at"}
    for col in essentials:
        assert col in col_names, f"{col} should be in list query columns"


# ── Detail query ────────────────────────────────────────────


def test_detail_query_can_load_full_fields():
    """验证详情 schema 仍包含 raw_data / parsed_content / parsed_options 等大字段。"""
    from app.schemas.admin_imports import AdminImportQuestionItem

    schema_fields = set(AdminImportQuestionItem.model_fields.keys())
    # 详情需要包含 list 排除的大字段
    for large in DETAIL_LARGE_COLUMNS:
        assert large in schema_fields, f"Detail schema should include {large}"
    assert "parsed_answer" in schema_fields

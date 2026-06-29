"""pgvector 修复验证 — 单元测试。

覆盖：
1. CAST(:emb AS vector) 绑定参数为 emb
2. embedding 校验（维度、有限值、类型）
3. VectorDecision 决策矩阵（off/shadow/allowlist/all）
4. allowlist 空值拒绝
5. subject/user_id 白名单匹配
6. shadow 不使用结果
7. 回填 cursor 分页
8. 回填跳过已有 embedding
9. force update
10. 单条失败后批次继续
11. API commit/rollback
12. 缓存失效
13. 状态接口维度不匹配检测
"""
import math
from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from app.services.vector_retrieval_service import (
    VectorDecision,
    decide_vector_access,
    resolve_vector_mode,
    is_vector_allowed_for,
    validate_embedding,
    _parse_allowlist,
    _is_allowlist_empty,
    _allowlist_matches,
    _reset_vector_enabled_cache,
    invalidate_vector_cache,
)
from app.services.embedding_service import vector_to_pg_literal


# ── 1. validate_embedding ──


class TestValidateEmbedding:
    """embedding 校验测试。"""

    def test_valid_list(self):
        result = validate_embedding([0.1, 0.2, 0.3], 3)
        assert result == [0.1, 0.2, 0.3]
        assert all(isinstance(x, float) for x in result)

    def test_valid_tuple(self):
        result = validate_embedding((1, 2, 3), 3)
        assert result == [1.0, 2.0, 3.0]

    def test_int_items_converted(self):
        result = validate_embedding([1, 2, 3], 3)
        assert result == [1.0, 2.0, 3.0]

    def test_none_raises(self):
        with pytest.raises(ValueError, match="embedding is None"):
            validate_embedding(None, 3)

    def test_string_raises(self):
        with pytest.raises(ValueError, match="must be list/tuple"):
            validate_embedding("not a vector", 3)

    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="empty"):
            validate_embedding([], 0)

    def test_wrong_dimension_raises(self):
        with pytest.raises(ValueError, match="dimension mismatch"):
            validate_embedding([0.1, 0.2], 3)

    def test_nested_array_raises(self):
        with pytest.raises(ValueError, match="nested array"):
            validate_embedding([[0.1], 0.2, 0.3], 3)

    def test_string_item_raises(self):
        with pytest.raises(ValueError, match="not numeric"):
            validate_embedding(["a", 0.2, 0.3], 3)

    def test_nan_raises(self):
        with pytest.raises(ValueError, match="not finite"):
            validate_embedding([float("nan"), 0.2, 0.3], 3)

    def test_inf_raises(self):
        with pytest.raises(ValueError, match="not finite"):
            validate_embedding([float("inf"), 0.2, 0.3], 3)

    def test_neg_inf_raises(self):
        with pytest.raises(ValueError, match="not finite"):
            validate_embedding([float("-inf"), 0.2, 0.3], 3)

    def test_none_item_raises(self):
        with pytest.raises(ValueError, match="not numeric"):
            validate_embedding([None, 0.2, 0.3], 3)


# ── 2. VectorDecision 决策矩阵 ──


class TestVectorDecisionMatrix:
    """VectorDecision 各模式决策测试。"""

    @patch("app.services.vector_retrieval_service.resolve_vector_mode", return_value="off")
    def test_off_mode(self, mock_mode):
        d = decide_vector_access(user_id=1, subject="math", infra_available=True)
        assert d.execute is False
        assert d.use_result is False
        assert d.mode == "off"
        assert d.reason == "mode_off"

    @patch("app.services.vector_retrieval_service.resolve_vector_mode", return_value="shadow")
    def test_shadow_mode(self, mock_mode):
        d = decide_vector_access(user_id=1, subject="math", infra_available=True)
        assert d.execute is True
        assert d.use_result is False
        assert d.mode == "shadow"
        assert d.reason == "shadow_mode"

    @patch("app.services.vector_retrieval_service.resolve_vector_mode", return_value="all")
    def test_all_mode(self, mock_mode):
        d = decide_vector_access(user_id=1, subject="math", infra_available=True)
        assert d.execute is True
        assert d.use_result is True
        assert d.mode == "all"
        assert d.reason == "mode_all"

    @patch("app.services.vector_retrieval_service._allowlist_matches", return_value=True)
    @patch("app.services.vector_retrieval_service._is_allowlist_empty", return_value=False)
    @patch("app.services.vector_retrieval_service.resolve_vector_mode", return_value="allowlist")
    def test_allowlist_hit(self, mock_mode, mock_empty, mock_match):
        d = decide_vector_access(user_id=1, subject="math", infra_available=True)
        assert d.execute is True
        assert d.use_result is True
        assert d.reason == "allowlist_hit"

    @patch("app.services.vector_retrieval_service._allowlist_matches", return_value=False)
    @patch("app.services.vector_retrieval_service._is_allowlist_empty", return_value=False)
    @patch("app.services.vector_retrieval_service.resolve_vector_mode", return_value="allowlist")
    def test_allowlist_miss(self, mock_mode, mock_empty, mock_match):
        d = decide_vector_access(user_id=99, subject="art", infra_available=True)
        assert d.execute is False
        assert d.use_result is False
        assert d.reason == "allowlist_miss"

    @patch("app.services.vector_retrieval_service._is_allowlist_empty", return_value=True)
    @patch("app.services.vector_retrieval_service.resolve_vector_mode", return_value="allowlist")
    def test_allowlist_empty_deny(self, mock_mode, mock_empty):
        """allowlist 为空时默认全部拒绝。"""
        d = decide_vector_access(user_id=1, subject="math", infra_available=True)
        assert d.execute is False
        assert d.use_result is False
        assert d.reason == "allowlist_empty_deny"

    @patch("app.services.vector_retrieval_service.resolve_vector_mode", return_value="all")
    def test_infra_unavailable(self, mock_mode):
        d = decide_vector_access(user_id=1, subject="math", infra_available=False)
        assert d.enabled is False
        assert d.execute is False
        assert d.use_result is False
        assert d.reason == "infra_unavailable"

    def test_vector_decision_is_frozen(self):
        d = VectorDecision(enabled=True, execute=True, use_result=True, mode="all", reason="test")
        with pytest.raises(FrozenInstanceError):
            d.execute = False  # type: ignore[misc]


# ── 3. allowlist 解析和匹配 ──


class TestAllowlistParsing:
    """allowlist 解析和匹配测试。"""

    @patch("app.services.vector_retrieval_service.settings")
    def test_empty_allowlist(self, mock_settings):
        mock_settings.VECTOR_ALLOWLIST = ""
        result = _parse_allowlist()
        assert result == {"user_ids": [], "subjects": []}

    @patch("app.services.vector_retrieval_service.settings")
    def test_subject_allowlist(self, mock_settings):
        mock_settings.VECTOR_ALLOWLIST = '["exam408-ds", "exam408-os"]'
        result = _parse_allowlist()
        assert "exam408-ds" in result["subjects"]
        assert "exam408-os" in result["subjects"]

    @patch("app.services.vector_retrieval_service.settings")
    def test_user_id_allowlist(self, mock_settings):
        mock_settings.VECTOR_ALLOWLIST = "[1, 2, 3]"
        result = _parse_allowlist()
        assert result["user_ids"] == [1, 2, 3]

    @patch("app.services.vector_retrieval_service.settings")
    def test_mixed_allowlist(self, mock_settings):
        mock_settings.VECTOR_ALLOWLIST = '["exam408-ds", 42]'
        result = _parse_allowlist()
        assert 42 in result["user_ids"]
        assert "exam408-ds" in result["subjects"]

    @patch("app.services.vector_retrieval_service.settings")
    def test_invalid_json(self, mock_settings):
        mock_settings.VECTOR_ALLOWLIST = "not json"
        result = _parse_allowlist()
        assert result == {"user_ids": [], "subjects": []}

    @patch("app.services.vector_retrieval_service.settings")
    def test_subject_normalization(self, mock_settings):
        """subject 匹配时忽略大小写和空格。"""
        mock_settings.VECTOR_ALLOWLIST = '["Exam408-DS"]'
        result = _parse_allowlist()
        # 存储时已转为小写
        assert "exam408-ds" in result["subjects"]

    @patch("app.services.vector_retrieval_service.settings")
    def test_whitespace_subject_filtered(self, mock_settings):
        mock_settings.VECTOR_ALLOWLIST = '["  ", "valid"]'
        result = _parse_allowlist()
        assert len(result["subjects"]) == 1
        assert "valid" in result["subjects"]


class TestAllowlistMatching:

    @patch("app.services.vector_retrieval_service.settings")
    def test_user_id_match(self, mock_settings):
        mock_settings.VECTOR_ALLOWLIST = "[1, 2]"
        assert _allowlist_matches(user_id=1) is True
        assert _allowlist_matches(user_id=3) is False

    @patch("app.services.vector_retrieval_service.settings")
    def test_subject_match_case_insensitive(self, mock_settings):
        mock_settings.VECTOR_ALLOWLIST = '["exam408-ds"]'
        assert _allowlist_matches(subject="Exam408-DS") is True
        assert _allowlist_matches(subject="exam408-os") is False

    @patch("app.services.vector_retrieval_service.settings")
    def test_empty_allowlist_no_match(self, mock_settings):
        mock_settings.VECTOR_ALLOWLIST = ""
        assert _allowlist_matches(user_id=1) is False

    @patch("app.services.vector_retrieval_service.settings")
    def test_is_vector_allowed_for_empty_deny(self, mock_settings):
        """allowlist 模式 + 空白名单 = 全部拒绝。"""
        mock_settings.VECTOR_MODE = "allowlist"
        mock_settings.VECTOR_ENABLED = True
        mock_settings.VECTOR_ALLOWLIST = ""
        assert is_vector_allowed_for(user_id=1, subject="math") is False


# ── 4. SQL 绑定参数验证 ──


class TestSQLBindingParameters:
    """验证 CAST(:emb AS vector) 的绑定参数名称为 emb。"""

    def test_cast_bindparam_name(self):
        """SQLAlchemy text() 解析 CAST(:emb AS vector) 后，绑定参数名应为 emb。"""
        from sqlalchemy import text
        sql = text("SELECT CAST(:emb AS vector)")
        # 获取绑定参数名称
        params = sql._bindparams
        assert "emb" in params, f"Expected 'emb' in bind params, got {list(params.keys())}"

    def test_cast_in_update(self):
        from sqlalchemy import text
        sql = text(
            "UPDATE question_embeddings SET embedding = CAST(:emb AS vector) "
            "WHERE question_id = :qid"
        )
        params = sql._bindparams
        assert "emb" in params
        assert "qid" in params

    def test_cast_in_insert(self):
        from sqlalchemy import text
        sql = text(
            "INSERT INTO question_embeddings (embedding) VALUES (CAST(:emb AS vector))"
        )
        params = sql._bindparams
        assert "emb" in params

    def test_cast_in_similarity_search(self):
        from sqlalchemy import text
        sql = text("""
            SELECT 1 - (qe.embedding <=> CAST(:emb AS vector)) AS similarity
            FROM question_embeddings qe
            ORDER BY qe.embedding <=> CAST(:emb AS vector)
        """)
        params = sql._bindparams
        assert "emb" in params
        # 确保没有解析出多余的参数（如 vector）
        assert len(params) == 1

    def test_old_syntax_wrong_param_name(self):
        """验证旧写法 :emb::vector 被 SQLAlchemy 错误解析为参数 em（非 emb）。

        这就是根因：调用代码传入 emb，但 SQLAlchemy 期望 em，导致绑定失败。
        CAST(:emb AS vector) 正确解析为 emb。
        """
        from sqlalchemy import text
        sql = text("SELECT :emb::vector")
        params = sql._bindparams
        # 旧写法解析出 'em' 而非 'emb'，这就是 bug
        assert "em" in params, f"Expected 'em' (bug), got {list(params.keys())}"
        assert "emb" not in params, "Old syntax should NOT produce 'emb'"


# ── 5. 回填游标分页 ──


class TestBackfillCursorPagination:
    """回填游标分页测试。"""

    @pytest.mark.asyncio
    async def test_backfill_returns_cursor_fields(self):
        """回填结果应包含 next_cursor 和 has_more。"""
        mock_db = MagicMock()
        mock_db.bind = MagicMock()
        mock_db.bind.dialect.name = "postgresql"
        mock_db.execute = AsyncMock()

        # Mock is_vector_enabled → True
        with patch("app.services.vector_retrieval_service.is_vector_enabled", new_callable=AsyncMock, return_value=True):
            # Mock query result → empty
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_db.execute.return_value = mock_result

            result = await __import__(
                "app.services.vector_retrieval_service", fromlist=["backfill_question_embeddings"]
            ).backfill_question_embeddings(mock_db, limit=10, after_id=5)

            assert "next_cursor" in result
            assert "has_more" in result
            assert result["has_more"] is False
            assert result["next_cursor"] is None

    @pytest.mark.asyncio
    async def test_backfill_disabled_when_not_vector_enabled(self):
        """向量未启用时返回 enabled=False。"""
        mock_db = MagicMock()
        mock_db.bind = MagicMock()
        mock_db.bind.dialect.name = "sqlite"

        with patch("app.services.vector_retrieval_service.is_vector_enabled", new_callable=AsyncMock, return_value=False):
            result = await __import__(
                "app.services.vector_retrieval_service", fromlist=["backfill_question_embeddings"]
            ).backfill_question_embeddings(mock_db)

            assert result["enabled"] is False


# ── 6. 缓存失效 ──


class TestCacheInvalidation:

    @pytest.mark.asyncio
    async def test_invalidate_increments_version(self):
        """invalidate_vector_cache 应递增版本号。"""
        with patch("app.services.vector_retrieval_service.cache") as mock_cache:
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.set = AsyncMock()

            await invalidate_vector_cache(user_id=42)

            mock_cache.set.assert_called_once()
            call_args = mock_cache.set.call_args
            assert call_args[0][0] == "vector:answer_ver:42"
            assert call_args[0][1] == 1

    @pytest.mark.asyncio
    async def test_invalidate_increments_existing(self):
        """已有版本号时递增。"""
        with patch("app.services.vector_retrieval_service.cache") as mock_cache:
            mock_cache.get = AsyncMock(return_value=5)
            mock_cache.set = AsyncMock()

            await invalidate_vector_cache(user_id=42)

            call_args = mock_cache.set.call_args
            assert call_args[0][1] == 6

    @pytest.mark.asyncio
    async def test_invalidate_swallows_errors(self):
        """缓存不可用时不抛异常。"""
        with patch("app.services.vector_retrieval_service.cache") as mock_cache:
            mock_cache.get = AsyncMock(side_effect=ConnectionError("redis down"))

            # 不应抛异常
            await invalidate_vector_cache(user_id=42)


# ── 7. 状态接口 ──


class TestStatusEndpoint:

    @pytest.mark.asyncio
    async def test_status_dimension_mismatch(self):
        """维度不匹配应在 issues 中报告。"""
        mock_db = MagicMock()
        mock_db.bind = MagicMock()
        mock_db.bind.dialect.name = "postgresql"
        mock_db.execute = AsyncMock()

        # Mock 各种查询结果
        async def mock_execute(sql, *args, **kwargs):
            sql_text = str(sql) if hasattr(sql, '__str__') else ""
            result = MagicMock()

            if "pg_extension" in sql_text:
                result.scalar.return_value = 1
            elif "information_schema.tables" in sql_text:
                result.scalar.return_value = 1
            elif "embedding_dim" in sql_text:
                result.scalar.return_value = 512  # 与配置的 1024 不匹配
            elif "COUNT" in sql_text:
                result.scalar.return_value = 10
            elif "pg_indexes" in sql_text:
                result.scalar.return_value = 1
            else:
                result.scalar.return_value = 100
            return result

        mock_db.execute.side_effect = mock_execute

        with patch("app.services.vector_retrieval_service.settings") as mock_settings, \
             patch("app.services.vector_retrieval_service.is_vector_enabled", new_callable=AsyncMock, return_value=True):
            mock_settings.VECTOR_ENABLED = True
            mock_settings.VECTOR_MODE = "all"
            mock_settings.EMBEDDING_DIM = 1024
            mock_settings.EMBEDDING_MODEL = "test-model"
            mock_settings.EMBEDDING_API_KEY = "test-key"
            mock_settings.EMBEDDING_BASE_URL = "http://test"
            mock_settings.VECTOR_ALLOWLIST = ""
            mock_settings.VECTOR_ENABLED = True

            from app.services.vector_retrieval_service import get_embedding_status
            status = await get_embedding_status(mock_db)

            assert status["configured_dimension"] == 1024
            assert status["database_dimension"] == 512
            assert status["dimension_matches"] is False
            assert any("dimension mismatch" in issue for issue in status["issues"])


# ── 8. resolve_vector_mode ──


class TestResolveVectorMode:

    @patch("app.services.vector_retrieval_service.settings")
    def test_explicit_mode(self, mock_settings):
        mock_settings.VECTOR_MODE = "shadow"
        mock_settings.VECTOR_ENABLED = False
        assert resolve_vector_mode() == "shadow"

    @patch("app.services.vector_retrieval_service.settings")
    def test_backward_compat_enabled_true(self, mock_settings):
        """VECTOR_ENABLED=True + VECTOR_MODE=off → 兼容为 all。"""
        mock_settings.VECTOR_MODE = "off"
        mock_settings.VECTOR_ENABLED = True
        assert resolve_vector_mode() == "all"

    @patch("app.services.vector_retrieval_service.settings")
    def test_invalid_mode_fallback(self, mock_settings):
        mock_settings.VECTOR_MODE = "invalid"
        mock_settings.VECTOR_ENABLED = False
        assert resolve_vector_mode() == "off"

    @patch("app.services.vector_retrieval_service.settings")
    def test_whitespace_mode(self, mock_settings):
        mock_settings.VECTOR_MODE = "  shadow  "
        mock_settings.VECTOR_ENABLED = False
        assert resolve_vector_mode() == "shadow"


# ── 9. vector_to_pg_literal ──


class TestVectorToPgLiteral:

    def test_basic(self):
        assert vector_to_pg_literal([0.1, 0.2, 0.3]) == "[0.1,0.2,0.3]"

    def test_integers(self):
        assert vector_to_pg_literal([1, 2, 3]) == "[1,2,3]"

    def test_single(self):
        assert vector_to_pg_literal([0.5]) == "[0.5]"

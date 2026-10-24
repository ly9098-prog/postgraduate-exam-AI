"""向量检索服务纯函数兼容基线。

覆盖 vector_retrieval_service 中可独立测试的纯规则：
- _parse_vector_dimension：向量类型维度解析
- validate_embedding：embedding 校验
- decide_vector_access：向量访问决策
- is_vector_allowed_for：向量访问白名单（已全开放）
"""

from __future__ import annotations

import math

import pytest

from app.services.vector_retrieval_service import (
    _parse_vector_dimension,
    decide_vector_access,
    is_vector_allowed_for,
    validate_embedding,
)


class TestParseVectorDimension:
    """_parse_vector_dimension 从 PostgreSQL format_type 解析向量维度。"""

    def test_none_returns_none(self) -> None:
        assert _parse_vector_dimension(None) is None

    def test_non_string_returns_none(self) -> None:
        assert _parse_vector_dimension(42) is None

    def test_valid_vector_type(self) -> None:
        assert _parse_vector_dimension("vector(1536)") == 1536

    def test_valid_vector_type_with_whitespace(self) -> None:
        assert _parse_vector_dimension("  vector(768)  ") == 768

    def test_non_vector_type_returns_none(self) -> None:
        assert _parse_vector_dimension("integer") is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_vector_dimension("") is None


class TestValidateEmbedding:
    """validate_embedding 校验向量并返回 list[float]。"""

    def test_valid_vector(self) -> None:
        result = validate_embedding([1.0, 2.0, 3.0], 3)
        assert result == [1.0, 2.0, 3.0]

    def test_valid_int_vector(self) -> None:
        result = validate_embedding([1, 2, 3], 3)
        assert result == [1.0, 2.0, 3.0]

    def test_valid_tuple(self) -> None:
        result = validate_embedding((1.0, 2.0), 2)
        assert result == [1.0, 2.0]

    def test_none_raises(self) -> None:
        with pytest.raises(ValueError, match="None"):
            validate_embedding(None, 3)

    def test_non_list_raises(self) -> None:
        with pytest.raises(ValueError, match="list/tuple"):
            validate_embedding("not a vector", 3)

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            validate_embedding([], 0)

    def test_dimension_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="mismatch"):
            validate_embedding([1.0, 2.0], 3)

    def test_nested_array_raises(self) -> None:
        with pytest.raises(ValueError, match="nested"):
            validate_embedding([1.0, [2.0]], 2)

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(ValueError, match="not numeric"):
            validate_embedding([1.0, "x"], 2)

    def test_nan_raises(self) -> None:
        with pytest.raises(ValueError, match="not finite"):
            validate_embedding([1.0, float("nan")], 2)

    def test_infinity_raises(self) -> None:
        with pytest.raises(ValueError, match="not finite"):
            validate_embedding([1.0, float("inf")], 2)


class TestDecideVectorAccess:
    """decide_vector_access 统一向量访问决策。"""

    def test_default_all_enabled(self) -> None:
        result = decide_vector_access()
        assert result.enabled is True
        assert result.execute is True
        assert result.use_result is True
        assert result.mode == "all"

    def test_infra_unavailable(self) -> None:
        result = decide_vector_access(infra_available=False)
        assert result.enabled is False
        assert result.execute is False
        assert result.use_result is False
        assert result.reason == "infra_unavailable"

    def test_with_user_and_subject(self) -> None:
        result = decide_vector_access(user_id=1, subject="math")
        assert result.enabled is True
        assert result.execute is True


class TestIsVectorAllowedFor:
    """is_vector_allowed_for 始终返回 True（白名单已移除）。"""

    def test_no_args(self) -> None:
        assert is_vector_allowed_for() is True

    def test_with_user_id(self) -> None:
        assert is_vector_allowed_for(user_id=42) is True

    def test_with_subject(self) -> None:
        assert is_vector_allowed_for(subject="math") is True

    def test_with_both(self) -> None:
        assert is_vector_allowed_for(user_id=1, subject="english") is True

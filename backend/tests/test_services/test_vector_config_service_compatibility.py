"""Real compatibility baseline for vector config pure functions.

Covers ``_model_features`` (feature list normalization) and
``get_embedding_config_sync`` (settings-based fallback config).
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.vector_config_service import (
    EmbeddingConfig,
    _model_features,
    get_embedding_config_sync,
)


class TestModelFeatures:
    """``_model_features`` normalizes the dual feature/feature_list fields."""

    def test_features_list_takes_precedence(self):
        model = SimpleNamespace(features=["embedding", "vision"], feature="ocr")
        assert _model_features(model) == ["embedding", "vision"]

    def test_features_list_filters_empty_and_non_str(self):
        model = SimpleNamespace(features=["embedding", "", None, 123, "  "], feature=None)
        assert _model_features(model) == ["embedding", "None", "123"]

    def test_falls_back_to_single_feature(self):
        model = SimpleNamespace(features=None, feature="ocr")
        assert _model_features(model) == ["ocr"]

    def test_empty_when_no_features(self):
        model = SimpleNamespace(features=None, feature=None)
        assert _model_features(model) == []

    def test_empty_features_list_returns_empty(self):
        model = SimpleNamespace(features=[], feature=None)
        assert _model_features(model) == []

    def test_features_list_with_only_empty_strings(self):
        model = SimpleNamespace(features=["", "  "], feature=None)
        assert _model_features(model) == []


class TestGetEmbeddingConfigSync:
    """``get_embedding_config_sync`` builds a fallback config from settings."""

    def test_returns_embedding_config_instance(self):
        cfg = get_embedding_config_sync()
        assert isinstance(cfg, EmbeddingConfig)

    def test_api_key_is_empty(self):
        cfg = get_embedding_config_sync()
        assert cfg.api_key == ""

    def test_model_config_id_is_none(self):
        cfg = get_embedding_config_sync()
        assert cfg.model_config_id is None

    def test_provider_from_settings(self):
        from app.core.config import settings

        cfg = get_embedding_config_sync()
        assert cfg.provider == settings.EMBEDDING_PROVIDER

    def test_base_url_from_settings(self):
        from app.core.config import settings

        cfg = get_embedding_config_sync()
        assert cfg.base_url == settings.EMBEDDING_BASE_URL

    def test_dim_from_settings(self):
        from app.core.config import settings

        cfg = get_embedding_config_sync()
        assert cfg.dim == settings.EMBEDDING_DIM

    def test_timeout_from_settings(self):
        from app.core.config import settings

        cfg = get_embedding_config_sync()
        assert cfg.timeout == settings.EMBEDDING_TIMEOUT

    def test_batch_size_from_settings(self):
        from app.core.config import settings

        cfg = get_embedding_config_sync()
        assert cfg.batch_size == settings.EMBEDDING_BATCH_SIZE

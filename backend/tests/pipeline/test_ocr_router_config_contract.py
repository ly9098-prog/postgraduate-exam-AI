"""Contract for OCR router config composition and degradation boundaries."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.features.pipeline_ocr_router_config import (
    build_router_config,
    initialize_router_config,
)
from app.services import admin_ai_config_service, model_config_resolver


class _MissingResolver:
    def __init__(self, db):
        self.db = db

    async def resolve_for_capability(self, capability):
        raise ValueError(f"missing {capability}")

    async def resolve_secret(self, config):
        raise AssertionError("secret must not be read without a resolved config")


class _FailingResolverInit:
    def __init__(self, db):
        raise RuntimeError("resolver init failed")


def _recording_logger(events):
    def record(name):
        def call(*args, **kwargs):
            events.append((name, args, kwargs))

        return call

    return SimpleNamespace(info=record("info"), warning=record("warning"))


def test_initialize_router_config_preserves_option_order_and_filter_coercion():
    config = initialize_router_config(
        {
            "ocr_correction_mode": "shadow",
            "ocr_noise_threshold": 0.7,
            "ocr_correction_daily_token_limit": 70000,
            "ocr_correction_monthly_token_limit": 900000,
            "ocr_fix_model": "fixture-model",
            "ocr_fix_strategy": "fixture-strategy",
            "ocr_filter_sensitive": "FALSE",
        }
    )

    assert config == {
        "mode": "shadow",
        "noise_threshold": 0.7,
        "daily_token_limit": 70000,
        "monthly_token_limit": 900000,
        "ocr_fix_model": "fixture-model",
        "ocr_fix_strategy": "fixture-strategy",
        "ocr_filter_sensitive": False,
    }
    assert (
        initialize_router_config({"ocr_filter_sensitive": True})["ocr_filter_sensitive"]
        is True
    )


def test_initialize_router_config_resolves_string_port_from_namespace():
    config = initialize_router_config(
        {"ocr_filter_sensitive": "TRUE"},
        namespace={"str": lambda _value: "false"},
    )

    assert config["ocr_filter_sensitive"] is False


@pytest.mark.asyncio
async def test_admin_filter_values_keep_types_and_legacy_aliases(monkeypatch):
    db = object()
    events = []

    async def fake_get_all_configs(actual_db):
        assert actual_db is db
        return {
            "ocr_filter_sensitive": "false",
            "ocr_filter_max_chars": 5000,
            "ocr_filter_max_tokens": "6000",
            "unrelated": "ignored",
        }

    monkeypatch.setattr(
        admin_ai_config_service, "get_all_configs", fake_get_all_configs
    )
    monkeypatch.setattr(
        model_config_resolver, "AIModelConfigResolver", _MissingResolver
    )

    config = await build_router_config(
        {},
        db,
        namespace={"logger": _recording_logger(events)},
    )

    assert config["ocr_filter_sensitive"] is False
    assert config["ocr_filter_max_chars"] == 5000
    assert config["ocr_filter_max_tokens"] == "6000"
    assert "unrelated" not in config
    assert config["deepseek_api_key"] == ""
    assert config["deepseek_base_url"] == ""
    assert [event[0] for event in events] == ["info", "info"]


@pytest.mark.asyncio
async def test_admin_filter_coercion_resolves_builtin_ports(monkeypatch):
    db = object()

    async def fake_get_all_configs(_db):
        return {"ocr_filter_sensitive": "TRUE"}

    monkeypatch.setattr(
        admin_ai_config_service, "get_all_configs", fake_get_all_configs
    )
    monkeypatch.setattr(
        model_config_resolver, "AIModelConfigResolver", _MissingResolver
    )

    config = await build_router_config(
        {},
        db,
        namespace={
            "isinstance": lambda _value, _type: False,
            "bool": bool,
            "str": lambda _value: "false",
            "Exception": Exception,
            "ValueError": ValueError,
            "logger": _recording_logger([]),
        },
    )

    assert config["ocr_filter_sensitive"] is False


@pytest.mark.asyncio
async def test_outer_exception_port_is_resolved_from_namespace(monkeypatch):
    class FailingResolverInit:
        def __init__(self, _db):
            raise RuntimeError("resolver init failed")

    def fail_if_called(_opts, _db, *, namespace):
        raise AssertionError("admin filters must not run after the raised exception")

    monkeypatch.setattr(
        model_config_resolver, "AIModelConfigResolver", FailingResolverInit
    )
    monkeypatch.setattr(
        "app.features.pipeline_ocr_router_config.apply_admin_filter_config",
        fail_if_called,
    )

    with pytest.raises(RuntimeError, match="resolver init failed"):
        await build_router_config(
            {},
            object(),
            namespace={"Exception": ValueError},
        )


@pytest.mark.asyncio
async def test_resolver_init_failure_is_logged_before_admin_filters(monkeypatch):
    db = object()
    events = []

    async def fake_get_all_configs(actual_db):
        assert actual_db is db
        return {"ocr_filter_sensitive": True}

    monkeypatch.setattr(
        admin_ai_config_service, "get_all_configs", fake_get_all_configs
    )
    monkeypatch.setattr(
        model_config_resolver, "AIModelConfigResolver", _FailingResolverInit
    )

    config = await build_router_config(
        {},
        db,
        namespace={"logger": _recording_logger(events)},
    )

    assert config["ocr_filter_sensitive"] is True
    assert [event[0] for event in events] == ["warning"]
    assert events[0][2]["exc_info"] is True


@pytest.mark.asyncio
async def test_admin_filter_failure_keeps_resolved_config_and_aliases(monkeypatch):
    db = object()
    events = []

    async def failing_get_all_configs(actual_db):
        raise RuntimeError("admin configs unavailable")

    monkeypatch.setattr(
        admin_ai_config_service, "get_all_configs", failing_get_all_configs
    )
    monkeypatch.setattr(
        model_config_resolver, "AIModelConfigResolver", _MissingResolver
    )

    config = await build_router_config(
        {"ocr_correction_mode": "auto"},
        db,
        namespace={"logger": _recording_logger(events)},
    )

    assert config["mode"] == "auto"
    assert config["deepseek_api_key"] == ""
    assert config["deepseek_base_url"] == ""
    assert [event[0] for event in events] == ["info", "info", "warning"]


@pytest.mark.asyncio
async def test_no_db_skips_resolution_and_filters_but_keeps_aliases(monkeypatch):
    monkeypatch.setattr(
        admin_ai_config_service,
        "get_all_configs",
        lambda db: pytest.fail("admin config must not be read"),
    )
    monkeypatch.setattr(
        model_config_resolver,
        "AIModelConfigResolver",
        lambda db: pytest.fail("resolver must not be constructed"),
    )

    config = await build_router_config({}, None, namespace={})

    assert config["mode"] == "auto"
    assert config["deepseek_api_key"] == ""
    assert config["deepseek_base_url"] == ""

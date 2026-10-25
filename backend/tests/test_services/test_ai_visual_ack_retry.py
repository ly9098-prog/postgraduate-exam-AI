"""Compatibility baseline for visual acknowledgement retry execution."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.ai.visual_ack_retry import (
    retry_visual_ack,
    should_retry_visual_ack,
)


def runtime():
    return SimpleNamespace(
        model_name="analysis-model",
        api_key="key",
        base_url="https://api.invalid/v1",
        provider="openai",
    )


def test_retry_is_bounded_to_valid_grounding_and_main_budget():
    assert should_retry_visual_ack(
        parsed_valid=True, grounding_valid=True, duration_ms=38_000
    )
    assert not should_retry_visual_ack(
        parsed_valid=False, grounding_valid=True, duration_ms=1
    )
    assert not should_retry_visual_ack(
        parsed_valid=True, grounding_valid=False, duration_ms=1
    )
    assert not should_retry_visual_ack(
        parsed_valid=True, grounding_valid=True, duration_ms=38_001
    )


@pytest.mark.asyncio
async def test_successful_probe_accumulates_usage_and_recovers_evidence():
    calls = {}

    async def chat(_messages, **kwargs):
        calls.update(kwargs)
        return {
            "content": '{"visual_evidence":"图中给出栈"}',
            "duration_ms": 21,
            "tokens_used": 32,
        }

    result = await retry_visual_ack(
        ["data:image/png;base64,AAA"],
        runtime=runtime(),
        source_model="main-model",
        wrong_question_id=7,
        current_evidence="",
        chat=chat,
        extract_evidence=lambda raw: "图中给出栈" if "图中" in raw else "",
    )

    assert result.retried is True
    assert result.evidence == "图中给出栈"
    assert result.retry_ms == 21
    assert result.tokens_used_delta == 32
    assert calls["model"] == "analysis-model"
    assert calls["temperature"] == 0.0
    assert calls["max_tokens"] == 160


@pytest.mark.asyncio
async def test_failed_probe_preserves_current_evidence():
    async def chat(_messages, **_kwargs):
        raise RuntimeError("provider reset")

    result = await retry_visual_ack(
        ["data:image/png;base64,AAA"],
        runtime=runtime(),
        source_model="main-model",
        wrong_question_id=7,
        current_evidence="无法读取",
        chat=chat,
        extract_evidence=lambda _raw: "",
    )

    assert result.retried is True
    assert result.evidence == "无法读取"
    assert result.retry_ms == 0
    assert result.tokens_used_delta == 0

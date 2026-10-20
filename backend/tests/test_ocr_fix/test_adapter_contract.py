"""Exercise real OCR adapters with an isolated LLM transport."""

from unittest.mock import AsyncMock

import pytest

from app.features.ocr_fix import openai_compatible_adapter as adapter_module
from app.features.ocr_fix.deepseek_adapter import DeepSeekFixer
from app.features.ocr_fix.interfaces import OCRFixResult
from app.features.ocr_fix.openai_compatible_adapter import OpenAICompatibleFixer
from app.features.ocr_fix.router import OCRFixRouter

TEXT = "1. Which value is correct?\nA. One\nB. Two\nC. Three\nD. Four"


@pytest.mark.asyncio
@pytest.mark.parametrize("options,text", [
    ({}, TEXT),
    ({"api_key": "test-key", "base_url": "https://example.invalid/v1"}, TEXT),
    ({"api_key": "test-key", "model_name": "test-model"}, TEXT),
    ({"base_url": "https://example.invalid/v1", "model_name": "test-model"}, TEXT),
    ({}, "  \n"),
])
async def test_unavailable_or_empty_input_never_calls_llm(monkeypatch, options, text):
    chat = AsyncMock()
    monkeypatch.setattr(adapter_module.llm, "chat", chat)
    result = await OpenAICompatibleFixer(**options).fix(ocr_text=text)
    assert isinstance(result, OCRFixResult)
    assert result.fixed_text == text
    chat.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("fixer_class", [OpenAICompatibleFixer, DeepSeekFixer])
async def test_configured_adapter_preserves_transport_and_result(monkeypatch, fixer_class):
    chat = AsyncMock(return_value={"content": TEXT, "tokens_used": 17})
    monkeypatch.setattr(adapter_module.llm, "chat", chat)
    fixer = fixer_class(
        api_key="test-key", base_url="https://example.invalid/v1",
        model_name="test-model", provider="test-provider",
    )
    result = await fixer.fix(ocr_text=TEXT)
    assert isinstance(result, OCRFixResult)
    assert result.fixed_text == TEXT
    assert result.model_used == "test-model"
    assert result.tokens_used == 17
    assert result.confidence == 0.85
    chat.assert_awaited_once()
    assert chat.call_args.kwargs == {
        "temperature": 0.1, "model": "test-model", "api_key": "test-key",
        "base_url": "https://example.invalid/v1", "provider": "test-provider",
    }
    assert any(TEXT in message["content"] for message in chat.call_args.args[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("response,reason", [
    ({"content": ""}, None),
    ({"content": "tiny"}, "output length out of bounds"),
    ({"content": "x" * 200}, "output length out of bounds"),
    (RuntimeError("transport unavailable"), "error: transport unavailable"),
])
async def test_failed_or_invalid_output_returns_original(monkeypatch, response, reason):
    chat = AsyncMock()
    if isinstance(response, Exception):
        chat.side_effect = response
    else:
        chat.return_value = response
    monkeypatch.setattr(adapter_module.llm, "chat", chat)
    fixer = OpenAICompatibleFixer(
        api_key="test-key", base_url="https://example.invalid/v1", model_name="test-model",
    )
    result = await fixer.fix(ocr_text=TEXT)
    assert result.fixed_text == TEXT
    assert result.raw_response == reason
    chat.assert_awaited_once()


@pytest.mark.parametrize("alias", ["openai-compatible", "openai_compatible", "deepseek"])
def test_router_lazily_builds_configured_adapter_and_keeps_alias(alias):
    router = OCRFixRouter()
    router.configure({
        "llm_api_key": "test-key", "llm_base_url": "https://example.invalid/v1",
        "llm_model_name": "test-model", "llm_provider": "test-provider",
    })
    adapter = router._get_adapter(alias)
    assert isinstance(adapter, OpenAICompatibleFixer)
    assert adapter.is_available
    assert router._get_adapter("openai-compatible") is adapter
    assert router._get_adapter(alias) is adapter
    assert adapter._provider == "test-provider"
    assert adapter.model_name == "test-model"


@pytest.mark.asyncio
async def test_real_rule_fallback_keeps_input_without_ai_calls():
    router = OCRFixRouter()
    router.configure({"ocr_fix_strategy": "manual"})
    result = await router.fix(ocr_text=TEXT)
    assert isinstance(result, OCRFixResult)
    assert result.fixed_text == TEXT
    assert result.model_used == "rule_fallback"
    assert result.metadata["router_call_stats"] == {
        "ai_calls": 0, "llm_calls": 0, "vl_calls": 0, "tokens_used": 0,
    }

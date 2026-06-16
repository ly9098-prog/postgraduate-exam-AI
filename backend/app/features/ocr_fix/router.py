"""OCRFixRouter — 可插拔 OCR 纠错模型路由器。

支持策略：
- manual: 手动选择模型
- auto: Qwen → DeepSeek → rule fallback（默认）

失败自动降级：当前模型失败时按顺序尝试下一个可用模型。
"""

from __future__ import annotations

import logging
from typing import Any

from app.features.ocr_fix.interfaces import OCRFixResult

logger = logging.getLogger(__name__)

# Default fallback chain for "auto" strategy
_AUTO_CHAIN = ["qwen", "deepseek", "rule_fallback"]

# Strategy constants
STRATEGY_MANUAL = "manual"
STRATEGY_AUTO = "auto"


class OCRFixRouter:
    """OCR 纠错模型路由器。

    根据 admin 配置选择模型，支持策略模式和失败自动降级。
    """

    def __init__(self, adapters: dict[str, Any] | None = None):
        """初始化路由器。

        Args:
            adapters: {model_name: fixer_instance} 映射。
              如果不提供，将在首次调用时按需惰性创建。
        """
        self._adapters: dict[str, Any] = {}
        if adapters:
            self._adapters = dict(adapters)
        self._config: dict[str, Any] = {}

    def configure(self, config: dict[str, Any]) -> None:
        """更新路由配置。"""
        self._config = dict(config)

    def register(self, name: str, fixer: Any) -> None:
        """注册适配器。"""
        self._adapters[name] = fixer

    def _get_adapter(self, name: str) -> Any | None:
        """获取适配器，必要时惰性创建。"""
        if name in self._adapters:
            return self._adapters[name]

        # 惰性创建
        if name == "rule_fallback":
            from app.features.ocr_fix.rule_adapter import RuleFixer
            self._adapters[name] = RuleFixer(config=self._config)
            return self._adapters[name]

        if name == "deepseek":
            from app.features.ocr_fix.deepseek_adapter import DeepSeekFixer
            api_key = self._config.get("deepseek_api_key")
            base_url = self._config.get("deepseek_base_url")
            self._adapters[name] = DeepSeekFixer(
                api_key=api_key, base_url=base_url, config=self._config,
            )
            return self._adapters[name]

        if name == "qwen":
            from app.features.ocr_fix.qwen_adapter import QwenFixer
            api_key = self._config.get("qwen_api_key")
            base_url = self._config.get("qwen_base_url")
            model = self._config.get("qwen_model", "qwen-vl-max")
            self._adapters[name] = QwenFixer(
                api_key=api_key, base_url=base_url, model=model, config=self._config,
            )
            return self._adapters[name]

        logger.warning("Unknown OCR fix adapter: %s", name)
        return None

    def _resolve_chain(self) -> list[str]:
        """根据策略解析模型调用链。"""
        strategy = self._config.get("ocr_fix_strategy", STRATEGY_AUTO)

        if strategy == STRATEGY_MANUAL:
            selected = self._config.get("ocr_fix_model", "")
            if selected:
                return [selected]
            return _AUTO_CHAIN[:1]  # 选了一个但为空时走 rule

        # STRATEGY_AUTO
        return list(_AUTO_CHAIN)

    async def fix(
        self,
        image: bytes | None = None,
        ocr_text: str = "",
        context: dict[str, Any] | None = None,
    ) -> OCRFixResult:
        """执行 OCR 纠错，支持自动降级。

        按策略链顺序尝试每个模型，成功后立即返回。
        全部失败后返回原始文本。
        """
        chain = self._resolve_chain()

        last_error: str | None = None

        for model_name in chain:
            adapter = self._get_adapter(model_name)
            if adapter is None:
                continue

            # 跳过不可用的适配器（如无 API key 的 Qwen）
            if hasattr(adapter, "is_available") and not adapter.is_available:
                logger.debug("OCR fix adapter '%s' unavailable, skipping", model_name)
                continue

            try:
                result = await adapter.fix(
                    image=image, ocr_text=ocr_text, context=context,
                )
                if result.fixed_text and not (
                    result.raw_response
                    and isinstance(result.raw_response, str)
                    and result.raw_response.startswith("error:")
                ):
                    logger.info(
                        "OCR fix succeeded with '%s' (conf=%.2f)",
                        model_name, result.confidence or 0,
                    )
                    return result

                # 模型返回了错误
                error_msg = result.raw_response or "empty result"
                logger.warning(
                    "OCR fix '%s' returned error, degrading: %s",
                    model_name, error_msg,
                )
                last_error = error_msg
            except Exception as exc:
                logger.warning("OCR fix '%s' raised, degrading: %s", model_name, exc)
                last_error = str(exc)

        logger.warning(
            "All OCR fix models failed (%s), returning original text",
            " -> ".join(chain),
        )
        return OCRFixResult(
            fixed_text=ocr_text,
            confidence=0.0,
            model_used=f"degraded_{last_error}" if last_error else "degraded_all",
        )

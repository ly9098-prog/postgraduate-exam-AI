"""OCR 纠错指标收集器 — 结构化追踪纠错管线各环节效果。

在 pipeline_orchestrator.correct_ocr_blocks 中集成，
每次导入运行结束时输出一条结构化 JSON 日志行，
支持后续按 model/date/科目 聚合分析纠错趋势。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 独立 logger，方便按 level 或 handler 分流到专用日志文件
metrics_logger = logging.getLogger("ocr_correction_metrics")


@dataclass
class ModelBucket:
    """单个模型的指标桶。"""

    called: int = 0
    succeeded: int = 0  # 模型返回结果
    actually_changed: int = 0  # 结果与输入不同（真正产生效果）
    total_before_chars: int = 0
    total_after_chars: int = 0
    total_duration_ms: int = 0
    total_tokens: int = 0


class OcrCorrectionMetrics:
    """一次导入管线的 OCR 纠错指标收集器。

    用法:
        metrics = OcrCorrectionMetrics()
        metrics.record_classification(total=50, noisy=12, skipped=38)
        metrics.record_correction(model="paddleocr-vl", before=text, after=fixed,
                                  duration_ms=1200, tokens=450)
        metrics.record_unchanged(model="openai-compatible", before=text)
        metrics.record_failure(model="paddleocr-vl", error="timeout")
        metrics.flush()  # 输出结构化 JSON 日志行
    """

    def __init__(self) -> None:
        self._start_time = time.monotonic()
        self.total_blocks: int = 0
        self.noisy_blocks: int = 0
        self.skipped_blocks: int = 0
        self.corrected_blocks: int = 0
        self.unchanged_blocks: int = 0
        self.failed_blocks: int = 0
        self.total_before_chars: int = 0
        self.total_after_chars: int = 0
        self.model_buckets: dict[str, ModelBucket] = {}

    def record_classification(self, *, total: int, noisy: int, skipped: int) -> None:
        self.total_blocks = total
        self.noisy_blocks = noisy
        self.skipped_blocks = skipped

    def _get_bucket(self, model: str) -> ModelBucket:
        key = model.split("_")[0] if "_" in model else model
        if key not in self.model_buckets:
            self.model_buckets[key] = ModelBucket()
        return self.model_buckets[key]

    def record_correction(
        self,
        *,
        model: str,
        before: str,
        after: str,
        duration_ms: int | None = None,
        tokens: int | None = None,
    ) -> None:
        b = self._get_bucket(model)
        b.called += 1
        b.succeeded += 1
        b.actually_changed += 1
        b.total_before_chars += len(before)
        b.total_after_chars += len(after)
        if duration_ms is not None:
            b.total_duration_ms += duration_ms
        if tokens is not None:
            b.total_tokens += tokens

        self.corrected_blocks += 1
        self.total_before_chars += len(before)
        self.total_after_chars += len(after)

    def record_unchanged(self, *, model: str, before: str) -> None:
        b = self._get_bucket(model)
        b.called += 1
        b.succeeded += 1
        b.total_before_chars += len(before)
        b.total_after_chars += len(before)

        self.unchanged_blocks += 1
        self.total_before_chars += len(before)
        self.total_after_chars += len(before)

    def record_failure(self, *, model: str, before: str) -> None:
        b = self._get_bucket(model)
        b.called += 1
        b.total_before_chars += len(before)

        self.failed_blocks += 1
        self.total_before_chars += len(before)
        self.total_after_chars += len(before)

    def summary(self) -> dict:
        elapsed_ms = (time.monotonic() - self._start_time) * 1000
        total_called = sum(b.called for b in self.model_buckets.values())
        total_changed = sum(b.actually_changed for b in self.model_buckets.values())

        return {
            "total_blocks": self.total_blocks,
            "noisy_blocks": self.noisy_blocks,
            "skipped_blocks": self.skipped_blocks,
            "corrected_blocks": self.corrected_blocks,
            "unchanged_blocks": self.unchanged_blocks,
            "failed_blocks": self.failed_blocks,
            "total_called": total_called,
            "total_changed": total_changed,
            "total_before_chars": self.total_before_chars,
            "total_after_chars": self.total_after_chars,
            "char_delta": self.total_after_chars - self.total_before_chars,
            "char_change_ratio": round(
                abs(self.total_after_chars - self.total_before_chars)
                / max(self.total_before_chars, 1),
                4,
            ),
            "models": {
                name: {
                    "called": b.called,
                    "succeeded": b.succeeded,
                    "actually_changed": b.actually_changed,
                    "change_rate": round(
                        b.actually_changed / max(b.called, 1),
                        3,
                    ),
                    "avg_duration_ms": round(b.total_duration_ms / max(b.called, 1)),
                    "total_tokens": b.total_tokens,
                    "avg_chars_before": round(b.total_before_chars / max(b.called, 1)),
                    "avg_chars_after": round(b.total_after_chars / max(b.called, 1)),
                }
                for name, b in self.model_buckets.items()
            },
            "elapsed_ms": round(elapsed_ms),
        }

    def flush(self, extra: dict | None = None) -> None:
        """输出一条结构化 JSON 日志行。"""
        payload = self.summary()
        if extra:
            payload["extra"] = extra
        metrics_logger.info(
            "OCR_CORRECTION_METRICS %s", json.dumps(payload, ensure_ascii=False)
        )

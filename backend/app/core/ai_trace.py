"""AI edit trace — 统一 AI 修改追踪。

Extracted from app.features.ai_safety to separate tracing concerns
from safety evaluation. This module contains the data class only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AIEditTrace:
    """统一的 AI 修改记录。"""

    stage: str  # "ocr_fix" / "ai_repair" / "ai_complete" / "ai_enrich"
    model: str  # "paddleocr-vl" / "deepseek" / "rule_fallback" ...
    before: str  # 修改前文本（截断到 2000 字符）
    after: str  # 修改后文本（截断到 2000 字符）
    diff: str = ""  # unified diff 摘要
    risk_flags: list[str] = field(default_factory=list)
    accepted: bool = True
    rollback_reason: str | None = None
    tokens_used: int = 0
    duration_ms: int = 0
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "model": self.model,
            "before": self.before[:500],
            "after": self.after[:500],
            "diff": self.diff[:300],
            "risk_flags": self.risk_flags,
            "accepted": self.accepted,
            "rollback_reason": self.rollback_reason,
            "tokens_used": self.tokens_used,
            "duration_ms": self.duration_ms,
        }

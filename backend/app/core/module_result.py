"""ModuleResult 统一契约 — 所有管线阶段的通用输出 envelope。

提供：
- ModuleError: 结构化错误信息
- ModuleResult[T]: 泛型阶段输出，包含数据、置信度、原始响应、性能指标
- AdapterCapabilities: 适配器能力声明
- raw 数据 100KB 截断与敏感字段脱敏
- 数据 codec：encode/decode 保证 typed round-trip

规则：
- ``ModuleResult.success()`` / ``.failure()`` 构造器保证合法状态
- 非法状态构造触发 ``ValueError``
- ``CancelledError`` / ``KeyboardInterrupt`` / ``SystemExit`` 不得被吞掉
- raw 先脱敏再截断，截断后仍为合法 JSON
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCHEMA_VERSION = "1.0"
_RAW_MAX_BYTES = 100 * 1024  # 100 KB
_RAW_CAPTURE_MODE = os.environ.get("MODULE_RAW_CAPTURE_MODE", "always")  # off | errors_only | always
_DETAILS_MAX_BYTES = 10 * 1024  # 10 KB for error details and warnings

# Sensitive field name patterns (case-insensitive, checked against key & value)
_SENSITIVE_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\btoken\b",
        r"\bauthorization\b",
        r"\bcookie[s]?\b",
        r"\bapi[_-]?key\b",
        r"\bsecret\b",
        r"\bpassword\b",
        r"\bcredential[s]?\b",
        r"\baccess[_-]?key\b",
        r"\bsignature\b",
        r"\bprivate[_-]?key\b",
        r"\brefresh[_-]?token\b",
        r"\bsession[_-]?id\b",
    ]
]

# ---------------------------------------------------------------------------
# Type vars and codec registry
# ---------------------------------------------------------------------------

T = TypeVar("T")

DATA_CODECS: dict[str, tuple[Callable[[Any], dict], Callable[[dict], Any]]] = {}
"""Registry of (encoder, decoder) for known data_type values.

Called by ``ModuleResult.encode()`` / ``ModuleResult.decode()``.
"""


def register_codec(
    type_name: str,
    encoder: Callable[[Any], dict],
    decoder: Callable[[dict], Any],
) -> None:
    """Register a data type codec for ``ModuleResult`` encode/decode."""
    DATA_CODECS[type_name] = (encoder, decoder)


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


@dataclass
class ModuleError:
    """结构化错误信息。

    ``code`` — 机器可读错误码，如 ``"OCR_TIMEOUT"``、``"ADAPTER_OUTPUT_INVALID"``
    ``message`` — 人类可读描述
    ``category`` — ``"input"`` | ``"output"`` | ``"model"`` | ``"system"`` | ``"network"``
    ``recoverable`` — 是否可降级继续
    ``retryable`` — 重试是否可能成功
    ``retry_after_ms`` — 建议重试间隔（毫秒）
    ``upstream_status`` — 上游 HTTP 状态码
    ``debug_reference`` — traceback / 错误 ID / 调试链接
    ``details`` — 额外上下文（递归脱敏，限长）

    **不可重试的异常**：``CancelledError``、``KeyboardInterrupt``、``SystemExit``
    不得被此 dataclass 包装或吞掉。
    """
    code: str
    message: str
    category: str = "system"
    recoverable: bool = False
    retryable: bool = False
    retry_after_ms: int | None = None
    upstream_status: int | None = None
    debug_reference: str | None = None
    details: dict | None = None

    def __post_init__(self) -> None:
        if self.details is not None:
            sanitize_and_truncate_dict(self.details, max_bytes=_DETAILS_MAX_BYTES)


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdapterCapabilities:
    """适配器能力声明。

    所有列表字段使用 ``tuple``（不可变），避免字符串漂移。
    """
    backend: str
    adapter_type: str  # "ocr" | "transform"

    # === OCR 能力 ===
    text: bool = False
    bbox: bool = False
    polygon: bool = False
    layout: bool = False
    reading_order: bool = False
    table: bool = False
    formula: bool = False
    code: bool = False
    per_line_confidence: bool = False
    offline: bool = False

    # 布局标签和区域类型
    layout_labels: tuple[str, ...] = field(default_factory=tuple)
    region_types: tuple[str, ...] = field(default_factory=tuple)

    # === 输入能力 ===
    supported_mime_types: tuple[str, ...] = field(default_factory=lambda: ("application/pdf", "image/png"))
    supported_devices: tuple[str, ...] = field(default_factory=lambda: ("cpu",))
    multipage: bool = False
    max_batch: int = 1
    max_pages: int = 200
    max_input_bytes: int = 100 * 1024 * 1024  # 100 MB
    requires_network: bool = False
    thread_safe: bool = False
    process_safe: bool = False
    max_concurrency: int = 1


# ---------------------------------------------------------------------------
# Raw sanitizer — 递归脱敏 + 限长截断
# ---------------------------------------------------------------------------


def _is_sensitive_key(key: str) -> bool:
    """Check if a dict key matches a sensitive pattern."""
    return any(p.search(key) for p in _SENSITIVE_PATTERNS)


def _is_sensitive_value(value: str) -> bool:
    """Check if a string value matches a sensitive pattern."""
    return any(p.search(value) for p in _SENSITIVE_PATTERNS)


def _sanitize_value(value: Any, depth: int = 0) -> Any:
    """Recursively sanitize a value, replacing sensitive fields with [REDACTED].

    ``depth`` bounds recursion to avoid stack overflow on deeply nested input.
    """
    if depth > 20:
        return str(value)[:200] if not isinstance(value, (int, float, bool, type(None))) else value

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for k, v in value.items():
            if _is_sensitive_key(k):
                result[k] = "[REDACTED]"
            elif isinstance(v, str) and _is_sensitive_value(v):
                result[k] = "[REDACTED]"
            else:
                result[k] = _sanitize_value(v, depth + 1)
        return result

    if isinstance(value, list):
        return [_sanitize_value(item, depth + 1) for item in value]

    if isinstance(value, str):
        if _is_sensitive_value(value):
            return "[REDACTED]"
        return value

    return value


def _truncate_string_values(obj: Any, max_total_bytes: int = _RAW_MAX_BYTES, max_str_len: int = 5000) -> tuple[Any, bool]:
    """Truncate large string values in a dict to fit within max_total_bytes when serialized.

    Returns ``(truncated_obj, was_truncated)``.
    The result is always valid JSON-serializable.
    """
    if isinstance(obj, dict):
        result: dict[str, Any] = {}
        was_truncated = False
        for k, v in obj.items():
            if isinstance(v, str) and len(v) > max_str_len:
                result[k] = v[:max_str_len] + f"...(truncated from {len(v)} chars)"
                was_truncated = True
            elif isinstance(v, (dict, list)):
                result[k], sub_truncated = _truncate_string_values(v, max_total_bytes, max_str_len)
                was_truncated = was_truncated or sub_truncated
            else:
                result[k] = v
        return result, was_truncated

    if isinstance(obj, list):
        result_list: list[Any] = []
        was_truncated = False
        for item in obj:
            if isinstance(item, (dict, list)):
                result_list.append(_truncate_string_values(item, max_total_bytes, max_str_len)[0])
            elif isinstance(item, str) and len(item) > max_str_len:
                result_list.append(item[:max_str_len] + f"...(truncated from {len(item)} chars)")
                was_truncated = True
            else:
                result_list.append(item)
        return result_list, was_truncated

    return obj, False


def _truncate_json_to_max_bytes(obj: Any, max_bytes: int = _RAW_MAX_BYTES) -> tuple[Any, str | None, bool]:
    """Sanitize, size-check, and truncate an object to max_bytes.

    Strategy: truncate large string values iteratively until the serialized
    form fits within ``max_bytes``.  The returned object is always valid JSON.

    Returns ``(sanitized_obj, sha256_hex, was_truncated)``.
    """
    # Step 1: sanitize (redact sensitive fields)
    sanitized = _sanitize_value(obj)

    # Step 2: serialize to compute full SHA256
    full_json = json.dumps(sanitized, ensure_ascii=False, default=str, sort_keys=True)
    sha256_hex = hashlib.sha256(full_json.encode("utf-8")).hexdigest()

    # Step 3: check size
    if len(full_json) <= max_bytes:
        return sanitized, sha256_hex, False

    # Step 4: iteratively truncate string values until under limit
    max_str_len = 5000
    truncated_obj, _ = _truncate_string_values(sanitized, max_bytes, max_str_len)

    # Re-check size
    truncated_json = json.dumps(truncated_obj, ensure_ascii=False, default=str, sort_keys=True)

    while len(truncated_json) > max_bytes and max_str_len > 100:
        max_str_len //= 2
        truncated_obj, _ = _truncate_string_values(sanitized, max_bytes, max_str_len)
        truncated_json = json.dumps(truncated_obj, ensure_ascii=False, default=str, sort_keys=True)

    # If still too large, prune keys
    if len(truncated_json) > max_bytes and isinstance(truncated_obj, dict):
        # Keep only first 10 keys with truncated values
        pruned: dict[str, Any] = {}
        for i, (k, v) in enumerate(list(truncated_obj.items())[:10]):
            pruned[k] = v
        pruned["_truncated_keys"] = len(truncated_obj) - 10
        truncated_obj = pruned

    return truncated_obj, sha256_hex, True


def sanitize_and_truncate_dict(
    d: dict[str, Any],
    max_bytes: int = _RAW_MAX_BYTES,
) -> None:
    """Sanitize and truncate a dict in-place.

    ``max_bytes`` limit is applied to the JSON serialization of each value.
    String values exceeding max_bytes are truncated individually.
    """
    for k, v in list(d.items()):
        if _is_sensitive_key(k) or (isinstance(v, str) and _is_sensitive_value(v)):
            d[k] = "[REDACTED]"
        elif isinstance(v, str) and len(v) > max_bytes:
            sha = hashlib.sha256(v.encode("utf-8")).hexdigest()[:16]
            d[k] = v[:max_bytes] + f"...(truncated, sha256:{sha})"


# ---------------------------------------------------------------------------
# Main result type
# ---------------------------------------------------------------------------


@dataclass
class ModuleResult(Generic[T]):
    """泛型模块输出。

    **构造器**：
    - ``ModuleResult.success(data, ...)`` — data 非 None、error 为 None
    - ``ModuleResult.failure(error, ...)`` — error 非 None、data 为 None

    **非法状态**：
    - 成功时 data 为 None → ``ValueError``
    - 失败时 error 为 None → ``ValueError``
    - confidence 不在 [0, 1] → ``ValueError``
    - latency_ms 为负 → ``ValueError``
    """
    # 标识
    module_name: str = ""
    module_version: str = "0.1.0"
    schema_version: str = _SCHEMA_VERSION

    # 数据
    data: T | None = None
    data_type: str = ""
    data_schema_version: str = ""
    confidence: float | None = None
    confidence_scope: str = "global"
    confidence_method: str = "average"

    # 原始响应
    raw: dict | None = None
    raw_sha256: str | None = None
    raw_truncated: bool = False

    # 错误 / 警告
    error: ModuleError | None = None
    warnings: list[str] = field(default_factory=list)

    # 来源追踪
    trace_id: str = ""
    model_fingerprint: str | None = None
    component_fingerprint: str = ""
    backend: str = ""

    # 性能
    latency_ms: float = 0.0

    # ── computed at construction ──
    _captured_at: float = 0.0

    def __post_init__(self) -> None:
        # Validate state invariants
        self._validate_state()

        # Auto-capture timestamp
        if not self._captured_at:
            object.__setattr__(self, "_captured_at", time.time())

        # Raw sanitization
        if self.raw is not None and _RAW_CAPTURE_MODE == "always":
            self._sanitize_raw()
        elif self.raw is not None and _RAW_CAPTURE_MODE == "errors_only" and self.error is not None:
            self._sanitize_raw()

    def _validate_state(self) -> None:
        """Validate ModuleResult invariants."""
        if self.data is not None and self.error is not None:
            raise ValueError("ModuleResult: data and error cannot both be non-None")
        if self.data is None and self.error is None:
            raise ValueError("ModuleResult: either data or error must be non-None")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"ModuleResult: confidence must be in [0, 1], got {self.confidence}")
        if self.latency_ms < 0:
            raise ValueError(f"ModuleResult: latency_ms must be >= 0, got {self.latency_ms}")

    def _sanitize_raw(self) -> None:
        """Apply sanitization, truncation, and SHA256 to raw."""
        sanitized, sha256_hex, truncated = _truncate_json_to_max_bytes(self.raw, _RAW_MAX_BYTES)
        object.__setattr__(self, "raw", sanitized)
        object.__setattr__(self, "raw_sha256", sha256_hex)
        object.__setattr__(self, "raw_truncated", truncated)

    # ── Constructors ──

    @classmethod
    def success(
        cls,
        data: T,
        *,
        module_name: str = "",
        module_version: str = "0.1.0",
        data_type: str = "",
        data_schema_version: str = "",
        confidence: float | None = None,
        confidence_scope: str = "global",
        confidence_method: str = "average",
        raw: dict | None = None,
        warnings: list[str] | None = None,
        trace_id: str = "",
        model_fingerprint: str | None = None,
        component_fingerprint: str = "",
        backend: str = "",
        latency_ms: float = 0.0,
    ) -> ModuleResult[T]:
        """Create a successful ModuleResult. ``data`` must be non-None."""
        if data is None:
            raise ValueError("ModuleResult.success(): data must be non-None")
        return cls(
            data=data,
            data_type=data_type or type(data).__name__,
            data_schema_version=data_schema_version,
            confidence=confidence,
            confidence_scope=confidence_scope,
            confidence_method=confidence_method,
            raw=raw,
            warnings=warnings or [],
            trace_id=trace_id,
            model_fingerprint=model_fingerprint,
            component_fingerprint=component_fingerprint,
            backend=backend,
            latency_ms=latency_ms,
            module_name=module_name,
            module_version=module_version,
        )

    @classmethod
    def failure(
        cls,
        error: ModuleError,
        *,
        module_name: str = "",
        module_version: str = "0.1.0",
        raw: dict | None = None,
        trace_id: str = "",
        model_fingerprint: str | None = None,
        component_fingerprint: str = "",
        backend: str = "",
        latency_ms: float = 0.0,
    ) -> ModuleResult[T]:
        """Create a failed ModuleResult. ``error`` must be non-None."""
        if error is None:
            raise ValueError("ModuleResult.failure(): error must be non-None")

        # Capture raw only in errors_only mode when error is present
        result = cls(
            data=None,
            error=error,
            raw=raw,
            warnings=[],
            trace_id=trace_id,
            model_fingerprint=model_fingerprint,
            component_fingerprint=component_fingerprint,
            backend=backend,
            latency_ms=latency_ms,
            module_name=module_name,
            module_version=module_version,
        )

        return result

    # ── Accessors ──

    @property
    def is_success(self) -> bool:
        return self.data is not None and self.error is None

    @property
    def is_failure(self) -> bool:
        return self.data is None and self.error is not None

    # ── Codec ──

    def encode(self) -> dict[str, Any]:
        """Serialize ModuleResult to a JSON-compatible dict.

        Data is encoded using the registered codec for ``data_type``.
        """
        encoded: dict[str, Any] = {
            "module_name": self.module_name,
            "module_version": self.module_version,
            "schema_version": self.schema_version,
            "data_type": self.data_type,
            "data_schema_version": self.data_schema_version,
            "confidence": self.confidence,
            "confidence_scope": self.confidence_scope,
            "confidence_method": self.confidence_method,
            "raw": self.raw,
            "raw_sha256": self.raw_sha256,
            "raw_truncated": self.raw_truncated,
            "warnings": list(self.warnings),
            "trace_id": self.trace_id,
            "model_fingerprint": self.model_fingerprint,
            "component_fingerprint": self.component_fingerprint,
            "backend": self.backend,
            "latency_ms": self.latency_ms,
        }

        # Encode data using registered codec
        if self.data is not None and self.data_type in DATA_CODECS:
            encoder, _ = DATA_CODECS[self.data_type]
            encoded["data"] = encoder(self.data)
        elif self.data is not None:
            # Fallback: use to_dict() or dataclass fields
            if hasattr(self.data, "to_dict"):
                encoded["data"] = self.data.to_dict()
            elif hasattr(self.data, "__dataclass_fields__"):
                encoded["data"] = {
                    f: getattr(self.data, f)
                    for f in self.data.__dataclass_fields__
                }
            else:
                encoded["data"] = str(self.data)
        else:
            encoded["data"] = None

        # Encode error
        if self.error is not None:
            encoded["error"] = {
                "code": self.error.code,
                "message": self.error.message,
                "category": self.error.category,
                "recoverable": self.error.recoverable,
                "retryable": self.error.retryable,
                "retry_after_ms": self.error.retry_after_ms,
                "upstream_status": self.error.upstream_status,
                "debug_reference": self.error.debug_reference,
                "details": self.error.details,
            }
        else:
            encoded["error"] = None

        return encoded

    @staticmethod
    def decode(data: dict[str, Any]) -> ModuleResult[Any]:
        """Deserialize a dict back to ModuleResult.

        Data is decoded using the registered codec for ``data_type``.
        """
        # Decode error
        error_data = data.get("error")
        error: ModuleError | None = None
        if error_data:
            error = ModuleError(
                code=error_data.get("code", "UNKNOWN"),
                message=error_data.get("message", ""),
                category=error_data.get("category", "system"),
                recoverable=error_data.get("recoverable", False),
                retryable=error_data.get("retryable", False),
                retry_after_ms=error_data.get("retry_after_ms"),
                upstream_status=error_data.get("upstream_status"),
                debug_reference=error_data.get("debug_reference"),
                details=error_data.get("details"),
            )

        # Decode data
        data_type = data.get("data_type", "")
        raw_data = data.get("data")
        decoded_data: Any = None
        if raw_data is not None and data_type in DATA_CODECS:
            _, decoder = DATA_CODECS[data_type]
            decoded_data = decoder(raw_data)
        elif raw_data is not None:
            decoded_data = raw_data  # keep as dict if no codec registered

        result = ModuleResult(
            module_name=data.get("module_name", ""),
            module_version=data.get("module_version", "0.1.0"),
            schema_version=data.get("schema_version", _SCHEMA_VERSION),
            data=decoded_data,
            data_type=data_type,
            data_schema_version=data.get("data_schema_version", ""),
            confidence=data.get("confidence"),
            confidence_scope=data.get("confidence_scope", "global"),
            confidence_method=data.get("confidence_method", "average"),
            raw=data.get("raw"),
            raw_sha256=data.get("raw_sha256"),
            raw_truncated=data.get("raw_truncated", False),
            error=error,
            warnings=data.get("warnings", []),
            trace_id=data.get("trace_id", ""),
            model_fingerprint=data.get("model_fingerprint"),
            component_fingerprint=data.get("component_fingerprint", ""),
            backend=data.get("backend", ""),
            latency_ms=data.get("latency_ms", 0.0),
        )
        # Bypass __post_init__ validation for reconstructed objects
        object.__setattr__(result, "_captured_at", data.get("_captured_at", 0.0))
        return result

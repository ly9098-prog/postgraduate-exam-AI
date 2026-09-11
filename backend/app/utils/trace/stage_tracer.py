"""
Per-question execution trace for the OCR normalization pipeline.

StageTracer wraps each sub-stage in normalize_question() to record:
- stage name, strategy, data lineage (input_source, parent_stage)
- input/output previews and token-level delta
- timing (duration_ms)
- corruption detection with causal chain tracking
- options recovery path reasoning

Design principle: transparent pass-through — trace recording is pure side-effect
with zero impact on return values.
"""

import difflib
import re
import time
from collections.abc import Callable
from typing import Any

_RE_STANDALONE_TOKEN = re.compile(r"(?<!\w)([ABCD])(?!\w)")
_RE_BROKEN_ARROW_DASH = re.compile(r"[−–—]\s*>")


def _preview(data: Any, max_len: int = 200) -> str:
    if data is None:
        return ""
    text = str(data)
    if len(text) > max_len:
        return text[:max_len] + f"...[+{len(text) - max_len}]"
    return text


def _compute_delta(inp: Any, out: Any) -> dict:
    """Token-level diff between input and output strings.

    Returns:
        dict with added_tokens, removed_tokens, modified_regions, has_changed.
    """
    delta: dict = {
        "added_tokens": [],
        "removed_tokens": [],
        "modified_regions": [],
        "has_changed": False,
    }
    if inp is None or out is None:
        return delta
    str_in = str(inp)
    str_out = str(out)
    if str_in == str_out:
        return delta
    delta["has_changed"] = True

    # Tokenize by whitespace (respecting punctuation boundaries)
    in_tokens = _tokenize(str_in)
    out_tokens = _tokenize(str_out)

    matcher = difflib.SequenceMatcher(None, in_tokens, out_tokens)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "insert":
            delta["added_tokens"].extend(out_tokens[j1:j2])
        elif op == "delete":
            delta["removed_tokens"].extend(in_tokens[i1:i2])
        elif op == "replace":
            delta["modified_regions"].append(
                {
                    "before": " ".join(in_tokens[i1:i2]),
                    "after": " ".join(out_tokens[j1:j2]),
                }
            )

    # Remove duplicates while preserving order
    delta["added_tokens"] = list(dict.fromkeys(delta["added_tokens"]))
    delta["removed_tokens"] = list(dict.fromkeys(delta["removed_tokens"]))
    return delta


def _tokenize(text: str) -> list[str]:
    """Split text into tokens on whitespace, stripping punctuation boundaries."""
    return re.findall(r"[^\s]+", text)


class StageTracer:
    """Records execution trace for one question through the normalization pipeline.

    Usage:
        tracer = StageTracer(raw_text)
        result = tracer.run("ocr_quality_gate", "rule", "raw_ocr", None,
                            _run_ocr_quality_gate, raw_text)
        tracer.add_note("stem_extraction", "stem length=120", "raw_ocr", "ocr_quality_gate")
        tracer.mark_corruption("stem", "c_token_noise", "Standalone 'C' at pos 5")
        tracer.mark_options_recovery("options", "raw_scan", 4, 1.0)
    """

    def __init__(self, raw_text: str = ""):
        self.entries: list[dict] = []
        # Corruption registry for causal chain tracking:
        # {corruption_type: {"origin_stage": str, "propagation_path": list, "resolved_at": str, "resolved_by": str}}
        self._corruption_registry: dict[str, dict] = {}

        if raw_text:
            self.entries.append(
                {
                    "stage": "ocr_raw_input",
                    "strategy": "passthrough",
                    "input_source": "raw_ocr",
                    "parent_stage": None,
                    "input_preview": _preview(raw_text),
                    "output_preview": _preview(raw_text),
                    "status": "observed",
                    "duration_ms": 0,
                    "delta": {
                        "added_tokens": [],
                        "removed_tokens": [],
                        "modified_regions": [],
                        "has_changed": False,
                    },
                    "notes": f"raw_text length={len(raw_text)}",
                }
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        stage: str,
        strategy: str,
        input_source: str,
        parent_stage: str | None,
        func: Callable,
        input_data: Any = None,
        **kwargs,
    ) -> Any:
        """Execute func with tracing. Returns func's output unchanged.

        Args:
            stage: Stage name (e.g., "ocr_quality_gate", "noise_filtering").
            strategy: One of "rule", "regex", "llm", "fallback", "pipeline".
            input_source: Data origin — "raw_ocr", "stem", "intermediate", "fallback", "final".
            parent_stage: Name of the previous processing stage, or None for the first stage.
            func: The callable to execute.
            input_data: Primary input to func (passed as first positional arg).
            **kwargs: Additional keyword arguments forwarded to func.

        Returns:
            Whatever func returns (pass-through, no modification).
        """
        entry = self._make_entry(
            stage, strategy, input_source, parent_stage, input_data
        )
        start = time.monotonic()
        try:
            output = func(input_data, **kwargs) if kwargs else func(input_data)
            entry["status"] = "success"
            entry["output_preview"] = _preview(output)
            entry["delta"] = _compute_delta(input_data, output)
        except Exception as exc:
            entry["status"] = "failed"
            entry["notes"] = str(exc)
            raise
        finally:
            entry["duration_ms"] = round((time.monotonic() - start) * 1000, 2)
        self.entries.append(entry)
        return output

    def add_note(
        self,
        stage: str,
        notes: str,
        input_source: str = "intermediate",
        parent_stage: str | None = None,
        strategy: str = "observation",
    ) -> None:
        """Record an observation about a stage without wrapping a function call."""
        self.entries.append(
            {
                "stage": stage,
                "strategy": strategy,
                "input_source": input_source,
                "parent_stage": parent_stage,
                "input_preview": "",
                "output_preview": "",
                "status": "info",
                "duration_ms": 0,
                "delta": {
                    "added_tokens": [],
                    "removed_tokens": [],
                    "modified_regions": [],
                    "has_changed": False,
                },
                "notes": notes,
            }
        )

    def mark_corruption(
        self,
        stage: str,
        corruption_type: str,
        detail: str,
        strategy: str = "detection",
    ) -> None:
        """Record a corruption finding with automatic causal chain tracking.

        Tracks where each corruption type originates, propagates, and is resolved.
        """
        # Update causal chain registry
        if corruption_type not in self._corruption_registry:
            # First occurrence — record as origin
            self._corruption_registry[corruption_type] = {
                "origin_stage": stage,
                "propagation_path": [],
                "resolved_at": None,
                "resolved_by": None,
            }
        elif self._corruption_registry[corruption_type].get("resolved_at") is not None:
            # Was resolved but reappeared — reset origin
            self._corruption_registry[corruption_type] = {
                "origin_stage": stage,
                "propagation_path": [],
                "resolved_at": None,
                "resolved_by": None,
            }
        else:
            # Propagating — add to path if not already last entry
            path = self._corruption_registry[corruption_type]["propagation_path"]
            if not path or path[-1] != stage:
                path.append(stage)

        registry = self._corruption_registry[corruption_type]

        entry = {
            "stage": stage,
            "strategy": strategy,
            "input_source": "intermediate",
            "parent_stage": None,
            "input_preview": "",
            "output_preview": "",
            "status": "corruption",
            "duration_ms": 0,
            "delta": {
                "added_tokens": [],
                "removed_tokens": [],
                "modified_regions": [],
                "has_changed": False,
            },
            "corruption_type": corruption_type,
            "origin_stage": registry["origin_stage"],
            "propagation_path": list(registry["propagation_path"]),
            "resolved_at": None,
            "resolved_by": None,
            "notes": detail,
        }
        self.entries.append(entry)

    def mark_corruption_resolved(
        self,
        stage: str,
        corruption_type: str,
        resolved_by: str,
        detail: str = "",
    ) -> None:
        """Record that a previously-tracked corruption was resolved at this stage."""
        registry = self._corruption_registry.get(corruption_type)
        if registry is None:
            # Corruption was never tracked — just record the resolution
            self._corruption_registry[corruption_type] = {
                "origin_stage": "unknown",
                "propagation_path": [],
                "resolved_at": stage,
                "resolved_by": resolved_by,
            }
            registry = self._corruption_registry[corruption_type]
        else:
            registry["resolved_at"] = stage
            registry["resolved_by"] = resolved_by

        self.entries.append(
            {
                "stage": stage,
                "strategy": "detection",
                "input_source": "intermediate",
                "parent_stage": None,
                "input_preview": "",
                "output_preview": "",
                "status": "resolved",
                "duration_ms": 0,
                "delta": {
                    "added_tokens": [],
                    "removed_tokens": [],
                    "modified_regions": [],
                    "has_changed": False,
                },
                "corruption_type": corruption_type,
                "origin_stage": registry["origin_stage"],
                "propagation_path": list(registry["propagation_path"]),
                "resolved_at": stage,
                "resolved_by": resolved_by,
                "notes": detail
                or f"Corruption '{corruption_type}' resolved by {resolved_by}",
            }
        )

    def mark_options_recovery(
        self,
        stage: str,
        origin: str,
        option_count: int,
        confidence: float,
        failure_reason: str | None = None,
    ) -> None:
        """Record where/how options were recovered.

        Args:
            stage: Stage name (typically "options_extraction").
            origin: Recovery origin — "raw_scan", "regex", "fallback", "llm".
            option_count: Number of options recovered (0-4).
            confidence: Confidence in the recovery (0.0-1.0).
            failure_reason: Why primary strategy failed (e.g. "missing_option_D"), or None.
        """
        self.entries.append(
            {
                "stage": stage,
                "strategy": "options_trace",
                "input_source": "intermediate",
                "parent_stage": None,
                "input_preview": "",
                "output_preview": "",
                "status": "info",
                "duration_ms": 0,
                "delta": {
                    "added_tokens": [],
                    "removed_tokens": [],
                    "modified_regions": [],
                    "has_changed": False,
                },
                "options_found_in": origin,
                "options_origin": origin,
                "options_confidence": round(confidence, 2),
                "options_failure_reason": failure_reason,
                "note": f"option_count={option_count}",
            }
        )

    def scan_text_corruptions(self, text: str, source_label: str) -> list[dict]:
        """Scan text for known corruption patterns.

        Returns list of {type, detail, source} dicts for each finding.
        """
        findings: list[dict] = []
        if not text:
            return findings

        # Standalone C/B/A/D tokens (potential noise)
        for match in _RE_STANDALONE_TOKEN.finditer(text):
            token = match.group(1)
            findings.append(
                {
                    "type": f"{token.lower()}_token_noise",
                    "detail": f"Standalone '{token}' token at pos {match.start()}",
                    "source": source_label,
                }
            )

        # Broken -> arrow (dash variants like − > or – >)
        if _RE_BROKEN_ARROW_DASH.search(text):
            findings.append(
                {
                    "type": "broken_arrow_dash",
                    "detail": "Arrow '->' appears as dash variant (e.g., '− >')",
                    "source": source_label,
                }
            )

        return findings

    @property
    def has_corruptions(self) -> bool:
        return bool(self._corruption_registry)

    @property
    def corruption_summary(self) -> list[dict]:
        """Return a summary of all tracked corruptions with their causal chains."""
        return [
            {
                "corruption_type": ctype,
                "origin_stage": reg["origin_stage"],
                "propagation_path": reg["propagation_path"],
                "resolved_at": reg["resolved_at"],
                "resolved_by": reg["resolved_by"],
            }
            for ctype, reg in self._corruption_registry.items()
        ]

    def to_list(self) -> list[dict]:
        """Return all recorded trace entries."""
        return self.entries

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_entry(
        self,
        stage: str,
        strategy: str,
        input_source: str,
        parent_stage: str | None,
        input_data: Any,
    ) -> dict:
        return {
            "stage": stage,
            "strategy": strategy,
            "input_source": input_source,
            "parent_stage": parent_stage,
            "input_preview": _preview(input_data),
            "output_preview": "",
            "status": "running",
            "duration_ms": 0,
            "delta": {
                "added_tokens": [],
                "removed_tokens": [],
                "modified_regions": [],
                "has_changed": False,
            },
            "notes": "",
        }

"""AI OCR Correction Layer — 在结构分析前对 OCR 文本块进行 AI 辅助纠错。

位于 normalize_text 之后、analyze_structure 之前。
仅在检测到 OCR 噪声信号时触发，按 block 逐块纠错。
AI 不可用或 token 超限时静默降级。
"""

import re
import time

_VALID_OPTION_MARKERS = re.compile(r"^[A-D][.、．）)\s]", re.MULTILINE)
_QUESTION_NUM_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:\d{1,3}|第[一二三四五六七八九十百]+题)[.、．）)【\s]",
)
_GARBLED_CHARS = re.compile(r"[�□█░-▓\x00-\x08\x0e-\x1f]")
_SHORT_LINE_THRESHOLD = 5

# ---------------------------------------------------------------------------
# Token budget (process-level, independent from ai_repair)
# ---------------------------------------------------------------------------

_token_usage: dict[str, int | str] = {
    "daily": 0, "monthly": 0, "daily_date": "", "monthly_month": "",
}


def _estimate_tokens(text: str) -> int:
    chinese = len(re.findall(r"[一-鿿]", text))
    return int(chinese * 1.3 + (len(text) - chinese) * 0.3)


def _reset_counters_if_needed():
    today = time.strftime("%Y-%m-%d")
    month = time.strftime("%Y-%m")
    if _token_usage["daily_date"] != today:
        _token_usage["daily"] = 0
        _token_usage["daily_date"] = today
    if _token_usage["monthly_month"] != month:
        _token_usage["monthly"] = 0
        _token_usage["monthly_month"] = month


def _check_token_limit(estimated_tokens: int, config: dict) -> bool:
    _reset_counters_if_needed()
    daily_limit = config.get("daily_token_limit", 50000)
    monthly_limit = config.get("monthly_token_limit", 1000000)
    if int(_token_usage["daily"]) + estimated_tokens > daily_limit:
        return False
    if int(_token_usage["monthly"]) + estimated_tokens > monthly_limit:
        return False
    return True
def _record_token_usage(tokens: int):
    _reset_counters_if_needed()
    _token_usage["daily"] = int(_token_usage["daily"]) + tokens
    _token_usage["monthly"] = int(_token_usage["monthly"]) + tokens


# ---------------------------------------------------------------------------
# Noise detection
# ---------------------------------------------------------------------------


def _detect_noise(block: dict) -> float:
    text = str(block.get("normalized_text") or "")
    if not text.strip():
        return 0.0

    lines = text.split("\n")
    total_lines = len(lines)
    if total_lines == 0:
        return 0.0

    score = 0.0

    # 1. Short line ratio (lines < 5 chars)
    short_lines = sum(1 for ln in lines if 0 < len(ln.strip()) < _SHORT_LINE_THRESHOLD)
    short_ratio = short_lines / total_lines
    if short_ratio > 0.4:
        score += 0.3
    elif short_ratio > 0.2:
        score += 0.15

    # 2. Garbled character density
    garbled_count = len(_GARBLED_CHARS.findall(text))
    garbled_ratio = garbled_count / max(len(text), 1)
    if garbled_ratio > 0.05:
        score += 0.3
    elif garbled_ratio > 0.02:
        score += 0.15

    # 3. Has options but no question number
    has_options = bool(_VALID_OPTION_MARKERS.search(text))
    has_question_num = bool(_QUESTION_NUM_PATTERN.search(text))
    if has_options and not has_question_num:
        score += 0.2

    # 4. Option fragmentation (has A but missing B/C/D)
    if has_options:
        found_options = set(re.findall(r"^([A-D])[.、．）)\s]", text, re.MULTILINE))
        if "A" in found_options and len(found_options) < 3:
            score += 0.2

    return min(score, 1.0)


def _should_correct(noise_score: float, config: dict) -> bool:
    mode = config.get("mode", "auto")
    if mode == "never":
        return False
    if mode == "always":
        return True
    threshold = config.get("noise_threshold", 0.3)
    return noise_score >= threshold


# ---------------------------------------------------------------------------
# AI call
# ---------------------------------------------------------------------------


async def _call_ai_correction(block_text: str, config: dict) -> str | None:
    from app.ai.client import deepseek
    from app.ai.prompts import build_ocr_correction

    if not deepseek.is_available():
        return None

    messages = build_ocr_correction(block_text)
    estimated = _estimate_tokens(block_text) * 3  # prompt + response overhead

    if not _check_token_limit(estimated, config):
        return None

    try:
        result = await deepseek.chat(messages, temperature=0.1)
    except Exception:
        return None

    _record_token_usage(result["tokens_used"])

    corrected = result["content"].strip()
    if not corrected:
        return None

    # Safety: reject if AI output is drastically different in length
    original_len = len(block_text)
    if len(corrected) > original_len * 2 or len(corrected) < original_len * 0.3:
        return None

    return corrected


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def correct_ocr_blocks(
    normalized_blocks: list[dict],
    config: dict | None = None,
) -> dict:
    """AI OCR 文本纠错层。"""
    if config is None:
        config = {}

    enabled = config.get("enabled", True)
    if not enabled:
        return {
            "corrected_blocks": normalized_blocks,
            "corrections": [],
            "stats": {
                "total_blocks": len(normalized_blocks),
                "noisy_blocks": 0,
                "corrected_blocks": 0,
                "skipped_blocks": len(normalized_blocks),
                "total_tokens": 0,
            },
            "skipped_reason": "disabled",
        }

    from app.ai.client import deepseek

    if not deepseek.is_available():
        return {
            "corrected_blocks": normalized_blocks,
            "corrections": [],
            "stats": {
                "total_blocks": len(normalized_blocks),
                "noisy_blocks": 0,
                "corrected_blocks": 0,
                "skipped_blocks": len(normalized_blocks),
                "total_tokens": 0,
            },
            "skipped_reason": "ai_unavailable",
        }

    corrections: list[dict] = []
    corrected_blocks = []
    noisy_count = 0
    corrected_count = 0
    total_tokens_before = int(_token_usage.get("daily", 0))

    for block in normalized_blocks:
        text = str(block.get("normalized_text") or "")
        if not text.strip():
            corrected_blocks.append(block)
            continue

        noise_score = _detect_noise(block)
        should = _should_correct(noise_score, config)

        if not should:
            corrected_blocks.append(block)
            corrections.append({
                "block_index": block.get("block_index", 0),
                "page": block.get("page", 1),
                "noise_score": round(noise_score, 3),
                "corrected": False,
            })
            continue

        noisy_count += 1
        corrected_text = await _call_ai_correction(text, config)

        if corrected_text is None:
            corrected_blocks.append(block)
            corrections.append({
                "block_index": block.get("block_index", 0),
                "page": block.get("page", 1),
                "noise_score": round(noise_score, 3),
                "corrected": False,
                "reason": "ai_failed_or_limit",
            })
            continue

        new_block = dict(block)
        new_block["normalized_text"] = corrected_text
        new_block["ocr_correction_applied"] = True
        corrected_blocks.append(new_block)
        corrected_count += 1

        corrections.append({
            "block_index": block.get("block_index", 0),
            "page": block.get("page", 1),
            "noise_score": round(noise_score, 3),
            "corrected": True,
        })

    _reset_counters_if_needed()
    total_tokens_used = int(_token_usage.get("daily", 0)) - total_tokens_before

    return {
        "corrected_blocks": corrected_blocks,
        "corrections": corrections,
        "stats": {
            "total_blocks": len(normalized_blocks),
            "noisy_blocks": noisy_count,
            "corrected_blocks": corrected_count,
            "skipped_blocks": len(normalized_blocks) - noisy_count,
            "total_tokens": max(total_tokens_used, 0),
        },
        "skipped_reason": None,
    }

"""AI OCR Correction Layer — 在结构分析前对 OCR 文本块进行 AI 辅助纠错。

位于 normalize_text 之后、analyze_structure 之前。
仅在检测到 OCR 噪声信号时触发，按 block 逐块纠错。
AI 不可用或 token 超限时静默降级。
"""

import asyncio
import logging
import re
import time

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_VALID_OPTION_MARKERS = re.compile(r"^[A-D][.、．）)\s]", re.MULTILINE)
_QUESTION_NUM_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:\d{1,3}|第[一二三四五六七八九十百]+题)[.、．）)【\s]",
)
_GARBLED_CHARS = re.compile(r"[�□█░-▓\x00-\x08\x0e-\x1f]")
_SHORT_LINE_THRESHOLD = 5

# ---------------------------------------------------------------------------
# Structure anomaly detection patterns (多维触发引擎)
# ---------------------------------------------------------------------------

# Runs of consecutive unusual symbols (mirror chars, arrows, etc.)
_RE_ABNORMAL_SYMBOLS = re.compile(r"[<>=!_:]{2,}|<-+|>-+")
# ASCII letter runs of 3+ consecutive lowercase chars (potential garbled words)
_RE_ASCII_RUN = re.compile(r"[a-z]{3,}")
# Short ASCII-only lines that might be garbled option markers
_RE_SHORT_ASCII_LINE = re.compile(r"^[!-~]{1,14}$", re.MULTILINE)

# ---------------------------------------------------------------------------
# Quality tier thresholds
# ---------------------------------------------------------------------------

TIER_HIGH_THRESHOLD = 0.15
TIER_MEDIUM_THRESHOLD = 0.30


def _classify_quality_tier(noise_score: float) -> str:
    """HIGH = clean (skip AI), MEDIUM = AI correct, LOW = AI correct + flag."""
    if noise_score < TIER_HIGH_THRESHOLD:
        return "HIGH"
    elif noise_score < TIER_MEDIUM_THRESHOLD:
        return "MEDIUM"
    else:
        return "LOW"


# ---------------------------------------------------------------------------
# Token budget (shared with ai_repair via token_budget module)
# ---------------------------------------------------------------------------

from app.features.token_budget import (
    estimate_tokens, check_token_limit, record_token_usage, get_token_usage_snapshot,
)

_estimate_tokens = estimate_tokens  # backward-compat alias for local use


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


# ---------------------------------------------------------------------------
# Structure anomaly detection (多维触发引擎)
# ---------------------------------------------------------------------------


def _detect_structure_abnormal(text: str) -> float:
    """检测 OCR 结果中的结构性异常（不依赖具体乱码字符）。

    五维检测：
    A. 中文占比异常 — 有中文但占比极低时说明识别丢失了中文字符
    B. 异常符号密度 — <-, =:, > > 等非正常考试文本的符号组合
    C. 无意义 ASCII 连续串 — 不含元音的连续小写字母（非英文单词特征）
    D. 选项结构异常 — 短 ASCII 行应匹配选项格式但未匹配
    E. 选项完整性异常 — 选项序列跳缺或数量不足（clean-but-incomplete）

    返回 0.0 ~ 1.0 的分数。
    """
    if not text.strip():
        return 0.0

    total = len(text.strip())
    if total < 5:
        return 0.0  # 太短无法判断

    score = 0.0

    # ---- A. 中文占比异常 ----
    chinese = len(re.findall(r"[一-鿿]", text))
    chinese_ratio = chinese / max(total, 1)
    has_some_chinese = chinese > 0

    if has_some_chinese and chinese_ratio < 0.10 and total > 20:
        score += 0.30  # 确定是中文文本但中文占比极低 → 严重异常
    elif has_some_chinese and chinese_ratio < 0.20 and total > 30:
        score += 0.15  # 中文占比偏低

    # ---- B. 异常符号密度 ----
    symbols = _RE_ABNORMAL_SYMBOLS.findall(text)
    symbol_chars = sum(len(m) for m in symbols)
    symbol_density = symbol_chars / max(total, 1)
    if symbol_density > 0.12:
        score += 0.30
    elif symbol_density > 0.06:
        score += 0.15

    # ---- C. 无意义 ASCII 连续串（不含元音的低位字母串） ----
    runs = _RE_ASCII_RUN.findall(text)
    bad_runs = sum(1 for r in runs if not re.search(r"[aeiou]", r))
    if bad_runs >= 3:
        score += 0.30  # 多个不含元音的"单词" → 极可能乱码
    elif bad_runs >= 1 and len(runs) >= 2:
        score += 0.15

    # ---- D. 选项结构异常 ----
    # 检查短 ASCII 行：如果存在大量短 ASCII 行但都不像选项标记
    lines = text.split("\n")
    ascii_short = [
        ln.strip() for ln in lines
        if 1 < len(ln.strip()) < 15 and not re.search(r"[一-鿿]", ln)
    ]
    if len(ascii_short) >= 3:
        option_like = sum(
            1 for ln in ascii_short
            if re.match(r"^[A-Da-d][.、．）)\s]", ln)
        )
        if option_like < len(ascii_short) * 0.3:
            score += 0.20

    # ---- E. 选项完整性异常（clean-but-incomplete：文本正常但选项缺失） ----
    option_markers = re.findall(r"^([A-D])\s*[.、．）)\s]", text, re.MULTILINE)
    if option_markers:
        present = set(option_markers)

        # 序列跳缺：A→C 跳过 B，或 A→D 缺少 B/C，或 B→D 跳过 C
        if "A" in present and "C" in present and "B" not in present:
            score += 0.30
        if "A" in present and "D" in present and ("B" not in present or "C" not in present):
            score += 0.30
        if "B" in present and "D" in present and "C" not in present:
            score += 0.25

        # 长文本（>150 字符）但选项数 ≤2 → 明显缺失
        if len(text) > 150 and len(present) <= 2:
            score += 0.20

        # 有 A/B/C 但缺 D（考研选择题通常为 4 个选项）
        if present == {"A", "B", "C"} and len(text) > 150:
            score += 0.20

    return min(score, 1.0)


def _should_correct(
    noise_score: float,
    config: dict,
    structure_score: float = 0.0,
    low_confidence: bool = False,
    has_image: bool = False,
) -> bool:
    """多维触发判断：noise OR structure_abnormal OR low_confidence。

    图片场景（has_image=True）降低触发阈值，但不无条件调用。
    """
    mode = config.get("mode", "auto")
    if mode == "never":
        return False
    if mode == "always":
        return True

    # 低置信度直接触发纠错
    if low_confidence:
        return True

    # 合并 noise 和 structure 分数
    combined = max(noise_score, structure_score)

    # 自定义阈值优先（向后兼容现有配置）
    threshold = config.get("noise_threshold")
    if threshold is not None:
        return combined >= threshold

    # 图片场景降低门槛：TIER_HIGH 的 70%
    if has_image:
        return combined >= TIER_HIGH_THRESHOLD * 0.7

    # 默认基于 quality tier（>= MEDIUM 触发）
    tier = _classify_quality_tier(combined)
    return tier in ("MEDIUM", "LOW")


# ---------------------------------------------------------------------------
# AI call
# ---------------------------------------------------------------------------


async def _call_ai_correction(
    block_text: str, config: dict,
    api_key: str | None = None, base_url: str | None = None,
    model: str | None = None,
    page_image: bytes | None = None,
) -> str | None:
    from app.ai.client import deepseek
    from app.ai.prompts import build_ocr_correction

    if not (api_key or deepseek.is_available()):
        return None

    # ocr_filter_max_chars: 截断超长文本
    max_chars = config.get("ocr_filter_max_chars")
    if max_chars is not None and len(block_text) > int(max_chars):
        block_text = block_text[:int(max_chars)]

    # ocr_filter_max_tokens: 超过上限则跳过
    max_tokens = config.get("ocr_filter_max_tokens")
    estimated = _estimate_tokens(block_text) * 3  # prompt + response overhead (computed once)
    if max_tokens is not None:
        if estimated > int(max_tokens):
            return None

    # 图片场景：base_url 含 dashscope 且提供了页面图片时，走 VL 多模态请求
    is_vl = base_url and "dashscope" in base_url and page_image
    if is_vl:
        import base64
        image_b64 = base64.b64encode(page_image).decode("ascii")
        messages = [
            {"role": "system", "content": config.get("ocr_correction_prompt") or "你是专业 OCR 校验助手。"},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                {"type": "text", "text": f"请根据图片核对并修正以下 OCR 识别文本：\n\n{block_text}"},
            ]},
        ]
    else:
        messages = build_ocr_correction(block_text, system_prompt=config.get("ocr_correction_prompt"))

    if not await check_token_limit(estimated, config):
        return None

    try:
        result = await deepseek.chat(messages, temperature=0.1, model=model, api_key=api_key, base_url=base_url)
    except Exception:
        return None

    await record_token_usage(result["tokens_used"])

    corrected = result["content"].strip()
    if not corrected:
        return None

    # Safety: reject if AI output is drastically different in length
    original_len = len(block_text)
    if len(corrected) > original_len * 2 or len(corrected) < original_len * 0.5:
        return None

    return corrected


# ---------------------------------------------------------------------------
# Sensitive content filter
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS = [
    (re.compile(r"1[3-9]\d{9}"), "[phone]"),                     # 手机号
    (re.compile(r"\b\d{17}[\dXx]\b"), "[id-number]"),             # 身份证号
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[email]"),
    (re.compile(r"(?:(?:https?|ftp)://|www\.)[^\s，。、；：)]+"), "[url]"),
]

_SENSITIVE_CJK_TERMS: list[re.Pattern] = [
    re.compile(term) for term in [
        r"代[考写发作]",
        r"助考",
        r"作弊",
        r"答案\s*[免免wx微信]",
        r"加\s*[微VQq微信]{1,4}\s*[信信号]?",
    ]
]


def _filter_sensitive(text: str) -> str:
    """过滤敏感内容：替换手机号、邮箱、网址、广告词等。"""
    if not text:
        return text
    for pat, replacement in _SENSITIVE_PATTERNS:
        text = pat.sub(replacement, text)
    for pat in _SENSITIVE_CJK_TERMS:
        text = pat.sub("[sensitive]", text)
    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def correct_ocr_blocks(
    normalized_blocks: list[dict],
    config: dict | None = None,
    db: AsyncSession | None = None,
    page_images: dict[int, bytes] | None = None,
) -> dict:
    """AI OCR 文本纠错层。"""
    if config is None:
        config = {}

    # 从 DB admin_ai_configs 读取过滤配置
    if db is not None:
        try:
            from app.services.admin_ai_config_service import get_all_configs

            db_cfg = await get_all_configs(db)
            for key in ("ocr_filter_max_chars", "ocr_filter_max_tokens", "ocr_correction_prompt", "ocr_filter_sensitive"):
                if key in db_cfg and key not in config:
                    val = db_cfg[key]
                    if val is not None and val != "":
                        config[key] = val
        except Exception:
            pass

    creds = None
    if db is not None:
        from app.services.model_config_resolver import ensure_db_model_configured
        creds = await ensure_db_model_configured(db, feature="ocr")

    _api_key = creds[0] if creds else None
    _base_url = creds[1] if creds else None
    _model_name = creds[2] if creds else None

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

    if not (_api_key or deepseek.is_available()):
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
    corrected_blocks: list[dict] = [None] * len(normalized_blocks)  # type: ignore
    noisy_count = 0
    corrected_count = 0
    flagged_for_review = 0
    tier_distribution: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    snapshot_before = get_token_usage_snapshot()
    total_tokens_before = snapshot_before["daily"]

    to_correct: list[tuple[int, str, float]] = []

    for idx, block in enumerate(normalized_blocks):
        text = str(block.get("normalized_text") or "")
        if not text.strip():
            corrected_blocks[idx] = block
            continue

        noise_score = _detect_noise(block)
        structure_score = _detect_structure_abnormal(text)
        combined = max(noise_score, structure_score)
        tier = _classify_quality_tier(combined)
        tier_distribution[tier] += 1
        should = _should_correct(noise_score, config, structure_score=structure_score)

        if not should:
            corrected_blocks[idx] = block
            corrections.append({
                "block_index": block.get("block_index", 0),
                "page": block.get("page", 1),
                "noise_score": round(noise_score, 3),
                "structure_score": round(structure_score, 3),
                "quality_tier": tier,
                "corrected": False,
            })
            continue

        noisy_count += 1
        to_correct.append((idx, text, noise_score, structure_score))

    sem = asyncio.Semaphore(3)

    async def _correct_one(idx: int, text: str, block: dict):
        async with sem:
            page_num = block.get("page", 1)
            page_img = page_images.get(page_num) if page_images else None
            return idx, await _call_ai_correction(
                text, config, api_key=_api_key, base_url=_base_url, model=_model_name,
                page_image=page_img,
            )

    results = await asyncio.gather(
        *[_correct_one(idx, text, normalized_blocks[idx]) for idx, text, _, _ in to_correct],
        return_exceptions=True,
    )

    for (idx, text, noise_score, structure_score), result in zip(to_correct, results):
        block = normalized_blocks[idx]
        combined = max(noise_score, structure_score)
        tier = _classify_quality_tier(combined)

        if isinstance(result, BaseException):
            logger.debug("ocr_correction block %d failed: %s", idx, result)
            corrected_text = None
        else:
            _, corrected_text = result

        if corrected_text is None:
            corrected_blocks[idx] = block
            corrections.append({
                "block_index": block.get("block_index", 0),
                "page": block.get("page", 1),
                "noise_score": round(noise_score, 3),
                "structure_score": round(structure_score, 3),
                "quality_tier": tier,
                "corrected": False,
                "needs_review": tier == "LOW",
                "reason": "ai_failed_or_limit",
            })
            if tier == "LOW":
                flagged_for_review += 1
            continue

        new_block = dict(block)
        new_block["normalized_text"] = corrected_text
        new_block["ocr_correction_applied"] = True
        if tier == "LOW":
            new_block["needs_review"] = True
            flagged_for_review += 1
        corrected_blocks[idx] = new_block
        corrected_count += 1

        corrections.append({
            "block_index": block.get("block_index", 0),
            "page": block.get("page", 1),
            "noise_score": round(noise_score, 3),
            "structure_score": round(structure_score, 3),
            "quality_tier": tier,
            "corrected": True,
            "needs_review": tier == "LOW",
        })

    # M2: ensure all blocks are non-None (defense against silent data loss)
    for idx, b in enumerate(corrected_blocks):
        if b is None:
            logger.error("ocr_correction: block %d was not filled — falling back to original", idx)
            corrected_blocks[idx] = normalized_blocks[idx]

    final_blocks = [b for b in corrected_blocks if b is not None]

    # 敏感内容过滤
    if config.get("ocr_filter_sensitive", False):
        filtered_count = 0
        for b in final_blocks:
            text = b.get("normalized_text", "")
            filtered = _filter_sensitive(text)
            if filtered != text:
                b["normalized_text"] = filtered
                filtered_count += 1
        if filtered_count:
            logger.debug("ocr_filter_sensitive: filtered %d blocks", filtered_count)

    snapshot_after = get_token_usage_snapshot()
    total_tokens_used = snapshot_after["daily"] - total_tokens_before

    return {
        "corrected_blocks": final_blocks,
        "corrections": corrections,
        "stats": {
            "total_blocks": len(normalized_blocks),
            "noisy_blocks": noisy_count,
            "corrected_blocks": corrected_count,
            "skipped_blocks": len(normalized_blocks) - noisy_count,
            "total_tokens": max(total_tokens_used, 0),
            "tier_distribution": tier_distribution,
            "flagged_for_review": flagged_for_review,
        },
        "skipped_reason": None,
    }

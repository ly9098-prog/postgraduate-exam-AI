"""Text syntax decoding for AI analysis, using the caller's live parser ports."""

from __future__ import annotations


def strip_code_fence(text: str, *, ports) -> str:
    """Strip complete or truncated Markdown code fences from model output."""
    value = str(text or "").strip()
    match = ports("re").search(
        r"```(?:json|javascript|js)?\s*([\s\S]*?)\s*```",
        value,
        ports("re").IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    value = ports("re").sub(
        r"^```(?:json|javascript|js)?\s*", "", value, flags=ports("re").IGNORECASE
    )
    value = ports("re").sub(r"\s*```$", "", value)
    return value.strip()


def looks_like_structured_analysis_text(text: str, *, ports) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if value[:1] in {"{", "["}:
        return True
    keys = ports("_DIAGNOSIS_KEYS") + ports("_KNOWLEDGE_KEYS") + ports("_TASK_KEYS")
    return any(
        ports("re").search(
            rf"""(["\']){ports("re").escape(key)}\1\s*:""",
            value,
            ports("re").IGNORECASE,
        )
        for key in keys
    )


def decode_structured_content(raw: str, *, ports):
    """Decode JSON/Python-literal model output, including text around the object."""
    original = (raw or "").strip()
    decoder = ports("json").JSONDecoder()

    def decode_candidates(value: str):
        starts = [0]
        starts.extend((i for i, char in enumerate(value) if i > 0 and char in "{["))
        for start in starts:
            candidate = value[start:].lstrip()
            if not candidate:
                continue
            try:
                decoded, _ = decoder.raw_decode(candidate)
                return decoded
            except (ports("json").JSONDecodeError, ValueError):
                pass
            try:
                decoded = ports("ast").literal_eval(candidate)
                if isinstance(decoded, (dict, list, str)):
                    return decoded
            except (SyntaxError, ValueError):
                pass
        return None

    # Decode the outer object before stripping fences inside its string fields.
    decoded = decode_candidates(original)
    if decoded is not None:
        return decoded
    stripped = ports("_strip_code_fence")(original)
    if stripped != original:
        return decode_candidates(stripped)
    return None


def parse_titled_analysis_text(text: str, *, ports) -> dict:
    stripped = ports("_strip_code_fence")(text)
    heading_re = ports("re").compile(
        r"(?im)^\s*(?:#{1,6}\s*)?(?:\d+[.、)]\s*)?(?:[-*]\s*)?"
        r"(?:\*\*)?\s*(错因诊断|补漏重点|复练任务)\s*(?:\*\*)?\s*[：:]\s*(?:\*\*)?\s*"
    )
    matches = list(heading_re.finditer(stripped))
    if not matches:
        if ports("_looks_like_structured_analysis_text")(stripped):
            return dict(ports("_EMPTY_ANALYSIS"))
        return {"mistake_diagnosis": stripped, "knowledge_patch": "", "review_task": ""}
    result = dict(ports("_EMPTY_ANALYSIS"))
    key_map = {
        "错因诊断": "mistake_diagnosis",
        "补漏重点": "knowledge_patch",
        "复练任务": "review_task",
    }
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(stripped)
        result[key_map[match.group(1)]] = stripped[match.end() : end].strip()
    return result

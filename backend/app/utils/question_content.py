"""Content utility functions shared across publish and import flows."""

from __future__ import annotations


def normalize_segment_type(segment: object) -> str:
    """Return a tolerant, canonical segment type for historical payloads."""
    if not isinstance(segment, dict):
        return ""
    return str(segment.get("type") or "").strip().lower()


def strip_student_segment_metadata(content: dict) -> dict:
    """Remove non-display import metadata from student-facing segment payloads.

    Admin/editor payloads keep the original metadata. This function always
    copies the content/segment mappings so API sanitization never mutates ORM
    JSON values in place.
    """
    sanitized = dict(content)
    segments = sanitized.get("segments")
    if not isinstance(segments, list):
        return sanitized

    cleaned: list[object] = []
    for raw_segment in segments:
        if not isinstance(raw_segment, dict):
            cleaned.append(raw_segment)
            continue
        segment = dict(raw_segment)
        if normalize_segment_type(segment) == "code":
            # Code-region alt text is an OCR/import/accessibility description,
            # not a visible code caption. `caption` is the explicit display field.
            segment.pop("alt", None)
        cleaned.append(segment)
    sanitized["segments"] = cleaned
    return sanitized


def extract_image_urls_from_content(content: dict | None) -> list[str] | None:
    """从 segments 中提取 display=True 的图片 URL 列表。

    规则：
    1. 只提取 {"type": "image", "display": true, "url": "..."} 的条目；
    2. URL 去重（保留首次出现顺序）；
    3. 忽略空 URL、非字符串 URL 和 display=False；
    4. 没有符合条件的图片时返回 None。
    """
    if not isinstance(content, dict):
        return None

    segments = content.get("segments")
    if not isinstance(segments, list) or not segments:
        return None

    seen: set[str] = set()
    urls: list[str] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        if normalize_segment_type(seg) != "image":
            continue
        if seg.get("display") is False:
            continue
        url = seg.get("url")
        if not isinstance(url, str):
            continue
        url = url.strip()
        if not url:
            continue
        if url not in seen:
            seen.add(url)
            urls.append(url)

    return urls if urls else None

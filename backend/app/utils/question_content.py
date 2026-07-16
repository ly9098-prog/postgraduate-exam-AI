"""Content utility functions shared across publish and import flows."""

from __future__ import annotations

from typing import Any


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
        if seg.get("type") != "image":
            continue
        if seg.get("display") is False:
            continue
        url = seg.get("url")
        if not isinstance(url, str) or not url:
            continue
        if url not in seen:
            seen.add(url)
            urls.append(url)

    return urls if urls else None

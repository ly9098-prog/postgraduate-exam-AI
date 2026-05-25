"""混合题内容构建器：将题文本 + MathRegion 列表组合为 segments 结构。"""
from app.services.math_region_detector import MathRegion, MathRegionType


def build(text: str, regions: list[MathRegion]) -> dict:
    """根据 text 和已填充 image_url 的 regions 构建 content JSON。

    无 regions 时返回纯文本结构（与旧路径一致）。
    有 regions 时返回含 segments 的结构。
    """
    if not regions:
        return {"text": text}

    # 只处理有 image_url 且 bbox 合法的区域，按页码和 y 坐标排序
    valid = [r for r in regions if r.image_url and r.bbox[2] > r.bbox[0]]
    if not valid:
        return {"text": text}

    valid.sort(key=lambda r: (r.page_num, r.bbox[1], r.bbox[0]))

    segments = _build_segments(text, valid)
    rebuilt_text = _rebuild_text(segments)

    return {
        "text": rebuilt_text,
        "segments": segments,
        "render_mode": "segments",
    }


def _build_segments(text: str, regions: list[MathRegion]) -> list[dict]:
    """将纯文本按公式区域切分为 segment 列表。

    strategy：逐行扫描，将 raw_latex 片段在 text 中定位并替换为 math_image segment。
    无法定位的 region 追加到末尾。
    """
    segments: list[dict] = []
    remaining = text

    for region in regions:
        alt = region.raw_latex or ""
        display = region.region_type == MathRegionType.DISPLAY

        # 尝试在剩余文本中定位 raw_latex
        pos = -1
        if alt:
            pos = remaining.find(alt)

        if pos >= 0:
            # 公式前的文本
            before = remaining[:pos]
            if before:
                segments.append({"type": "text", "text": before})
            # 公式 segment
            segments.append({
                "type": "math_image",
                "url": region.image_url,
                "alt": alt,
                "display": display,
            })
            remaining = remaining[pos + len(alt):]
        else:
            # 无法定位：追加为行内公式（不切割文本）
            segments.append({
                "type": "math_image",
                "url": region.image_url,
                "alt": alt,
                "display": display,
            })

    # 剩余文本
    if remaining:
        segments.append({"type": "text", "text": remaining})

    return segments


def _rebuild_text(segments: list[dict]) -> str:
    """从 segments 重建 content.text，公式用 $alt$ 占位。"""
    parts = []
    for seg in segments:
        if seg["type"] == "text":
            parts.append(seg.get("text") or "")
        elif seg["type"] == "math_image":
            alt = seg.get("alt") or ""
            parts.append(f"${alt}$")
        elif seg["type"] == "newline":
            parts.append("\n")
    return "".join(parts)

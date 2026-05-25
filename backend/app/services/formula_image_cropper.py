"""公式截图系统：根据 MathRegion bbox 截图，上传到 StorageBackend。"""
import hashlib
import logging
from datetime import datetime

import fitz

from app.services.math_region_detector import MathRegion, MathRegionType
from app.services.storage_backend import StorageBackend

logger = logging.getLogger(__name__)

_DPI = {
    MathRegionType.INLINE: 144,
    MathRegionType.DISPLAY: 240,
    MathRegionType.MIXED: 144,
}
_PADDING_PT = 6.0


def crop_region(page: fitz.Page, region: MathRegion) -> bytes:
    """截取单个 MathRegion 为 PNG bytes。"""
    x0, y0, x1, y1 = region.bbox
    rect = fitz.Rect(
        max(0, x0 - _PADDING_PT),
        max(0, y0 - _PADDING_PT),
        min(page.rect.width, x1 + _PADDING_PT),
        min(page.rect.height, y1 + _PADDING_PT),
    )
    dpi = _DPI.get(region.region_type, 144)
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, clip=rect, colorspace=fitz.csRGB, alpha=False)
    return pix.tobytes("png")


async def crop_and_upload(
    doc: fitz.Document,
    regions: list[MathRegion],
    storage: StorageBackend,
    import_id: int,
) -> list[MathRegion]:
    """截图并上传，返回填充了 image_url 的 MathRegion 列表。单图失败时跳过。"""
    month = datetime.now().strftime("%Y%m")
    result = []

    for region in regions:
        try:
            if region.page_num < 0 or region.page_num >= len(doc):
                result.append(region)
                continue

            page = doc[region.page_num]
            png_bytes = crop_region(page, region)
            content_hash = hashlib.md5(png_bytes).hexdigest()[:8]
            filename = f"{import_id}_{region.page_num}_{content_hash}.png"
            url = await storage.upload(f"{month}/{filename}", png_bytes)
            region.image_url = url
        except Exception as e:
            logger.warning(
                "截图上传失败 import_id=%s page=%s: %s",
                import_id, region.page_num, e,
            )
        result.append(region)

    return result

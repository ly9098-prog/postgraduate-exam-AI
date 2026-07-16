"""公式截图系统：根据 MathRegion bbox 截图，上传到 StorageBackend。

支持两种截图方式：
1. crop_region / crop_and_upload — 基于 PyMuPDF (fitz) 的 PDF 页截图。
2. crop_from_page_ref / crop_and_upload_refs — 基于已渲染页面 PNG 的截图。

crop_from_page_ref 委托给 visual_region_cropper 实现，保持向后兼容。
"""
import hashlib
import io
import logging
from datetime import datetime

import fitz

from app.services.math_region_detector import MathRegion, MathRegionType
from app.services.storage_backend import StorageBackend
from app.services.visual_region_cropper import crop_from_page_ref_compat

logger = logging.getLogger(__name__)

_DPI = {
    MathRegionType.INLINE: 144,
    MathRegionType.DISPLAY: 240,
    MathRegionType.MIXED: 144,
}
_PADDING_PT = 6.0
_PAGE_RENDER_DPI = 150  # _render_page_image_refs 的渲染 DPI
_MIN_CROP_WIDTH = 16
_MIN_CROP_HEIGHT = 16


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


def crop_from_page_ref(
    page_image_path: str,
    bbox: tuple[float, float, float, float],
    region_type: MathRegionType = MathRegionType.MIXED,
) -> bytes:
    """P2-3: 从已渲染的页面 PNG 截取公式区域，返回 PNG bytes。

    将 PDF 坐标空间 (72 DPI) 的 bbox 按 _PAGE_RENDER_DPI 缩放后裁剪。
    委托给 visual_region_cropper 实现，保持向后兼容。

    Raises:
        ValueError: cropped 区域为空时抛出（bbox 超出图片范围或负区间）。
        FileNotFoundError / PIL.UnidentifiedImageError: page_image_path 不可读或非图片时由上层处理。
    """
    try:
        return crop_from_page_ref_compat(
            page_image_path,
            bbox,
            padding_pt=_PADDING_PT,
        )
    except Exception as e:
        raise ValueError(
            f"crop_from_page_ref failed: bbox={bbox} path={page_image_path}: {e}"
        ) from e


async def crop_and_upload_refs(
    page_image_refs: dict[int, str],
    regions: list[MathRegion],
    storage: StorageBackend,
    import_id: int,
) -> list[MathRegion]:
    """P2-3: 基于页面 PNG 批量截图并上传，单图失败时跳过。"""
    month = datetime.now().strftime("%Y%m")
    result = []

    for region in regions:
        try:
            page_path = page_image_refs.get(region.page_num)
            if not page_path:
                result.append(region)
                continue

            png_bytes = crop_from_page_ref(page_path, region.bbox, region.region_type)
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

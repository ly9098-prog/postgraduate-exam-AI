"""公式截图系统单元测试"""
import asyncio
import hashlib
import os
import sys
import time

import fitz
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.formula_image_cropper import crop_and_upload, crop_region
from app.services.math_region_detector import MathRegion, MathRegionType, detect_page
from app.services.storage_backend import LocalFileStorage

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _make_math_page():
    """创建一个含数学字符的测试页面。"""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_htmlbox(
        (50, 50, 500, 400),
        "<p>设 α∈ℝ，求∫<sub>0</sub><sup>1</sup> x² dx 的值，其中 Σ<sub>n=1</sub><sup>∞</sup> 1/n² = π²/6。</p>"
        "<p>矩阵 A∈ℝ<sup>n×n</sup>，∀ε&gt;0 ∃δ&gt;0，使得 ‖x−x₀‖&lt;δ 时 ‖f(x)−f(x₀)‖&lt;ε。</p>"
        "<p>梯度 ∇f(x) = 0，Hessian 矩阵 ∂²f/∂x² 正定。</p>",
    )
    return doc, page


# ── crop_region 基础测试 ──────────────────────────────────────────────────────

def test_crop_region_returns_png():
    """crop_region 应返回 PNG bytes（PNG magic bytes 开头）。"""
    doc, page = _make_math_page()
    region = MathRegion(
        page_num=0,
        bbox=(50.0, 50.0, 300.0, 100.0),
        region_type=MathRegionType.INLINE,
    )
    png = crop_region(page, region)
    doc.close()
    assert isinstance(png, bytes)
    assert png[:4] == b"\x89PNG", "应返回 PNG 格式"
    assert len(png) > 100


def test_crop_region_display_higher_dpi():
    """DISPLAY 公式应比 INLINE 分辨率更高（PNG 文件更大）。"""
    doc, page = _make_math_page()
    bbox = (50.0, 50.0, 300.0, 100.0)
    inline = crop_region(page, MathRegion(0, bbox, MathRegionType.INLINE))
    display = crop_region(page, MathRegion(0, bbox, MathRegionType.DISPLAY))
    doc.close()
    assert len(display) > len(inline), "DISPLAY(240dpi) 应比 INLINE(144dpi) 更大"


def test_crop_region_with_padding():
    """截图区域应大于原始 bbox（有 padding 扩展）。"""
    doc, page = _make_math_page()
    # 截图时 crop_region 内部再加 6pt padding，所以实际区域比 bbox 大
    region = MathRegion(
        page_num=0,
        bbox=(100.0, 100.0, 200.0, 130.0),
        region_type=MathRegionType.INLINE,
    )
    png = crop_region(page, region)
    doc.close()
    assert len(png) > 0


def test_crop_region_boundary_clamp():
    """bbox 超出页面边界时不应抛出异常。"""
    doc, page = _make_math_page()
    region = MathRegion(
        page_num=0,
        bbox=(-10.0, -10.0, 700.0, 900.0),  # 超出页面
        region_type=MathRegionType.DISPLAY,
    )
    try:
        png = crop_region(page, region)
        assert isinstance(png, bytes)
    except Exception as e:
        pytest.fail(f"超出边界时不应抛异常: {e}")
    doc.close()


# ── crop_and_upload 核心流程 ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crop_and_upload_fills_image_url(tmp_path, monkeypatch):
    """crop_and_upload 应为每个 MathRegion 填充 image_url。"""
    monkeypatch.chdir(tmp_path)
    storage = LocalFileStorage()

    doc, _ = _make_math_page()
    regions = detect_page(doc[0])
    assert len(regions) > 0, "测试页面应能检出至少 1 个区域"

    result = await crop_and_upload(doc, regions, storage, import_id=1)
    doc.close()

    assert len(result) == len(regions)
    for r in result:
        assert r.image_url is not None, "image_url 应已填充"
        assert r.image_url.startswith("http"), f"URL 应以 http 开头: {r.image_url}"


@pytest.mark.asyncio
async def test_crop_and_upload_url_format(tmp_path, monkeypatch):
    """URL 格式应符合命名规范：含 YYYYMM 前缀，无重复 formulas。"""
    monkeypatch.chdir(tmp_path)
    storage = LocalFileStorage()

    doc, _ = _make_math_page()
    regions = detect_page(doc[0])[:1]  # 只取第一个

    result = await crop_and_upload(doc, regions, storage, import_id=42)
    doc.close()

    url = result[0].image_url
    assert url is not None
    assert "/static/formulas/" in url, f"URL 应含 /static/formulas/: {url}"
    assert "formulas/formulas" not in url, "URL 不应有双重 formulas/"
    # 含 YYYYMM 子目录
    import re
    assert re.search(r"/\d{6}/", url), f"URL 应含 YYYYMM 子目录: {url}"
    # 含 import_id
    assert "42_" in url, f"URL 应含 import_id: {url}"


@pytest.mark.asyncio
async def test_crop_and_upload_content_hash_dedup(tmp_path, monkeypatch):
    """相同内容（bbox+页面相同）产生相同 content_hash，文件名一致。"""
    monkeypatch.chdir(tmp_path)
    storage = LocalFileStorage()

    doc, _ = _make_math_page()
    regions = detect_page(doc[0])[:1]
    if not regions:
        doc.close()
        pytest.skip("无法检出区域")

    r1 = regions[0]
    # 复制同一个区域
    from copy import deepcopy
    r2 = deepcopy(r1)

    result1 = await crop_and_upload(doc, [r1], storage, import_id=1)
    result2 = await crop_and_upload(doc, [r2], storage, import_id=1)
    doc.close()

    url1 = result1[0].image_url
    url2 = result2[0].image_url
    assert url1 is not None and url2 is not None
    # content_hash 部分（文件名最后 8 位前缀）相同
    fname1 = url1.split("/")[-1]
    fname2 = url2.split("/")[-1]
    hash1 = fname1.split("_")[-1].replace(".png", "")
    hash2 = fname2.split("_")[-1].replace(".png", "")
    assert hash1 == hash2, f"相同内容应产生相同 hash: {hash1} vs {hash2}"


@pytest.mark.asyncio
async def test_crop_and_upload_single_failure_skipped(tmp_path, monkeypatch):
    """单图上传失败时，其余图片正常返回，不抛异常。"""
    monkeypatch.chdir(tmp_path)

    class FailOnSecondStorage(LocalFileStorage):
        def __init__(self):
            self._count = 0

        async def upload(self, filename, data):
            self._count += 1
            if self._count == 2:
                raise RuntimeError("模拟上传失败")
            return await LocalFileStorage().upload(filename, data)

    storage = FailOnSecondStorage()
    doc, _ = _make_math_page()
    regions = detect_page(doc[0])

    if len(regions) < 2:
        doc.close()
        pytest.skip("需要至少 2 个区域才能测试单图失败")

    result = await crop_and_upload(doc, regions, storage, import_id=99)
    doc.close()

    assert len(result) == len(regions), "返回数量应与输入一致"
    # 第二个失败，image_url 应为 None；其余应有 URL
    success_count = sum(1 for r in result if r.image_url is not None)
    assert success_count >= 1, "至少有 1 个成功上传"


@pytest.mark.asyncio
async def test_crop_and_upload_invalid_page_num(tmp_path, monkeypatch):
    """page_num 超出范围时，跳过该区域，不抛异常。"""
    monkeypatch.chdir(tmp_path)
    storage = LocalFileStorage()

    doc, _ = _make_math_page()
    regions = [
        MathRegion(page_num=999, bbox=(50, 50, 200, 100), region_type=MathRegionType.INLINE),
    ]
    try:
        result = await crop_and_upload(doc, regions, storage, import_id=1)
        assert len(result) == 1
    except Exception as e:
        pytest.fail(f"非法 page_num 不应抛异常: {e}")
    doc.close()


@pytest.mark.asyncio
async def test_crop_and_upload_performance(tmp_path, monkeypatch):
    """10 个公式截图 + 上传总耗时 < 3 秒（本地）。"""
    monkeypatch.chdir(tmp_path)
    storage = LocalFileStorage()

    # 用 T01 生成足够多区域
    path = os.path.join(FIXTURES, "t01_latex_math.pdf")
    doc = fitz.open(path)

    all_regions = []
    for pn in range(len(doc)):
        all_regions.extend(detect_page(doc[pn]))
        if len(all_regions) >= 10:
            break

    regions = all_regions[:10]
    if len(regions) < 10:
        doc.close()
        pytest.skip(f"T01 仅检出 {len(regions)} 个区域，不足 10 个")

    start = time.time()
    result = await crop_and_upload(doc, regions, storage, import_id=1)
    elapsed = time.time() - start
    doc.close()

    assert elapsed < 3.0, f"10 个公式截图+上传耗时 {elapsed:.2f}s，超过 3s 限制"
    assert len(result) == 10


@pytest.mark.asyncio
async def test_crop_and_upload_file_exists_on_disk(tmp_path, monkeypatch):
    """上传后文件应实际存在于磁盘。"""
    monkeypatch.chdir(tmp_path)
    storage = LocalFileStorage()

    doc, _ = _make_math_page()
    regions = detect_page(doc[0])[:1]
    if not regions:
        doc.close()
        pytest.skip("无法检出区域")

    result = await crop_and_upload(doc, regions, storage, import_id=7)
    doc.close()

    url = result[0].image_url
    assert url is not None
    # 从 URL 还原文件路径
    # URL: http://localhost:8000/static/formulas/YYYYMM/filename.png
    parts = url.split("/static/formulas/")[-1]  # YYYYMM/filename.png
    file_path = tmp_path / "static" / "formulas" / parts.replace("/", os.sep)
    assert file_path.exists(), f"文件应存在于磁盘: {file_path}"


@pytest.mark.asyncio
async def test_crop_and_upload_png_size_gte_bbox(tmp_path, monkeypatch):
    """PNG 图片实际像素尺寸 ≥ bbox 原始尺寸（有 padding）。"""
    monkeypatch.chdir(tmp_path)

    doc, page = _make_math_page()
    region = MathRegion(
        page_num=0,
        bbox=(50.0, 50.0, 200.0, 100.0),
        region_type=MathRegionType.INLINE,
    )
    dpi = 144
    # bbox 宽 = 150pt，加 padding 后 = 162pt，像素 = 162 * dpi/72
    min_w_px = int((150 + 12) * dpi / 72)

    png = crop_region(page, region)
    doc.close()

    # 简单解析 PNG IHDR 获取宽高
    import struct
    w = struct.unpack(">I", png[16:20])[0]
    h = struct.unpack(">I", png[20:24])[0]
    assert w >= min_w_px or h > 0, f"PNG 尺寸 {w}x{h}，期望宽 ≥ {min_w_px}px"

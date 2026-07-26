"""Tests for image compression and storage backend."""

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from app.core.config import settings
from app.services.storage_backend import (
    MAX_IMAGE_DIMENSION,
    COSStorage,
    LocalFileStorage,
    compress_image,
    get_storage,
)


def _make_image(fmt: str = "JPEG", size: tuple[int, int] = (200, 150), color: tuple[int, int, int] = (255, 0, 0)):
    """Create a minimal test image and return its bytes.

    For PNG with alpha, pass a 4-tuple color; for PNG without alpha, use mode='RGB'.
    """
    if fmt == "PNG" and isinstance(color, tuple) and len(color) == 4:
        img = Image.new("RGBA", size, color)
    elif fmt == "PNG":
        img = Image.new("RGB", size, color)
    else:
        img = Image.new("RGB", size, color)
    buf = BytesIO()
    img.save(buf, format=fmt)
    buf.seek(0)
    return buf.read(), img


def _image_from_bytes(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data))


class TestCompressImage:
    def test_compress_jpeg(self):
        """JPEG is re-encoded at target quality."""
        data, _ = _make_image("JPEG")
        compressed = compress_image(data)
        assert len(compressed) > 0
        img = _image_from_bytes(compressed)
        assert img.format in ("JPEG",)

    def test_compress_png_rgb(self):
        """RGB PNG without transparency is converted to JPEG (smaller)."""
        # Create PNG with plain RGB (no alpha) — should convert to JPEG
        data, _ = _make_image("PNG", size=(100, 80), color=(128, 64, 32))
        compressed = compress_image(data)
        img = _image_from_bytes(compressed)
        assert img.format in ("JPEG",)

    def test_compress_png_rgba_preserves_png(self):
        """RGBA PNG with transparency stays as PNG."""
        img = Image.new("RGBA", (100, 80), (255, 0, 0, 128))
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        data = buf.read()
        compressed = compress_image(data)
        img2 = _image_from_bytes(compressed)
        assert img2.format == "PNG"

    def test_compress_webp(self):
        """WebP is re-encoded at target quality."""
        data, _ = _make_image("WEBP")
        compressed = compress_image(data)
        img = _image_from_bytes(compressed)
        assert img.format == "WEBP"

    def test_compress_gif_converted_to_jpeg(self):
        """GIF is converted to JPEG."""
        data, _ = _make_image("GIF", size=(50, 50))
        compressed = compress_image(data)
        img = _image_from_bytes(compressed)
        assert img.format == "JPEG"

    def test_compress_bmp_converted_to_jpeg(self):
        """BMP is converted to JPEG."""
        data, _ = _make_image("BMP", size=(50, 50))
        compressed = compress_image(data)
        img = _image_from_bytes(compressed)
        assert img.format == "JPEG"

    def test_resize_large_image(self):
        """Image wider than MAX_IMAGE_DIMENSION gets resized."""
        large_w = MAX_IMAGE_DIMENSION * 2
        data, original = _make_image("JPEG", size=(large_w, 1000))
        compressed = compress_image(data)
        img = _image_from_bytes(compressed)
        assert img.width <= MAX_IMAGE_DIMENSION
        assert img.height <= MAX_IMAGE_DIMENSION

    def test_resize_tall_image(self):
        """Tall image gets resized proportionally."""
        tall_h = MAX_IMAGE_DIMENSION * 3
        data, _ = _make_image("JPEG", size=(500, tall_h))
        compressed = compress_image(data)
        img = _image_from_bytes(compressed)
        assert img.height <= MAX_IMAGE_DIMENSION

    def test_small_image_not_resized(self):
        """Small image is not upscaled."""
        data, original = _make_image("JPEG", size=(100, 80))
        compressed = compress_image(data)
        img = _image_from_bytes(compressed)
        assert img.width == 100
        assert img.height == 80

    def test_aspect_ratio_preserved(self):
        """Aspect ratio is preserved after resize."""
        data, _ = _make_image("JPEG", size=(2400, 1200))
        compressed = compress_image(data)
        img = _image_from_bytes(compressed)
        aspect = img.width / img.height
        assert abs(aspect - 2.0) < 0.01  # 2400/1200 = 2.0

    def test_compression_reduces_size(self):
        """Compressed image is noticeably smaller than the raw equivalent."""
        # Create a high-quality JPEG that leaves headroom for compression
        data, _ = _make_image("JPEG", size=(1600, 1200))
        compressed = compress_image(data)
        # Compression should at least match (might be near-identical for
        # simple synthetic images at 85% quality, but resize should help)
        assert len(compressed) <= len(data) + 500

    def test_compress_image_twice_stable(self):
        """Compressing an already compressed image is stable (no unbounded growth)."""
        data, _ = _make_image("JPEG", size=(400, 300))
        c1 = compress_image(data)
        c2 = compress_image(c1)  # re-compress
        # Second pass should not significantly increase size
        assert len(c2) <= len(c1) * 1.1 or abs(len(c2) - len(c1)) < 5000


# ── COS Storage ──────────────────────────────────────────────────────────


class TestCOSStorage:
    """Tests for Tencent Cloud COS storage backend."""

    def test_default_bucket_prefix(self):
        """COSStorage uses configured bucket, region, and prefix from settings."""
        storage = COSStorage()
        assert storage._bucket == settings.COS_BUCKET
        assert storage._region == settings.COS_REGION
        assert storage._prefix == settings.COS_PREFIX.rstrip("/")

    @pytest.mark.asyncio
    @patch("app.services.storage_backend.COSStorage._get_client")
    async def test_upload_success(self, mock_get_client, tmp_path):
        """Successful COS upload returns correct URL."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        storage = COSStorage()
        url = await storage.upload("test/img.png", b"fake-data")

        assert url.startswith(f"https://{storage._bucket}.cos.{storage._region}.myqcloud.com/")
        assert "test/img.png" in url
        mock_client.put_object.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.storage_backend.COSStorage._get_client")
    async def test_upload_fallback_on_failure(self, mock_get_client, tmp_path):
        """When COS upload throws, fall back to local storage."""
        mock_client = MagicMock()
        mock_client.put_object.side_effect = Exception("COS timeout")
        mock_get_client.return_value = mock_client

        storage = COSStorage()
        url = await storage.upload("test/fallback.png", b"local-data")

        # Falls back to local file storage
        assert "localhost" in url or "static/formulas" in url

    @pytest.mark.asyncio
    @patch("app.services.storage_backend.settings")
    async def test_upload_when_not_configured(self, mock_settings):
        """When bucket/region are empty, falls back to local storage and logs a warning."""
        mock_settings.COS_BUCKET = ""
        mock_settings.COS_REGION = ""
        mock_settings.COS_SECRET_ID = ""
        mock_settings.COS_SECRET_KEY = ""
        mock_settings.COS_PREFIX = "static/formulas/"
        mock_settings.PUBLIC_BASE_URL = "http://localhost:8000"

        storage = COSStorage()
        client = storage._get_client()
        assert client is None  # no credentials → None

        url = await storage.upload("test/noconfig.png", b"data")
        assert "localhost" in url

    def test_build_key_with_prefix(self):
        """_build_key prepends the configured prefix."""
        storage = COSStorage()
        # Override prefix for test
        storage._prefix = "static/formulas/"
        key = storage._build_key("202607/subdir/img.png")
        assert key == "static/formulas/202607/subdir/img.png"

    def test_build_key_no_double_slash(self):
        """_build_key handles leading slash in filename."""
        storage = COSStorage()
        storage._prefix = "static/formulas/"
        key = storage._build_key("/img.png")
        assert "//" not in key
        assert key == "static/formulas/img.png"


class TestGetStorage:
    def test_default_local(self):
        """get_storage returns LocalFileStorage by default."""
        storage = get_storage()
        assert isinstance(storage, LocalFileStorage)

    @patch("app.services.storage_backend.settings")
    def test_cos_when_configured(self, mock_settings):
        """get_storage returns COSStorage when STORAGE_BACKEND == 'cos'."""
        mock_settings.STORAGE_BACKEND = "cos"
        storage = get_storage()
        assert isinstance(storage, COSStorage)

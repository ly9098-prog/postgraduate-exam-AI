import io

import pytest
from PIL import Image, ImageFile

from app.services import user_service


def _png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("L", (width, height), 0).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def test_avatar_rejects_oversized_dimensions_before_decode(monkeypatch):
    payload = _png(8192, 4096)
    loaded = []
    original_load = ImageFile.ImageFile.load

    def spy_load(self, *args, **kwargs):
        loaded.append(self.size)
        return original_load(self, *args, **kwargs)

    monkeypatch.setattr(ImageFile.ImageFile, "load", spy_load)
    with pytest.raises(ValueError):
        user_service._normalize_avatar_bytes(payload)
    assert loaded == []


def test_avatar_dimension_boundaries():
    limit = user_service.MAX_AVATAR_DIMENSION
    user_service._normalize_avatar_bytes(_png(limit, 8))
    with pytest.raises(ValueError):
        user_service._normalize_avatar_bytes(_png(limit + 1, 8))
    with pytest.raises(ValueError):
        user_service._normalize_avatar_bytes(_png(8, limit + 1))


def test_avatar_corrupt_png_maps_to_value_error():
    data = bytearray(_png(64, 64))
    data[40:60] = b"\x00" * 20
    with pytest.raises(ValueError):
        user_service._normalize_avatar_bytes(bytes(data))


def test_avatar_accepts_normal_image():
    out = user_service._normalize_avatar_bytes(_png(600, 400))
    assert Image.open(io.BytesIO(out)).size == (
        user_service.AVATAR_SIZE,
        user_service.AVATAR_SIZE,
    )

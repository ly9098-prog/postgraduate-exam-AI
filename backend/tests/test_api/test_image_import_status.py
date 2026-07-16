from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.v1 import imports
from app.services import import_pipeline_service as pipeline_svc


class FakeCache:
    def __init__(self):
        self.values = {}
        self.ttls = {}
        self.fail_set = False
        self.fail_get = False

    async def get(self, key):
        if self.fail_get:
            raise RuntimeError("cache unavailable")
        return self.values.get(key)

    async def set(self, key, value, ttl=300):
        if self.fail_set:
            raise RuntimeError("cache unavailable")
        self.values[key] = value
        self.ttls[key] = ttl


@pytest.fixture(autouse=True)
def clear_image_status_store():
    pipeline_svc._image_pipeline_store.clear()
    yield
    pipeline_svc._image_pipeline_store.clear()


@pytest.fixture
def fake_cache(monkeypatch):
    cache = FakeCache()
    monkeypatch.setattr(pipeline_svc, "cache", cache)
    return cache


@pytest.mark.asyncio
async def test_set_image_pipeline_status_writes_cache_and_memory(fake_cache):
    status = await pipeline_svc._set_image_pipeline_status("img_1", status="queued")

    assert pipeline_svc._image_pipeline_store["img_1"] == status
    assert fake_cache.values[pipeline_svc._image_pipeline_key("img_1")] == status
    assert fake_cache.ttls[pipeline_svc._image_pipeline_key("img_1")] == 86400


@pytest.mark.asyncio
async def test_get_image_pipeline_status_reads_cache_after_memory_clear(fake_cache):
    await pipeline_svc._set_image_pipeline_status("img_1", status="queued")
    pipeline_svc._image_pipeline_store.clear()

    status = await pipeline_svc._get_image_pipeline_status("img_1")

    assert status["pipeline_id"] == "img_1"
    assert status["status"] == "queued"


@pytest.mark.asyncio
async def test_get_image_pipeline_status_falls_back_to_memory_on_cache_miss(fake_cache):
    pipeline_svc._image_pipeline_store["img_1"] = {"pipeline_id": "img_1", "status": "parsing"}

    status = await pipeline_svc._get_image_pipeline_status("img_1")

    assert status == {"pipeline_id": "img_1", "status": "parsing"}


@pytest.mark.asyncio
async def test_cache_set_exception_keeps_memory_status(fake_cache):
    fake_cache.fail_set = True

    status = await pipeline_svc._set_image_pipeline_status("img_1", status="ocr_running")

    assert status["status"] == "ocr_running"
    assert pipeline_svc._image_pipeline_store["img_1"]["status"] == "ocr_running"


@pytest.mark.asyncio
async def test_set_image_pipeline_status_ignores_pipeline_id_update(fake_cache):
    status = await pipeline_svc._set_image_pipeline_status(
        "img_1",
        pipeline_id="other",
        status="completed",
    )

    assert status["pipeline_id"] == "img_1"
    assert status["status"] == "completed"


@pytest.mark.asyncio
async def test_get_image_pipeline_status_falls_back_to_memory_on_cache_error(fake_cache):
    fake_cache.fail_get = True
    pipeline_svc._image_pipeline_store["img_1"] = {"pipeline_id": "img_1", "status": "parsing"}

    status = await pipeline_svc._get_image_pipeline_status("img_1")

    assert status == {"pipeline_id": "img_1", "status": "parsing"}


def test_build_ocr_text_diagnostics_tracks_raw_and_cleaned_text():
    diagnostics = pipeline_svc._build_ocr_text_diagnostics(
        "31. 原始题干\n\nA. 选项A\nB. 选项B\n",
        "31. 原始题干\nA. 选项A B. 选项B",
    )

    assert diagnostics == {
        "raw_text_length": 24,
        "cleaned_text_length": 22,
        "raw_line_count": 3,
        "cleaned_line_count": 2,
        "raw_text_preview": "31. 原始题干\n\nA. 选项A\nB. 选项B\n",
        "cleaned_text_preview": "31. 原始题干\nA. 选项A B. 选项B",
        "text_length_delta": 2,
        "line_count_delta": 1,
    }


@pytest.mark.asyncio
async def test_fail_image_pipeline_appends_error_and_finishes(fake_cache):
    await pipeline_svc._set_image_pipeline_status(
        "img_1",
        errors=["first"],
        stages={"upload": {"status": "completed"}, "ocr": {"status": "running"}},
    )

    await pipeline_svc._fail_image_pipeline("img_1", "second")

    status = pipeline_svc._image_pipeline_store["img_1"]
    assert status["status"] == "failed"
    assert status["errors"] == ["first", "second"]
    assert status["stages"]["upload"] == {"status": "completed"}
    assert status["stages"]["ocr"] == {"status": "failed", "error": "second"}
    assert status["finished_at"]


@pytest.mark.asyncio
async def test_pipeline_status_returns_old_pipeline_first(monkeypatch, fake_cache):
    old_status = {"pipeline_id": "same", "status": "completed", "batch_id": "old_batch"}
    monkeypatch.setattr(imports, "svc_get_pipeline_status", AsyncMock(return_value=old_status))
    await pipeline_svc._set_image_pipeline_status("same", status="failed", batch_id="image_batch")

    response = await imports.pipeline_status("same", None)

    assert response["batch_id"] == "old_batch"
    assert response["status"] == "completed"


@pytest.mark.asyncio
async def test_pipeline_status_returns_image_status_when_old_missing(monkeypatch, fake_cache):
    # Mock orchestrator to return None so svc_get_pipeline_status falls through
    # to image pipeline store.
    monkeypatch.setattr(pipeline_svc, "_orchestrator_get_pipeline_status", AsyncMock(return_value=None))
    await pipeline_svc._set_image_pipeline_status("img_1", status="completed", batch_id="image_batch")

    response = await imports.pipeline_status("img_1", None)

    assert response.batch_id == "image_batch"
    assert response.status == "completed"


@pytest.mark.asyncio
async def test_pipeline_status_raises_404_when_missing(monkeypatch, fake_cache):
    monkeypatch.setattr(pipeline_svc, "_orchestrator_get_pipeline_status", AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as exc:
        await imports.pipeline_status("missing", None)

    assert exc.value.status_code == 404

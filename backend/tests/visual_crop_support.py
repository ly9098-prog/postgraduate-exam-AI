"""Synthetic visual-crop ports; executors record work without reading images."""

import datetime
import logging
from types import SimpleNamespace
from unittest.mock import Mock

from app.core import executor_registry
from app.features import pipeline_orchestrator as target
from app.services import storage_backend, visual_region_cropper


class FrozenDatetime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 27, 8)


class VisualCropHarness:
    def __init__(self, monkeypatch):
        self.pipeline = SimpleNamespace(pipeline_id="visual-crop-test")
        self.pages = {1: "/synthetic/page-1.png", 2: "/synthetic/page-2.png"}
        self.trace = []
        self.regions = []
        self.jobs = []
        self.uploads = []
        self.png = b"synthetic-png"
        self.region_url = "storage://region.png"
        self.crop_failed = False
        self.errors = {}
        self.logger = Mock()
        self.storage = SimpleNamespace(upload=self.upload)
        original_logger = logging.getLogger

        def get_logger(name=None):
            return self.logger if name == target.__name__ else original_logger(name)

        monkeypatch.setattr(logging, "getLogger", get_logger)
        monkeypatch.setattr(datetime, "datetime", FrozenDatetime)
        monkeypatch.setattr(storage_backend, "get_storage", self.get_storage)
        monkeypatch.setattr(visual_region_cropper, "crop_and_upload_region", self.crop)
        monkeypatch.setattr(executor_registry, "get_executor", self.executor)

    def check(self, stage):
        self.trace.append(stage)
        if stage in self.errors:
            raise self.errors[stage]

    def get_storage(self):
        self.check("storage")
        return self.storage

    async def crop(self, pages, region, import_id):
        assert pages is self.pages
        self.regions.append((region, import_id))
        self.check("crop")
        region.image_url = self.region_url
        region.crop_failed = self.crop_failed
        return region

    def executor(self, name):
        self.check(("executor", name))

        async def run(function, *args, **kwargs):
            self.jobs.append((name, function, args, kwargs))
            self.check("run")
            return self.png

        return SimpleNamespace(run=run)

    async def upload(self, key, payload):
        self.uploads.append((key, payload))
        self.check("upload")
        return "storage://snapshot.png"

    async def run(self, questions, pages=None):
        return await target.ImportPipeline._run_visual_region_crop(
            self.pipeline,
            questions,
            self.pages if pages is None else pages,
        )


def region(**kwargs):
    return {
        "region_id": "r1",
        "region_type": "diagram",
        "source_page": 1,
        "bbox": [10, 20, 100, 200],
        **kwargs,
    }

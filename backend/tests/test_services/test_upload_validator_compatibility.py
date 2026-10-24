"""Real compatibility baseline for upload validator against OCR profiles."""

from __future__ import annotations

import pytest
from dataclasses import dataclass

from app.services.upload_validator import UploadValidator


@dataclass
class FakeProfile:
    name: str = "test"
    allowed_source_types: tuple = ("pdf", "excel", "image", "txt")
    max_pdf_pages: int = 0
    max_upload_bytes: int = 0
    max_batch_files: int = 0


class TestValidateFile:
    def test_accepts_allowed_extension(self):
        v = UploadValidator(FakeProfile())
        v.validate_file("test.pdf", 1000)

    def test_rejects_disallowed_source_type(self):
        profile = FakeProfile(allowed_source_types=("pdf", "txt"))
        v = UploadValidator(profile)
        with pytest.raises(ValueError, match="不支持"):
            v.validate_file("test.xlsx", 1000)

    def test_rejects_oversized_file(self):
        profile = FakeProfile(max_upload_bytes=1024)
        v = UploadValidator(profile)
        with pytest.raises(ValueError, match="文件大小超过"):
            v.validate_file("test.pdf", 2048)

    def test_accepts_within_size_limit(self):
        profile = FakeProfile(max_upload_bytes=2048)
        v = UploadValidator(profile)
        v.validate_file("test.pdf", 1024)

    def test_zero_size_limit_means_unlimited(self):
        profile = FakeProfile(max_upload_bytes=0)
        v = UploadValidator(profile)
        v.validate_file("test.pdf", 999_999_999)

    def test_unknown_extension_passes(self):
        v = UploadValidator(FakeProfile())
        v.validate_file("test.unknown", 1000)


class TestValidatePdfPages:
    def test_zero_limit_means_unlimited(self):
        v = UploadValidator(FakeProfile(max_pdf_pages=0))
        v.validate_pdf_pages(9999)

    def test_rejects_over_limit(self):
        v = UploadValidator(FakeProfile(max_pdf_pages=100))
        with pytest.raises(ValueError, match="PDF 页数"):
            v.validate_pdf_pages(200)

    def test_accepts_at_limit(self):
        v = UploadValidator(FakeProfile(max_pdf_pages=100))
        v.validate_pdf_pages(100)


class TestValidateBatchSize:
    def test_zero_limit_means_unlimited(self):
        v = UploadValidator(FakeProfile(max_batch_files=0))
        v.validate_batch_size(9999)

    def test_rejects_over_limit(self):
        v = UploadValidator(FakeProfile(max_batch_files=10))
        with pytest.raises(ValueError, match="批量上传数量"):
            v.validate_batch_size(20)

    def test_accepts_at_limit(self):
        v = UploadValidator(FakeProfile(max_batch_files=10))
        v.validate_batch_size(10)

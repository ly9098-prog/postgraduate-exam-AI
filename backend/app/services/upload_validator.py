from pathlib import Path

from app.core.ocr_profile import OCRProfile, get_ocr_profile

_EXT_TO_SOURCE_TYPE = {
    ".pdf": "pdf",
    ".xlsx": "excel",
    ".xls": "excel",
    ".txt": "txt",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".webp": "image",
}


class UploadValidator:
    def __init__(self, profile: OCRProfile):
        self._profile = profile

    def validate_file(
        self, filename: str, size: int, content_type: str | None = None
    ) -> None:
        ext = Path(filename).suffix.lower()
        source_type = _EXT_TO_SOURCE_TYPE.get(ext)

        if source_type and source_type not in self._profile.allowed_source_types:
            raise ValueError(
                f"当前环境（{self._profile.name}）不支持 {ext} 文件导入，建议在本地导入后同步至云端",
            )

        if self._profile.max_upload_bytes and size > self._profile.max_upload_bytes:
            limit_mb = self._profile.max_upload_bytes / (1024 * 1024)
            raise ValueError(
                f"文件大小超过当前环境限制（{limit_mb:.0f}MB），建议在本地导入后同步至云端",
            )

    def validate_pdf_pages(self, total_pages: int) -> None:
        if self._profile.max_pdf_pages and total_pages > self._profile.max_pdf_pages:
            raise ValueError(
                f"PDF 页数（{total_pages}）超过当前环境限制（{self._profile.max_pdf_pages}页），建议在本地导入后同步至云端",
            )

    def validate_batch_size(self, file_count: int) -> None:
        if self._profile.max_batch_files and file_count > self._profile.max_batch_files:
            raise ValueError(
                f"批量上传数量（{file_count}）超过当前环境限制（{self._profile.max_batch_files}），建议在本地导入后同步至云端",
            )


def get_upload_validator() -> UploadValidator:
    return UploadValidator(get_ocr_profile())

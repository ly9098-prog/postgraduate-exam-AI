import os
from abc import ABC, abstractmethod

from app.core.config import settings


class StorageBackend(ABC):
    @abstractmethod
    async def upload(self, filename: str, data: bytes) -> str:
        """上传图片，返回绝对 HTTP URL"""
        ...


class LocalFileStorage(StorageBackend):
    async def upload(self, filename: str, data: bytes) -> str:
        # filename 形如 "YYYYMM/import_id_page_hash.png"
        filepath = os.path.join("static/formulas", filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(data)
        return f"{settings.PUBLIC_BASE_URL}/static/formulas/{filename}"


class COSStorage(StorageBackend):
    async def upload(self, filename: str, data: bytes) -> str:
        raise NotImplementedError("COS 存储后端尚未配置凭证")


def get_storage() -> StorageBackend:
    if settings.STORAGE_BACKEND == "cos":
        return COSStorage()
    return LocalFileStorage()

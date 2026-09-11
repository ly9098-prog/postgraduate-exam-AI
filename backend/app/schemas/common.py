from math import ceil
from typing import Generic, TypeVar

from app.schemas.base import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int


class RawPaginatedResponse(BaseModel):
    """Pagination envelope without item-type validation (for dict-based list endpoints)."""

    items: list[dict]
    total: int
    page: int
    page_size: int
    total_pages: int


def paginated_response(
    items: list,
    total: int,
    page: int,
    page_size: int,
) -> dict:
    """构建统一分页响应，确保分页字段一致。"""
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(ceil(total / page_size), 1) if total > 0 else 0,
    }

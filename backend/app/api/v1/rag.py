from fastapi import APIRouter, Depends, HTTPException

from app.core.deployment_profile import is_restricted_environment
from app.core.security import get_current_user
from app.models.user import User
from app.core.runtime_paths import API_V1_PREFIX
from rag.context_builder import build_context

router = APIRouter(prefix=f"{API_V1_PREFIX}/rag")


def require_dev_rag_access() -> None:
    """RAG returns repository source chunks; developer tooling only."""
    if is_restricted_environment():
        raise HTTPException(status_code=404, detail="Not Found")


@router.get("/search", dependencies=[Depends(require_dev_rag_access)])
async def search(
    query: str,
    top_k: int = 3,
    _: User = Depends(get_current_user),
):
    """检索最相关的前端+后端模块。"""
    from rag.retriever import retrieve

    results = retrieve(query, top_k=top_k)
    if not results:
        raise HTTPException(status_code=404, detail="无匹配模块")
    return {"query": query, "results": results}


@router.get("/context", dependencies=[Depends(require_dev_rag_access)])
async def get_context(
    query: str,
    _: User = Depends(get_current_user),
):
    """构建结构化上下文（前后端分离）。"""
    result = build_context(query)
    if result["is_empty"]:
        raise HTTPException(status_code=404, detail="无匹配上下文")
    return result

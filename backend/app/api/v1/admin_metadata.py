"""管理端题型元数据接口 — 从后端 QuestionType 领域定义动态生成。

不读取数据库字典表，不提供新增/编辑/删除操作。
"""

from fastapi import APIRouter, Depends

from app.core.admin_security import require_permissions
from app.core.runtime_paths import API_ADMIN_V1_PREFIX
from app.features.question_type import get_question_type_metadata_items

router = APIRouter(prefix=f"{API_ADMIN_V1_PREFIX}/metadata", tags=["admin-metadata"])


@router.get("/question-types")
async def list_question_types(
    _=Depends(require_permissions("import:read")),
):
    """返回题型元数据列表，按 sort_order 稳定排序。

    code 来自 QuestionType 枚举，label 和能力配置来自同一后端定义。
    不读取数据库，不需要缓存失效。
    """
    return {
        "items": get_question_type_metadata_items(),
    }

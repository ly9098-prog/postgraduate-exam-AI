import asyncio
import json
import logging
import time
from urllib.parse import urljoin, urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import OpenAICompatibleAPIError, llm
from app.core.admin_security import AdminPrincipal
from app.core.config import settings
from app.core.log_context import get_trace_headers
from app.core.secret_crypto import (
    SecretDecryptionError,
    SecretEncryptionError,
    decrypt_secret,
    encrypt_secret,
)
from app.core.time_utils import utcnow
from app.models.admin_ai_config import AdminAiConfig, AdminAiModelConfig

logger = logging.getLogger(__name__)
from app.schemas.admin_ai_config import (
    AdminAiModelConfigCreateRequest,
    AdminAiModelConfigPatchRequest,
    AdminAiModelConfigResponse,
)
from app.services.admin_audit_service import write_admin_audit
from app.services.safe_remote_fetch import (
    UnsafeRemoteURLError,
    request_remote_bytes,
    validate_remote_url,
)

# ---------------------------------------------------------------------------
# In-memory TTL cache — avoids DB query on every single-question completion.
# Cleared automatically on write (patch / seed).
# ---------------------------------------------------------------------------

_config_cache: dict | None = None
_config_cache_time: float = 0
_CONFIG_CACHE_TTL = 10  # seconds


def _clear_config_cache() -> None:
    global _config_cache, _config_cache_time
    _config_cache = None
    _config_cache_time = 0


# ---------------------------------------------------------------------------
# Default config values — mirrors app/ai/prompts.py
# ---------------------------------------------------------------------------

_DEFAULT_CONFIGS: dict[str, str] = {
    "ocr_correction_prompt": (
        "你是 OCR 文本纠错助手。输入是 OCR 识别的考研题目文本片段。\n"
        "你的任务是修复 OCR 识别错误，保持原文含义不变。\n\n"
        "修复规则：\n"
        "1. 修复换行错乱：被错误断开的句子重新拼接为完整句\n"
        "2. 修复选项错位：确保 A/B/C/D 选项各占独立行\n"
        "3. 修复题号缺失：如果上下文明确有题号但缺失，补上（如 1. 2. 等）\n"
        "4. 修复 OCR 错字：选项标号中 8→B、6→G、0→D、l→1、O→0 等\n"
        "5. 修复标点错乱：中英文标点混用、缺失等\n"
        "6. 修复计算机专业术语 OCR 错误：\n"
        "   方武→方式、进稈→进程、协汉→协议、线稈→线程、死铐→死锁\n"
        "   数据枸构→数据结构、操作糸统→操作系统、编释器→编译器\n"
        "   堆找→堆栈、链哀→链表、二叉村→二叉树、递归→递归\n"
        "   冲突检侧→冲突检测、调度箅法→调度算法、虚拟内仔→虚拟内存\n"
        "   网绔→网络、路甶器→路由器、传输曾→传输层、TCP/IP协汉→TCP/IP协议\n"
        "   中斷→中断、缓冲→缓冲、寄仔器→寄存器、磁盐→磁盘\n"
        "7. 修复数学术语 OCR 错误：\n"
        "   导敖→导数、积兮→积分、极眼→极限、矩陣→矩阵\n"
        "   连统→连续、可异→可导、收敛→收敛、级敖→级数\n"
        "   微兮→微分、偏异数→偏导数、线性伐数→线性代数\n"
        "   行列或→行列式、特征俌→特征值、向里→向量\n"
        "   函敖→函数、方稈→方程、不等或→不等式、概率→概率\n"
        "8. 保持专业缩写完整：TCP/UDP/HTTP/DNS/ARP/ICMP/IP/OS 等不要拆分或修改\n\n"
        "禁止规则：\n"
        "- 禁止添加原文中不存在的内容（不要补充答案、解析等）\n"
        "- 禁止修改题目实质含义\n"
        "- 禁止重新排版或添加格式标记\n"
        "- 如果文本质量已经很好，原样返回即可\n\n"
        "输出格式：直接返回纠错后的纯文本，不要包含任何 JSON、代码块或其他标记。"
    ),
    "ocr_strategy_math_formula": "true",
    "ocr_strategy_punctuation": "true",
    "ocr_strategy_digit_letter": "true",
    "ocr_strategy_space_newline": "false",
    "ocr_structure_question_type": "true",
    "ocr_structure_options": "true",
    "ocr_structure_answer": "true",
    "ocr_structure_analysis": "true",
    "ocr_filter_max_chars": "2000",
    "ocr_filter_max_tokens": "4096",
    "ocr_filter_sensitive": "true",
    # OCR 纠错模型路由配置
    "ocr_fix_model": "openai-compatible",
    "ocr_fix_strategy": "auto",
    "completion_prompt": (
        "你是考研题目补全助手。根据已有的题干和上下文，补全缺失字段。"
        "你的输出仅是辅助提示，必须经过人工审核后才能采用。"
        "如果你不确定，请将对应字段留空字符串而不要编造。\n"
        "数学公式输出规则：所有数学内容用 LaTeX（行内 $...$，块级 $$...$$），"
        "禁止使用 Unicode 数学符号。\n"
        "请用中文回答，严格 JSON 格式输出。\n\n"
        "有效学科（subject）值：\n"
        "- math2（数学二通用，无法确定子类时使用）\n"
        "- math2-calculus（数学二-微积分）\n"
        "- math2-linalg（数学二-线性代数）\n"
        "- exam408（408 统考通用，无法确定子类时使用）\n"
        "- data_structure（408-数据结构）\n"
        "- operating_system（408-操作系统）\n"
        "- computer_organization（408-计算机组成原理）\n"
        "- computer_network（408-计算机网络）\n"
        "- english（英语）\n\n"
        "有效题型（question_type）值：\n"
        "- single_choice（单选题）\n"
        "- multiple_choice（多选题）\n"
        "- true_false（判断题）\n"
        "- fill_blank（填空题）\n"
        "- multi_blank_choice（多空（单选）选择题，每空一个选项）\n"
        "- multi_blank_multiple_choice（多空（多选）选择题，每空可选多个选项）\n"
        "- subjective（主观题/简答题）\n\n"
        "推断规则：\n"
        "- 优先根据题干内容推断最具体的子学科，无法确定时使用大类\n"
        "- 数学题干出现极限/导数/积分/微分 → math2-calculus\n"
        "- 数学题干出现矩阵/向量/特征值/行列式/线性 → math2-linalg\n"
        "- 408 题干出现链表/树/图/排序/查找/算法 → data_structure\n"
        "- 408 题干出现进程/线程/死锁/内存/文件系统 → operating_system\n"
        "- 408 题干出现 CPU/指令/流水线/Cache/总线 → computer_organization\n"
        "- 408 题干出现 TCP/IP/HTTP/DNS/路由/子网 → computer_network\n\n"
        "输出 JSON 格式：\n"
        '{"subject": "math2-calculus", '
        '"question_type": "single_choice", '
        '"answer": "A", '
        '"analysis": "解析（若不确定可留空）", '
        '"knowledge_points": ["知识点1"], '
        '"difficulty": 3, '
        '"answer_uncertain": false, '
        '"confidence": 0.6, '
        '"reason": "推理依据"}'
    ),
    "completion_auto_stem": "true",
    "completion_auto_options": "true",
    "completion_auto_answer_reasoning": "false",
    "completion_auto_knowledge_tags": "true",
    "completion_repair_structure": "false",
}

_DEFAULT_MODELS: list[dict] = [
    {
        "name": "deepseek-v4-flash",
        "display_name": "DeepSeek V4 Flash",
        "provider": "deepseek",
        "api_base_url": "https://api.deepseek.com",
        "is_enabled": True,
        "is_default": True,
        "sort_order": 1,
        "feature": None,
        "features": None,
    },
]


def _parse_features(features_val: list[str] | None) -> list[str]:
    """安全解析 features 字段，处理 None 情况。"""
    return features_val if features_val else []


def _validate_model_feature_shape(features: list[str] | None) -> None:
    """Enforce model-type boundaries encoded through capabilities.

    Embedding models are a distinct endpoint type and must not simultaneously
    participate in chat/OCR feature routing. This keeps the model registry
    unambiguous without adding a schema migration for ``model_type``.
    """
    values = set(features or [])
    if "embedding" in values and len(values) > 1:
        raise ValueError(
            "Embedding 模型不能同时绑定 Chat/OCR 功能；请将模型类型设为 Embedding"
        )


def _single_assignment_overlap(
    features: list[str], other_features: list[str]
) -> set[str]:
    """Return capabilities that still require a single active model.

    ``embedding`` is intentionally excluded because vector config explicitly
    selects one registered Embedding model, so multiple candidates may stay
    enabled at the same time.
    """
    return (set(features) & set(other_features)) - {"embedding"}


def _reset_vector_runtime_cache() -> None:
    """Invalidate vector runtime cache after model-registry changes."""
    try:
        from app.services.vector_retrieval_service import _reset_vector_enabled_cache

        _reset_vector_enabled_cache()
    except Exception:
        # Avoid creating a hard dependency/cycle during startup or migrations.
        pass


def _validated_api_base_url(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().rstrip("/")
    if not normalized:
        return None
    parsed = urlsplit(normalized)
    if parsed.query or parsed.fragment:
        raise ValueError("API Base URL 不能包含查询参数或片段")
    try:
        validate_remote_url(
            normalized,
            allow_http=settings.AI_ALLOW_HTTP_BASE_URLS,
        )
    except UnsafeRemoteURLError as exc:
        raise ValueError(f"API Base URL 不安全或不可用: {exc}") from exc
    return normalized


def _same_origin(left: str, right: str) -> bool:
    try:
        l = urlsplit(left)
        r = urlsplit(right)
        l_port = l.port or (443 if l.scheme == "https" else 80)
        r_port = r.port or (443 if r.scheme == "https" else 80)
    except ValueError:
        return False
    return (
        l.scheme.lower(),
        (l.hostname or "").lower(),
        l_port,
    ) == (
        r.scheme.lower(),
        (r.hostname or "").lower(),
        r_port,
    )


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_configs_if_empty(db: AsyncSession):
    result = await db.execute(select(AdminAiConfig).limit(1))
    if result.scalar_one_or_none() is not None:
        return
    for key, value in _DEFAULT_CONFIGS.items():
        db.add(AdminAiConfig(config_key=key, config_value=value))
    await db.flush()
    _clear_config_cache()


async def _seed_models_if_empty(db: AsyncSession):
    result = await db.execute(select(AdminAiModelConfig).limit(1))
    if result.scalar_one_or_none() is not None:
        return
    for m in _DEFAULT_MODELS:
        model = AdminAiModelConfig(**m)
        db.add(model)
    await db.flush()


async def _ensure_env_key_synced(db: AsyncSession):
    pass  # removed: API keys are DB-only


# ---------------------------------------------------------------------------
# Model config
# ---------------------------------------------------------------------------


def _model_to_response(m: AdminAiModelConfig) -> AdminAiModelConfigResponse:
    api_ok = False
    api_key_masked = None
    if m.api_key_encrypted:
        try:
            raw = decrypt_secret(m.api_key_encrypted)
            if raw:
                api_ok = True
                api_key_masked = "********"
        except (SecretDecryptionError, SecretEncryptionError):
            api_ok = False
    return AdminAiModelConfigResponse(
        id=m.id,
        name=m.name,
        display_name=m.display_name,
        provider=m.provider,
        api_base_url=m.api_base_url,
        api_configured=api_ok,
        api_key_masked=api_key_masked,
        is_enabled=m.is_enabled,
        is_default=m.is_default,
        sort_order=m.sort_order,
        feature=m.feature,
        features=m.features,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


async def list_models(db: AsyncSession) -> list[AdminAiModelConfigResponse]:
    await _seed_models_if_empty(db)
    await _ensure_env_key_synced(db)
    result = await db.execute(
        select(AdminAiModelConfig)
        .where(AdminAiModelConfig.deleted_at.is_(None))
        .order_by(
            AdminAiModelConfig.is_default.desc(),
            AdminAiModelConfig.sort_order,
        )
    )
    return [_model_to_response(m) for m in result.scalars().all()]


async def patch_model(
    db: AsyncSession,
    model_id: int,
    data: AdminAiModelConfigPatchRequest,
    operator: AdminPrincipal,
) -> AdminAiModelConfigResponse:
    model = await db.get(AdminAiModelConfig, model_id)
    if model is None or model.deleted_at is not None:
        raise ValueError(f"模型 {model_id} 不存在")

    changes = {}

    if data.name is not None and data.name.strip():
        model.name = data.name.strip()
        changes["name"] = data.name.strip()
    if data.display_name is not None and data.display_name.strip():
        model.display_name = data.display_name.strip()
        changes["display_name"] = data.display_name.strip()
    if data.provider is not None and data.provider.strip():
        model.provider = data.provider.strip().lower()
        changes["provider"] = model.provider

    if data.is_default is True:
        # 清除其它模型的 default 标志
        old_defaults = await db.execute(
            select(AdminAiModelConfig).where(
                AdminAiModelConfig.is_default == True,  # noqa: E712
                AdminAiModelConfig.deleted_at.is_(None),
                AdminAiModelConfig.id != model_id,
            )
        )
        for other in old_defaults.scalars().all():
            other.is_default = False
            other.updated_at = utcnow()

    if data.is_enabled is not None:
        model.is_enabled = data.is_enabled
        changes["is_enabled"] = data.is_enabled
    if data.is_default is not None:
        model.is_default = data.is_default
        changes["is_default"] = data.is_default
    # API key: use get_api_key_value() which handles None and mask placeholders
    new_key = data.get_api_key_value()
    if data.api_base_url is not None:
        new_base_url = _validated_api_base_url(data.api_base_url)
        if not new_base_url:
            raise ValueError("API Base URL 不能为空")
        old_base_url = (model.api_base_url or "").rstrip("/") or None
        if new_base_url != old_base_url and model.api_key_encrypted and new_key is None:
            raise ValueError("修改 API Base URL 时必须同时重新提交 API Key")
        model.api_base_url = new_base_url
        changes["api_base_url"] = new_base_url

    if new_key is not None:
        model.api_key_encrypted = encrypt_secret(new_key)
        changes["api_key_updated"] = True

    if "features" in data.model_fields_set:
        new_features = data.features
        _validate_model_feature_shape(new_features)
        if new_features:
            # Chat/OCR 功能仍保持单模型映射；Embedding 由向量配置显式选择，允许多个候选。
            is_becoming_enabled = (
                data.is_enabled if data.is_enabled is not None else model.is_enabled
            )
            if is_becoming_enabled:
                # 查出所有其他已启用模型，在 Python 层做 features 交集检查
                all_enabled = await db.execute(
                    select(AdminAiModelConfig).where(
                        AdminAiModelConfig.id != model_id,
                        AdminAiModelConfig.is_enabled == True,  # noqa: E712
                        AdminAiModelConfig.deleted_at.is_(None),
                    )
                )
                for other in all_enabled.scalars().all():
                    other_features = _parse_features(other.features)
                    overlap = _single_assignment_overlap(new_features, other_features)
                    if overlap:
                        raise ValueError(
                            f"功能层「{list(overlap)[0]}」已有启用模型"
                            f"「{other.display_name}」，"
                            "请先禁用该模型再切换"
                        )
            model.features = new_features
            # 同步旧字段：取第一个 feature 写入
            model.feature = new_features[0]
        else:
            model.features = None
            model.feature = None
        changes["features"] = model.features

    # 向后兼容：单独写 feature 时同步到 features
    if "feature" in data.model_fields_set and "features" not in data.model_fields_set:
        if data.feature:
            model.features = [data.feature]
        else:
            model.features = None
        changes["features"] = model.features

    # 当前向量配置如果正引用此模型，而模型被禁用或不再是 Embedding，
    # 自动清除选择，避免保留一个永远不可用的 model id。
    selected_embedding = await db.get(AdminAiConfig, "embedding_model_config_id")
    if (
        selected_embedding is not None
        and selected_embedding.config_value == str(model_id)
        and (not model.is_enabled or "embedding" not in _parse_features(model.features))
    ):
        selected_embedding.config_value = ""
        changes["embedding_selection_cleared"] = True

    model.updated_at = utcnow()
    await db.flush()
    _reset_vector_runtime_cache()

    await write_admin_audit(
        db,
        operator,
        "ai_model_config.update",
        "ai_model_config",
        model.id,
        detail={"model_name": model.name, "changes": changes},
    )
    return _model_to_response(model)


async def create_model(
    db: AsyncSession,
    data: AdminAiModelConfigCreateRequest,
    operator: AdminPrincipal,
) -> AdminAiModelConfigResponse:
    """动态添加新模型。"""
    from sqlalchemy import func

    # 计算下一个 sort_order
    max_order = await db.scalar(select(func.max(AdminAiModelConfig.sort_order)))
    next_order = (max_order or 0) + 1

    new_features = data.features if data.features else None
    _validate_model_feature_shape(new_features)
    if new_features:
        # Chat/OCR 功能检查冲突；Embedding 候选允许并存。
        all_enabled = await db.execute(
            select(AdminAiModelConfig).where(
                AdminAiModelConfig.is_enabled == True,  # noqa: E712
                AdminAiModelConfig.deleted_at.is_(None),
            )
        )
        for other in all_enabled.scalars().all():
            other_features = _parse_features(other.features)
            overlap = _single_assignment_overlap(new_features, other_features)
            if overlap:
                raise ValueError(
                    f"功能层「{list(overlap)[0]}」已有启用模型"
                    f"「{other.display_name}」，"
                    "请先禁用该模型再创建新模型"
                )

    # 向后兼容：入参只传 feature 时同步到 features
    if "features" not in data.model_fields_set and data.feature:
        new_features = [data.feature]
    _validate_model_feature_shape(new_features)

    api_base_url = _validated_api_base_url(data.api_base_url)
    if not api_base_url:
        raise ValueError(
            "API Base URL 不能为空；请填写 OpenAI-compatible SDK 使用的 base_url"
        )
    model = AdminAiModelConfig(
        name=data.name.strip(),
        display_name=data.display_name.strip(),
        provider=data.provider.strip().lower(),
        api_base_url=api_base_url,
        is_enabled=True,
        is_default=False,
        sort_order=next_order,
        feature=new_features[0] if new_features else None,
        features=new_features,
    )
    new_key = data.get_api_key_value()
    if new_key:
        model.api_key_encrypted = encrypt_secret(new_key)
    db.add(model)
    await db.flush()
    _reset_vector_runtime_cache()

    await write_admin_audit(
        db,
        operator,
        "ai_model_config.create",
        "ai_model_config",
        model.id,
        detail={"model_name": model.name, "provider": model.provider},
    )
    return _model_to_response(model)


async def delete_model(
    db: AsyncSession,
    model_id: int,
    operator: AdminPrincipal,
) -> None:
    """软删除模型配置，同时保留稳定 ID 供历史记录继续引用。"""
    model = await db.get(AdminAiModelConfig, model_id)
    if model is None or model.deleted_at is not None:
        raise ValueError(f"模型 {model_id} 不存在")

    # 保留最后一个可用模型，避免软删除后系统完全失去 AI 能力。
    if model.is_enabled:
        result = await db.execute(
            select(AdminAiModelConfig).where(
                AdminAiModelConfig.is_enabled == True,  # noqa: E712
                AdminAiModelConfig.deleted_at.is_(None),
                AdminAiModelConfig.id != model_id,
            )
        )
        enabled_count = len(result.scalars().all())
        if enabled_count == 0:
            raise ValueError("不能删除最后一个启用的模型")

    selected_embedding = await db.get(AdminAiConfig, "embedding_model_config_id")
    selection_cleared = False
    if selected_embedding is not None and selected_embedding.config_value == str(
        model_id
    ):
        selected_embedding.config_value = ""
        selection_cleared = True

    now = utcnow()
    model.is_enabled = False
    model.is_default = False
    model.deleted_at = now
    model.updated_at = now

    await write_admin_audit(
        db,
        operator,
        "ai_model_config.delete",
        "ai_model_config",
        model.id,
        detail={
            "model_name": model.name,
            "soft_deleted": True,
            "embedding_selection_cleared": selection_cleared,
        },
    )
    await db.flush()
    _reset_vector_runtime_cache()


# ---------------------------------------------------------------------------
# Config key-value
# ---------------------------------------------------------------------------


async def get_all_configs(db: AsyncSession) -> dict:
    global _config_cache, _config_cache_time
    now = time.time()
    if _config_cache is not None and now - _config_cache_time < _CONFIG_CACHE_TTL:
        return _config_cache
    await _seed_configs_if_empty(db)
    result = await db.execute(select(AdminAiConfig))
    _config_cache = {
        row.config_key: _coerce_value(row.config_value)
        for row in result.scalars().all()
    }
    _config_cache_time = now
    return _config_cache


async def patch_configs(
    db: AsyncSession,
    updates: dict,
    operator: AdminPrincipal,
) -> dict:
    await _seed_configs_if_empty(db)
    changed_keys: list[str] = []

    MAX_PROMPT_LENGTH = 5000

    for key, value in updates.items():
        if key not in _DEFAULT_CONFIGS:
            continue  # 忽略不存在的 key
        if (
            key in ("ocr_correction_prompt", "completion_prompt")
            and len(str(value)) > MAX_PROMPT_LENGTH
        ):
            raise ValueError(f"{key} exceeds max length of {MAX_PROMPT_LENGTH}")
        serialized = str(value).lower() if isinstance(value, bool) else str(value)
        existing = await db.get(AdminAiConfig, key)
        if existing is None:
            db.add(
                AdminAiConfig(
                    config_key=key, config_value=serialized, updated_by=operator.id
                )
            )
        else:
            existing.config_value = serialized
            existing.updated_by = operator.id
            existing.updated_at = utcnow()
        changed_keys.append(key)

    if changed_keys:
        await write_admin_audit(
            db,
            operator,
            "ai_config.update",
            "ai_config",
            None,
            detail={"changed_keys": changed_keys},
        )

    await db.flush()
    _clear_config_cache()
    return await get_all_configs(db)


def _coerce_value(raw: str):
    """尝试将配置值转为适当类型。"""
    if raw in ("true", "false"):
        return raw == "true"
    try:
        return int(raw)
    except (ValueError, TypeError):
        pass
    try:
        return float(raw)
    except (ValueError, TypeError):
        pass
    return raw


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


async def test_model_connection(
    api_base_url: str,
    api_key: str | None,
    model_name: str,
    model_id: int | None = None,
    db: AsyncSession | None = None,
    provider: str | None = None,
    feature: str | None = None,
    features: list[str] | None = None,
) -> dict:
    """对给定模型配置发起一次最小连通性测试，返回诊断结果。

    凭据优先级：
    1. 请求明确提交了非空、非掩码的临时 API Key；
    2. 提供了 model_id：从数据库解密已保存 Key；
    3. 项目明确支持的环境变量 fallback；
    4. 都没有则返回安全的 auth_error。

    - OpenAI-compatible Chat 模型：按 SDK base_url 语义调用 /chat/completions
    - PaddleOCR-VL：提交极小图片测试其专用 OCR 接口
    """

    # 确定 provider / features：优先参数，其次 DB
    effective_provider = provider
    effective_features: list[str] = features if features else []
    if feature and feature not in effective_features:
        effective_features.append(feature)

    # Key priority 1: explicit temp key from request
    effective_api_key = (api_key or "").strip() or None

    # Key priority 2: from DB via model_id (only if no explicit key provided)
    if effective_api_key is None and model_id is not None and db is not None:
        model = await db.get(AdminAiModelConfig, model_id)
        if model is not None and model.deleted_at is not None:
            return {
                "success": False,
                "status": "model_not_found",
                "message": f"模型配置 #{model_id} 已删除，请重新选择模型",
                "latency_ms": 0,
            }
        if model is not None:
            # model_id is primarily used to reuse the encrypted saved secret.
            # Keep the request's Base URL / model name / provider so the Admin
            # form can test unsaved edits before persisting them.
            if not effective_provider:
                effective_provider = model.provider
            if not effective_features:
                effective_features = (
                    model.features
                    if model.features
                    else ([model.feature] if model.feature else [])
                )

            if model.api_key_encrypted:
                try:
                    effective_api_key = decrypt_secret(model.api_key_encrypted)
                except (SecretDecryptionError, SecretEncryptionError):
                    # DB key not decryptable — do NOT fall back to env
                    return {
                        "success": False,
                        "status": "auth_error",
                        "message": "数据库中保存的 API Key 无法解密，请检查加密配置或重新保存凭据",
                        "latency_ms": 0,
                    }
        else:
            await _seed_models_if_empty(db)
            await db.flush()
            model = await db.get(AdminAiModelConfig, model_id)
            if model is not None and model.deleted_at is not None:
                return {
                    "success": False,
                    "status": "model_not_found",
                    "message": f"模型配置 #{model_id} 已删除，请重新选择模型",
                    "latency_ms": 0,
                }
            if model is not None:
                if not effective_provider:
                    effective_provider = model.provider
                if not effective_features:
                    effective_features = (
                        model.features
                        if model.features
                        else ([model.feature] if model.feature else [])
                    )
                if model.api_key_encrypted:
                    try:
                        effective_api_key = decrypt_secret(model.api_key_encrypted)
                    except (SecretDecryptionError, SecretEncryptionError):
                        return {
                            "success": False,
                            "status": "auth_error",
                            "message": "数据库中保存的 API Key 无法解密",
                            "latency_ms": 0,
                        }

    try:
        api_base_url = _validated_api_base_url(api_base_url) or ""
    except ValueError as exc:
        return {
            "success": False,
            "status": "network_error",
            "message": str(exc),
            "latency_ms": 0,
        }

    # Key priority 3: no key available
    if not effective_api_key:
        return {
            "success": False,
            "status": "auth_error",
            "message": "未提供 API Key，请在上方输入后测试，或先保存模型配置",
            "latency_ms": 0,
        }

    # Embedding 模型测试：走 /embeddings，而不是 chat/completions。
    if "embedding" in effective_features:
        from app.services.vector_config_service import test_embedding_connection

        result = await test_embedding_connection(
            api_base_url=api_base_url,
            api_key=effective_api_key,
            model=model_name,
            dim=None,
            timeout=15,
        )
        return {
            "success": result.success,
            "status": result.status,
            "message": result.message,
            "latency_ms": result.latency_ms,
            "model_returned": model_name if result.success else None,
        }

    # PaddleOCR-VL 特殊处理：不调用 chat/completions
    _provider_norm = (effective_provider or "").strip().lower().replace("_", "-")
    _is_paddleocr = (
        "vision" in effective_features
        or _provider_norm == "paddle"
        or _provider_norm.startswith("paddleocr")
    )
    if _is_paddleocr:
        return await _test_paddleocr_vl_connection(api_base_url, effective_api_key)

    # 通用 Chat 模型测试
    return await _test_chat_connection(
        api_base_url, effective_api_key, model_name, provider=effective_provider
    )


async def _test_chat_connection(
    api_base_url: str,
    api_key: str,
    model_name: str,
    *,
    provider: str | None = None,
) -> dict:
    """Use the same adaptive OpenAI-compatible client as production traffic.

    The previous test path sent a fixed ``max_tokens + temperature`` payload, so
    a model could pass/fail differently from the real wrong-question request.
    Reusing ``llm.chat`` makes the admin "测试连接" exercise URL construction,
    token-field translation and optional reasoning/temperature negotiation too.
    """
    base = _validated_api_base_url(api_base_url) or ""
    start = time.time()
    try:
        result = await llm.chat(
            [{"role": "user", "content": "Reply with OK only."}],
            temperature=0.0,
            model=model_name,
            api_key=api_key,
            base_url=base,
            provider=provider or "openai_compatible",
            # A connection probe should not reject a healthy slow relay merely
            # because it cannot answer inside the old 15-second diagnostic cap.
            # Keep it below common front-proxy/browser request ceilings while
            # giving reasoning/relay models enough time to return a tiny reply.
            timeout=55.0,
            max_tokens=8,
            prefer_direct_answer=True,
            connection_probe=True,
        )
        elapsed = int(result.get("duration_ms") or ((time.time() - start) * 1000))
        returned_model = str(result.get("model") or model_name)
        message = f"连接成功，模型「{returned_model}」响应正常"
        if int(result.get("compatibility_retries") or 0) > 0:
            message += "；已自动适配该接口的 OpenAI-compatible 参数格式"
        return {
            "success": True,
            "status": "ok",
            "message": message,
            "latency_ms": elapsed,
            "model_returned": returned_model or None,
        }
    except TimeoutError:
        return {
            "success": False,
            "status": "timeout",
            "message": "连接模型超时，请检查第三方接口可用性或模型响应速度",
            "latency_ms": int((time.time() - start) * 1000),
        }
    except OpenAICompatibleAPIError as exc:
        elapsed = int((time.time() - start) * 1000)
        if exc.status_code in (401, 403):
            return {
                "success": False,
                "status": "auth_error",
                "message": f"API Key 无效或无权限访问 (HTTP {exc.status_code})",
                "latency_ms": elapsed,
            }
        if exc.status_code == 404 or exc.error_kind == "model_not_found":
            return {
                "success": False,
                "status": "model_not_found",
                "message": f"模型「{model_name}」不存在，请检查模型名称是否正确",
                "latency_ms": elapsed,
            }
        return {
            "success": False,
            "status": "unknown_error",
            "message": f"接口返回异常状态码 {exc.status_code}",
            "latency_ms": elapsed,
        }
    except UnsafeRemoteURLError as exc:
        return {
            "success": False,
            "status": "network_error",
            "message": f"请求失败: {str(exc)[:160]}",
            "latency_ms": int((time.time() - start) * 1000),
        }
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        return {
            "success": False,
            "status": "format_error",
            "message": f"接口返回格式不符合 OpenAI Chat Completions 规范: {str(exc)[:120]}",
            "latency_ms": int((time.time() - start) * 1000),
        }
    except RuntimeError as exc:
        message = str(exc)
        if "OpenAI-compatible API response" in message:
            status = "format_error"
            detail = "接口返回格式不符合 OpenAI Chat Completions 规范"
        else:
            status = "network_error"
            detail = f"请求失败: {message[:160]}"
        return {
            "success": False,
            "status": status,
            "message": detail,
            "latency_ms": int((time.time() - start) * 1000),
        }
    except Exception as exc:
        return {
            "success": False,
            "status": "network_error",
            "message": f"请求失败: {str(exc)[:160]}",
            "latency_ms": int((time.time() - start) * 1000),
        }


async def _test_paddleocr_vl_connection(
    api_base_url: str,
    api_key: str,
) -> dict:
    """测试 PaddleOCR-VL 连接，不跟随携带凭据的重定向。"""
    base = _validated_api_base_url(api_base_url) or ""
    url = urljoin(base + "/", "/api/v2/ocr/jobs")

    start = time.time()
    try:
        remote = await asyncio.to_thread(
            request_remote_bytes,
            url,
            method="GET",
            max_bytes=1024 * 1024,
            timeout=15.0,
            allow_http=settings.AI_ALLOW_HTTP_BASE_URLS,
            follow_redirects=False,
            headers={
                **get_trace_headers(),
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
        )
        elapsed = int((time.time() - start) * 1000)

        if remote.status in (401, 403):
            return {
                "success": False,
                "status": "auth_error",
                "message": f"API Key 无效或无权限访问 (HTTP {remote.status})",
                "latency_ms": elapsed,
            }

        if remote.status in {301, 302, 303, 307, 308}:
            return {
                "success": False,
                "status": "network_error",
                "message": "服务返回重定向；为防止凭据泄露，测试请求不会跟随重定向",
                "latency_ms": elapsed,
            }

        return {
            "success": True,
            "status": "ok",
            "message": (
                f"连接成功（HTTP {remote.status}），API Key 通过基本校验，"
                f"服务端响应时延 {elapsed}ms"
            ),
            "latency_ms": elapsed,
        }
    except Exception as exc:
        elapsed = int((time.time() - start) * 1000)
        return {
            "success": False,
            "status": "network_error",
            "message": f"请求失败: {str(exc)[:160]}",
            "latency_ms": elapsed,
        }

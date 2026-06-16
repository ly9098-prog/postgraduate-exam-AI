from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_security import AdminPrincipal
from app.core.config import settings
from app.models.admin_ai_config import AdminAiConfig, AdminAiModelConfig, decrypt_api_key, encrypt_api_key
from app.schemas.admin_ai_config import AdminAiModelConfigCreateRequest, AdminAiModelConfigResponse, AdminAiModelConfigPatchRequest
from app.services.admin_audit_service import write_admin_audit

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
    "ocr_fix_model": "deepseek",
    "ocr_fix_strategy": "auto",
    "qwen_api_key": "",
    "qwen_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen_model": "qwen-vl-max",
    "ocr_fix_feature_flag": "false",
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
        "- exam408-ds（408-数据结构）\n"
        "- exam408-os（408-操作系统）\n"
        "- exam408-co（408-计算机组成原理）\n"
        "- exam408-cn（408-计算机网络）\n"
        "- english（英语）\n\n"
        "有效题型（question_type）值：\n"
        "- single_choice（单选题）\n"
        "- multiple_choice（多选题）\n"
        "- true_false（判断题）\n"
        "- fill_blank（填空题）\n"
        "- multi_blank_choice（多空选择题）\n"
        "- subjective（主观题/简答题）\n\n"
        "推断规则：\n"
        "- 优先根据题干内容推断最具体的子学科，无法确定时使用大类\n"
        "- 数学题干出现极限/导数/积分/微分 → math2-calculus\n"
        "- 数学题干出现矩阵/向量/特征值/行列式/线性 → math2-linalg\n"
        "- 408 题干出现链表/树/图/排序/查找/算法 → exam408-ds\n"
        "- 408 题干出现进程/线程/死锁/内存/文件系统 → exam408-os\n"
        "- 408 题干出现 CPU/指令/流水线/Cache/总线 → exam408-co\n"
        "- 408 题干出现 TCP/IP/HTTP/DNS/路由/子网 → exam408-cn\n\n"
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
}

_DEFAULT_MODELS: list[dict] = [
    {"name": "deepseek-v4-flash", "display_name": "DeepSeek V4 Flash", "provider": "deepseek",
     "api_base_url": "https://api.deepseek.com", "is_enabled": True, "is_default": True, "sort_order": 1},
    {"name": "qwen-vl-max", "display_name": "Qwen-VL-Max", "provider": "openai",
     "api_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "is_enabled": False, "is_default": False, "sort_order": 2},
]


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


async def _seed_models_if_empty(db: AsyncSession):
    result = await db.execute(select(AdminAiModelConfig).limit(1))
    if result.scalar_one_or_none() is not None:
        return
    env_key = settings.DEEPSEEK_API_KEY
    for m in _DEFAULT_MODELS:
        model = AdminAiModelConfig(**m)
        if m["name"] == "deepseek-v4-flash" and env_key and env_key != "sk-your-key-here":
            model.api_key_encrypted = encrypt_api_key(env_key)
        db.add(model)
    await db.flush()


async def _ensure_env_key_synced(db: AsyncSession):
    """对于已存在的数据库，确保 deepseek-v4-flash 模型有 API key（从环境变量同步）。
    当 env key 被轮换时也自动更新 DB。
    """
    env_key = settings.DEEPSEEK_API_KEY
    if not env_key or env_key == "sk-your-key-here":
        return
    model = (
        await db.execute(
            select(AdminAiModelConfig).where(AdminAiModelConfig.name == "deepseek-v4-flash")
        )
    ).scalar_one_or_none()
    if model is None:
        return
    if model.api_key_encrypted:
        # 已加密的 key 能解密且与当前 env key 一致时不覆盖
        # 解密失败（key 轮换）或与新 key 不同时更新
        existing = decrypt_api_key(model.api_key_encrypted)
        if existing and existing == env_key:
            return
    model.api_key_encrypted = encrypt_api_key(env_key)
    await db.flush()


# ---------------------------------------------------------------------------
# Model config
# ---------------------------------------------------------------------------


def _model_to_response(m: AdminAiModelConfig) -> AdminAiModelConfigResponse:
    api_ok = False
    if m.api_key_encrypted:
        try:
            api_ok = bool(decrypt_api_key(m.api_key_encrypted))
        except Exception:
            api_ok = False
    return AdminAiModelConfigResponse(
        id=m.id,
        name=m.name,
        display_name=m.display_name,
        provider=m.provider,
        api_base_url=m.api_base_url,
        api_configured=api_ok,
        is_enabled=m.is_enabled,
        is_default=m.is_default,
        sort_order=m.sort_order,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


async def list_models(db: AsyncSession) -> list[AdminAiModelConfigResponse]:
    await _seed_models_if_empty(db)
    await _ensure_env_key_synced(db)
    result = await db.execute(select(AdminAiModelConfig).order_by(AdminAiModelConfig.sort_order))
    return [_model_to_response(m) for m in result.scalars().all()]


async def patch_model(
    db: AsyncSession,
    model_id: int,
    data: AdminAiModelConfigPatchRequest,
    operator: AdminPrincipal,
) -> AdminAiModelConfigResponse:
    model = await db.get(AdminAiModelConfig, model_id)
    if model is None:
        raise ValueError(f"模型 {model_id} 不存在")

    changes = {}

    if data.is_default is True:
        # 清除其它模型的 default 标志
        old_defaults = await db.execute(
            select(AdminAiModelConfig).where(
                AdminAiModelConfig.is_default == True,  # noqa: E712
                AdminAiModelConfig.id != model_id,
            )
        )
        for other in old_defaults.scalars().all():
            other.is_default = False
            other.updated_at = datetime.utcnow()

    if data.is_enabled is not None:
        model.is_enabled = data.is_enabled
        changes["is_enabled"] = data.is_enabled
    if data.is_default is not None:
        model.is_default = data.is_default
        changes["is_default"] = data.is_default
    if data.api_base_url is not None:
        model.api_base_url = data.api_base_url
        changes["api_base_url"] = data.api_base_url
    if data.api_key is not None and data.api_key.strip() and data.api_key != "****":
        model.api_key_encrypted = encrypt_api_key(data.api_key)
        changes["api_key_updated"] = True

    model.updated_at = datetime.utcnow()
    await db.flush()

    await write_admin_audit(
        db, operator, "ai_model_config.update", "ai_model_config",
        model.id, detail={"model_name": model.name, "changes": changes},
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

    model = AdminAiModelConfig(
        name=data.name,
        display_name=data.display_name,
        provider=data.provider,
        api_base_url=data.api_base_url,
        is_enabled=True,
        is_default=False,
        sort_order=next_order,
    )
    if data.api_key and data.api_key.strip():
        model.api_key_encrypted = encrypt_api_key(data.api_key)
    db.add(model)
    await db.flush()

    await write_admin_audit(
        db, operator, "ai_model_config.create", "ai_model_config",
        model.id, detail={"model_name": model.name, "provider": model.provider},
    )
    return _model_to_response(model)


async def delete_model(
    db: AsyncSession,
    model_id: int,
    operator: AdminPrincipal,
) -> None:
    """删除模型（保留最后一个启用模型）。"""
    model = await db.get(AdminAiModelConfig, model_id)
    if model is None:
        raise ValueError(f"模型 {model_id} 不存在")

    # 检查是否最后一个启用模型
    if model.is_enabled:
        result = await db.execute(
            select(AdminAiModelConfig).where(
                AdminAiModelConfig.is_enabled == True,  # noqa: E712
                AdminAiModelConfig.id != model_id,
            )
        )
        enabled_count = len(result.scalars().all())
        if enabled_count == 0:
            raise ValueError("不能删除最后一个启用的模型")

    await write_admin_audit(
        db, operator, "ai_model_config.delete", "ai_model_config",
        model.id, detail={"model_name": model.name},
    )
    await db.delete(model)
    await db.flush()


# ---------------------------------------------------------------------------
# Config key-value
# ---------------------------------------------------------------------------


async def get_all_configs(db: AsyncSession) -> dict:
    await _seed_configs_if_empty(db)
    result = await db.execute(select(AdminAiConfig))
    return {row.config_key: _coerce_value(row.config_value) for row in result.scalars().all()}


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
        if key in ("ocr_correction_prompt", "completion_prompt") and len(str(value)) > MAX_PROMPT_LENGTH:
            raise ValueError(f"{key} exceeds max length of {MAX_PROMPT_LENGTH}")
        serialized = str(value).lower() if isinstance(value, bool) else str(value)
        existing = await db.get(AdminAiConfig, key)
        if existing is None:
            db.add(AdminAiConfig(config_key=key, config_value=serialized, updated_by=operator.id))
        else:
            existing.config_value = serialized
            existing.updated_by = operator.id
            existing.updated_at = datetime.utcnow()
        changed_keys.append(key)

    if changed_keys:
        await write_admin_audit(
            db, operator, "ai_config.update", "ai_config",
            None, detail={"changed_keys": changed_keys},
        )

    await db.flush()
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

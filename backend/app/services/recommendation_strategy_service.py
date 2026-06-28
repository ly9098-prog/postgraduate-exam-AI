"""Phase 4 — 推荐策略配置服务。"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recommendation_strategy_config import RecommendationStrategyConfig

logger = logging.getLogger(__name__)

# 内置默认权重（无数据库配置时使用）
_DEFAULT_WEIGHTS = {
    "weight_vector_similarity": 0.5,
    "weight_knowledge_overlap": 0.2,
    "weight_difficulty_match": 0.1,
    "weight_mastery_gap": 0.1,
    "weight_path_priority": 0.1,
    "exploration_ratio": 0.1,
}

# Phase 4.5: 允许的策略类型
ALLOWED_STRATEGY_TYPES = {
    "weakness_vector", "knowledge_path", "similar_vector",
    "rule_based", "fallback_random", "fallback",
}

# 属于权重值的字段
WEIGHT_FIELDS = [
    "weight_vector_similarity", "weight_knowledge_overlap",
    "weight_difficulty_match", "weight_mastery_gap",
    "weight_path_priority", "exploration_ratio",
]


def validate_strategy_config(payload: dict) -> list[str]:
    """校验策略配置。返回错误列表，空列表 = 合法。"""
    errors: list[str] = []

    strategy_type = payload.get("strategy_type")
    if strategy_type is not None and strategy_type not in ALLOWED_STRATEGY_TYPES:
        errors.append(
            f"strategy_type '{strategy_type}' 不在允许列表中: "
            f"{', '.join(sorted(ALLOWED_STRATEGY_TYPES))}"
        )

    for field in WEIGHT_FIELDS:
        value = payload.get(field)
        if value is None:
            continue
        if not isinstance(value, (int, float)):
            errors.append(f"{field} 必须是数字")
            continue
        if value < 0:
            errors.append(f"{field} 不能为负数")
        if value > 1:
            logger.warning("%s = %s 超过 1，建议归一化", field, value)

    return errors


def _config_to_dict(config: RecommendationStrategyConfig) -> dict:
    return {
        "id": config.id,
        "name": config.name,
        "display_name": config.display_name,
        "description": config.description,
        "scene": config.scene,
        "is_active": config.is_active,
        "is_default": config.is_default,
        "weight_vector_similarity": config.weight_vector_similarity,
        "weight_knowledge_overlap": config.weight_knowledge_overlap,
        "weight_difficulty_match": config.weight_difficulty_match,
        "weight_mastery_gap": config.weight_mastery_gap,
        "weight_path_priority": config.weight_path_priority,
        "exploration_ratio": config.exploration_ratio,
        "config_json": config.config_json,
    }


async def get_strategy_config(
    db: AsyncSession,
    scene: str,
    strategy_name: str | None = None,
) -> dict:
    """获取策略配置。

    优先按 name 查找，其次找 scene 下 is_default=True。
    没有数据库配置时返回内置默认权重。
    """
    if strategy_name:
        result = await db.execute(
            select(RecommendationStrategyConfig).where(
                RecommendationStrategyConfig.name == strategy_name,
                RecommendationStrategyConfig.is_active == True,  # noqa: E712
            )
        )
        config = result.scalar_one_or_none()
        if config:
            return _config_to_dict(config)

    # 找 scene 下 is_default=True
    result = await db.execute(
        select(RecommendationStrategyConfig).where(
            RecommendationStrategyConfig.scene == scene,
            RecommendationStrategyConfig.is_active == True,  # noqa: E712
            RecommendationStrategyConfig.is_default == True,  # noqa: E712
        )
    )
    config = result.scalar_one_or_none()
    if config:
        return _config_to_dict(config)

    # 返回内置默认
    return {
        "id": None,
        "name": "default",
        "display_name": "内置默认",
        "description": None,
        "scene": scene,
        "is_active": True,
        "is_default": True,
        **_DEFAULT_WEIGHTS,
        "config_json": None,
    }


async def create_or_update_strategy_config(
    db: AsyncSession,
    payload: dict,
) -> dict:
    """创建或更新策略配置（按 name 匹配）。"""
    errors = validate_strategy_config(payload)
    if errors:
        raise ValueError("; ".join(errors))

    name = payload.get("name")
    result = await db.execute(
        select(RecommendationStrategyConfig).where(
            RecommendationStrategyConfig.name == name,
        )
    )
    config = result.scalar_one_or_none()

    if config:
        # 更新
        for key, value in payload.items():
            if value is not None and hasattr(config, key):
                setattr(config, key, value)
    else:
        config = RecommendationStrategyConfig(**payload)
        db.add(config)

    await db.flush()
    await db.refresh(config)
    return _config_to_dict(config)


async def list_strategy_configs(
    db: AsyncSession,
    scene: str | None = None,
) -> list[dict]:
    """列出策略配置。"""
    q = select(RecommendationStrategyConfig)
    if scene:
        q = q.where(RecommendationStrategyConfig.scene == scene)
    q = q.order_by(RecommendationStrategyConfig.scene, RecommendationStrategyConfig.name)

    result = await db.execute(q)
    configs = result.scalars().all()
    return [_config_to_dict(c) for c in configs]


def apply_strategy_weights(base_scores: dict, config: dict) -> float:
    """根据配置权重计算加权分数。

    base_scores 示例:
    {
        "vector_similarity": 0.8,
        "knowledge_overlap": 1.0,
        "difficulty_match": 0.5,
        "mastery_gap": 0.7,
        "path_priority": 0.9,
    }

    返回: 加权分数，clamp 到 0~1。
    """
    weight_map = {
        "vector_similarity": config.get("weight_vector_similarity", _DEFAULT_WEIGHTS["weight_vector_similarity"]),
        "knowledge_overlap": config.get("weight_knowledge_overlap", _DEFAULT_WEIGHTS["weight_knowledge_overlap"]),
        "difficulty_match": config.get("weight_difficulty_match", _DEFAULT_WEIGHTS["weight_difficulty_match"]),
        "mastery_gap": config.get("weight_mastery_gap", _DEFAULT_WEIGHTS["weight_mastery_gap"]),
        "path_priority": config.get("weight_path_priority", _DEFAULT_WEIGHTS["weight_path_priority"]),
    }

    total_weight = sum(weight_map.values()) or 1.0
    weighted_sum = 0.0

    for key, weight in weight_map.items():
        score = base_scores.get(key, 0.0) or 0.0
        weighted_sum += score * weight

    # 归一化 + clamp
    result = weighted_sum / total_weight
    return max(0.0, min(1.0, result))

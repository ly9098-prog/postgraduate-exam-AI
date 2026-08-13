"""Phase 4 — 推荐策略配置服务。"""
import logging

from sqlalchemy import select, update
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
    "weakness_vector", "knowledge_path", "scored", "hybrid_graph", "similar_vector",
    "rule_based", "fallback_random", "fallback",
}


# scored / 图谱综合推荐的系统级运行权重。
# UserRecommendPreference 仍负责用户级 0.7~1.3 微调；这里提供管理员可控的
# 全局乘数，最终两者相乘后进入 calculate_smart_score。
DEFAULT_SCORED_RUNTIME_WEIGHTS = {
    "due_weight": 1.0,
    "weakness_weight": 1.0,
    "wrong_weight": 1.0,
    "new_question_weight": 1.0,
    "diversity_weight": 1.0,
    "path_weight": 1.0,
}

DEFAULT_SCORED_GRAPH_CONFIG = {
    "weak_target_limit": 5,
    "max_depth": 2,
    "max_nodes": 24,
    "prerequisite_mastery_threshold": 60.0,
    "prerequisite_confidence_threshold": 0.3,
}

SCORED_WEIGHT_FIELDS = tuple(DEFAULT_SCORED_RUNTIME_WEIGHTS)

# 属于权重值的字段
WEIGHT_FIELDS = [
    "weight_vector_similarity", "weight_knowledge_overlap",
    "weight_difficulty_match", "weight_mastery_gap",
    "weight_path_priority", "exploration_ratio",
]


def validate_strategy_config(payload: dict) -> list[str]:
    """校验策略配置。返回错误列表，空列表 = 合法。"""
    errors: list[str] = []

    if payload.get("is_default") is True and payload.get("is_active") is False:
        errors.append("默认策略必须处于启用状态")

    config_json = payload.get("config_json")
    nested_strategy_type = config_json.get("strategy_type") if isinstance(config_json, dict) else None
    strategy_type = payload.get("strategy_type") or nested_strategy_type
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

    if isinstance(config_json, dict):
        scored_weights = config_json.get("scored_weights")
        if scored_weights is not None and not isinstance(scored_weights, dict):
            errors.append("config_json.scored_weights 必须是对象")
        elif isinstance(scored_weights, dict):
            for field in SCORED_WEIGHT_FIELDS:
                value = scored_weights.get(field)
                if value is None:
                    continue
                if not isinstance(value, (int, float)):
                    errors.append(f"config_json.scored_weights.{field} 必须是数字")
                elif not 0.0 <= float(value) <= 2.0:
                    errors.append(f"config_json.scored_weights.{field} 必须在 0~2 之间")

        graph = config_json.get("graph")
        if graph is not None and not isinstance(graph, dict):
            errors.append("config_json.graph 必须是对象")
        elif isinstance(graph, dict):
            numeric_ranges = {
                "weak_target_limit": (1, 20),
                "max_depth": (1, 2),
                "max_nodes": (1, 100),
                "prerequisite_mastery_threshold": (0.0, 100.0),
                "prerequisite_confidence_threshold": (0.0, 1.0),
            }
            for field, (low, high) in numeric_ranges.items():
                value = graph.get(field)
                if value is None:
                    continue
                if not isinstance(value, (int, float)):
                    errors.append(f"config_json.graph.{field} 必须是数字")
                elif not low <= float(value) <= high:
                    errors.append(f"config_json.graph.{field} 必须在 {low}~{high} 之间")

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
        select(RecommendationStrategyConfig)
        .where(
            RecommendationStrategyConfig.scene == scene,
            RecommendationStrategyConfig.is_active == True,  # noqa: E712
            RecommendationStrategyConfig.is_default == True,  # noqa: E712
        )
        # 兼容历史上可能已经存在的多默认脏数据，避免 scalar_one_or_none
        # 直接抛 MultipleResultsFound。新的写入路径会主动清理同 scene 其他默认。
        .order_by(RecommendationStrategyConfig.updated_at.desc(), RecommendationStrategyConfig.id.desc())
        .limit(1)
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

    # 每个 scene 最多保留一个默认策略。数据库当前没有 partial unique
    # constraint，因此在服务层维护该不变量，并兼容 SQLite/PostgreSQL。
    if bool(getattr(config, "is_default", False)):
        await db.execute(
            update(RecommendationStrategyConfig)
            .where(
                RecommendationStrategyConfig.scene == config.scene,
                RecommendationStrategyConfig.name != config.name,
                RecommendationStrategyConfig.is_default == True,  # noqa: E712
            )
            .values(is_default=False)
        )

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


def _clamp_number(value, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(number, high))


async def get_scored_runtime_config(
    db: AsyncSession,
    strategy_name: str = "default_scored",
) -> dict:
    """读取 scored 的系统级运行配置。

    该配置保存在 RecommendationStrategyConfig.config_json 中，避免为推荐权重
    单独增加数据库列。管理员权重是全局乘数，随后还会与用户级
    UserRecommendPreference 相乘。找不到配置时返回安全的内置默认值。
    """
    result = await db.execute(
        select(RecommendationStrategyConfig).where(
            RecommendationStrategyConfig.name == strategy_name,
            RecommendationStrategyConfig.is_active == True,  # noqa: E712
        )
    )
    config = result.scalar_one_or_none()
    raw = config.config_json if config and isinstance(config.config_json, dict) else {}

    raw_weights = raw.get("scored_weights") if isinstance(raw.get("scored_weights"), dict) else {}
    weights = {
        field: _clamp_number(raw_weights.get(field), default, 0.0, 2.0)
        for field, default in DEFAULT_SCORED_RUNTIME_WEIGHTS.items()
    }

    raw_graph = raw.get("graph") if isinstance(raw.get("graph"), dict) else {}
    graph = {
        "weak_target_limit": int(_clamp_number(
            raw_graph.get("weak_target_limit"), DEFAULT_SCORED_GRAPH_CONFIG["weak_target_limit"], 1, 20
        )),
        "max_depth": int(_clamp_number(
            raw_graph.get("max_depth"), DEFAULT_SCORED_GRAPH_CONFIG["max_depth"], 1, 2
        )),
        "max_nodes": int(_clamp_number(
            raw_graph.get("max_nodes"), DEFAULT_SCORED_GRAPH_CONFIG["max_nodes"], 1, 100
        )),
        "prerequisite_mastery_threshold": _clamp_number(
            raw_graph.get("prerequisite_mastery_threshold"),
            DEFAULT_SCORED_GRAPH_CONFIG["prerequisite_mastery_threshold"],
            0.0,
            100.0,
        ),
        "prerequisite_confidence_threshold": _clamp_number(
            raw_graph.get("prerequisite_confidence_threshold"),
            DEFAULT_SCORED_GRAPH_CONFIG["prerequisite_confidence_threshold"],
            0.0,
            1.0,
        ),
    }

    return {
        "strategy_config_id": config.id if config else None,
        "strategy_name": config.name if config else strategy_name,
        "weights": weights,
        "graph": graph,
    }


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

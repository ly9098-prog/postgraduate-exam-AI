"""Phase 4.5 — 默认推荐策略种子服务。"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recommendation_strategy_config import RecommendationStrategyConfig

logger = logging.getLogger(__name__)

# 5 个默认策略定义
_SEED_STRATEGIES = [
    {
        "name": "default_random",
        "display_name": "默认随机",
        "scene": "practice_smart",
        "is_active": True,
        "is_default": False,
        "weight_vector_similarity": 0.0,
        "weight_knowledge_overlap": 0.0,
        "weight_difficulty_match": 0.0,
        "weight_mastery_gap": 0.0,
        "weight_path_priority": 0.0,
        "exploration_ratio": 1.0,
        "config_json": {"strategy_type": "fallback_random"},
    },
    {
        "name": "default_weakness_vector",
        "display_name": "默认薄弱点向量",
        "scene": "practice_smart",
        "is_active": True,
        "is_default": True,
        "weight_vector_similarity": 0.25,
        "weight_knowledge_overlap": 0.0,
        "weight_difficulty_match": 0.15,
        "weight_mastery_gap": 0.35,
        "weight_path_priority": 0.15,
        "exploration_ratio": 0.1,
        "config_json": {
            "strategy_type": "weakness_vector",
            "freshness_weight": 0.10,
        },
    },
    {
        "name": "default_knowledge_path",
        "display_name": "默认知识路径",
        "scene": "knowledge_path",
        "is_active": True,
        "is_default": True,
        "weight_vector_similarity": 0.20,
        "weight_knowledge_overlap": 0.0,
        "weight_difficulty_match": 0.15,
        "weight_mastery_gap": 0.25,
        "weight_path_priority": 0.40,
        "exploration_ratio": 0.1,
        "config_json": {"strategy_type": "knowledge_path"},
    },
    {
        "name": "default_similar_vector",
        "display_name": "默认相似题向量",
        "scene": "similar",
        "is_active": True,
        "is_default": True,
        "weight_vector_similarity": 0.70,
        "weight_knowledge_overlap": 0.15,
        "weight_difficulty_match": 0.10,
        "weight_mastery_gap": 0.0,
        "weight_path_priority": 0.0,
        "exploration_ratio": 0.05,
        "config_json": {
            "strategy_type": "similar_vector",
            "question_type_weight": 0.05,
        },
    },
    {
        "name": "default_fallback",
        "display_name": "默认兜底",
        "scene": "practice_smart",
        "is_active": True,
        "is_default": False,
        "weight_vector_similarity": 0.0,
        "weight_knowledge_overlap": 0.0,
        "weight_difficulty_match": 0.0,
        "weight_mastery_gap": 0.0,
        "weight_path_priority": 0.0,
        "exploration_ratio": 0.0,
        "config_json": {"strategy_type": "fallback"},
    },
]


async def seed_default_recommendation_strategies(
    db: AsyncSession,
    force: bool = False,
) -> dict:
    """种子默认策略配置。

    - 幂等：已存在时只补缺失字段，不覆盖管理员手动修改（除非 force=True）。
    - 返回 {"created": int, "updated": int, "skipped": int}。
    """
    created = 0
    updated = 0
    skipped = 0

    for seed in _SEED_STRATEGIES:
        result = await db.execute(
            select(RecommendationStrategyConfig).where(
                RecommendationStrategyConfig.name == seed["name"],
            )
        )
        existing = result.scalar_one_or_none()

        if existing is None:
            # 创建新配置
            config = RecommendationStrategyConfig(**seed)
            db.add(config)
            created += 1
        elif force:
            # 强制覆盖
            for key, value in seed.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            updated += 1
        else:
            # 只补缺失字段
            changed = False
            for key, value in seed.items():
                if key == "name":
                    continue
                current = getattr(existing, key, None)
                # 只填充空值（None、空字符串、0.0 且默认值有意义的情况）
                if current is None or (isinstance(current, str) and current == ""):
                    setattr(existing, key, value)
                    changed = True
            if changed:
                updated += 1
            else:
                skipped += 1

    await db.flush()
    return {"created": created, "updated": updated, "skipped": skipped}

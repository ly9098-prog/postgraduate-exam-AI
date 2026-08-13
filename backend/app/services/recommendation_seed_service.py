"""Phase 4.5 — 默认推荐策略种子服务。"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recommendation_strategy_config import RecommendationStrategyConfig

logger = logging.getLogger(__name__)

# 默认策略定义（practice_smart 的生产主策略为 scored）
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
        "is_default": False,
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
        "name": "default_scored",
        "display_name": "智能图谱综合推荐",
        "description": "智能刷题生产主策略：复习、薄弱、错题、多样性与知识图谱前置关系综合打分。",
        "scene": "practice_smart",
        "is_active": True,
        "is_default": True,
        # legacy 权重字段主要服务 weakness/vector rerank；scored 的真实运行权重
        # 保存在 config_json.scored_weights，由后台策略页直接维护。
        "weight_vector_similarity": 0.0,
        "weight_knowledge_overlap": 0.0,
        "weight_difficulty_match": 0.0,
        "weight_mastery_gap": 0.0,
        "weight_path_priority": 0.0,
        "exploration_ratio": 0.0,
        "config_json": {
            "strategy_type": "scored",
            "scored_weights": {
                "due_weight": 1.0,
                "weakness_weight": 1.0,
                "wrong_weight": 1.0,
                "new_question_weight": 1.0,
                "diversity_weight": 1.0,
                "path_weight": 1.0,
            },
            "graph": {
                "weak_target_limit": 5,
                "max_depth": 2,
                "max_nodes": 24,
                "prerequisite_mastery_threshold": 60.0,
                "prerequisite_confidence_threshold": 0.3,
            },
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


def _merge_missing_dict(current: dict | None, defaults: dict) -> tuple[dict, bool]:
    """递归补齐缺失配置，不覆盖管理员已有值。"""
    merged = dict(current or {})
    changed = False
    for key, value in defaults.items():
        if key not in merged or merged[key] is None:
            merged[key] = value
            changed = True
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            child, child_changed = _merge_missing_dict(merged[key], value)
            if child_changed:
                merged[key] = child
                changed = True
    return merged, changed


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
    scored_created = False

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
            if seed["name"] == "default_scored":
                scored_created = True
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
                if key == "config_json" and isinstance(value, dict):
                    merged, json_changed = _merge_missing_dict(
                        current if isinstance(current, dict) else None,
                        value,
                    )
                    if json_changed or current is None:
                        existing.config_json = merged
                        changed = True
                    continue
                # 只填充空值，不覆盖管理员手动修改。
                if current is None or (isinstance(current, str) and current == ""):
                    setattr(existing, key, value)
                    changed = True
            if changed:
                updated += 1
            else:
                skipped += 1

    await db.flush()

    # 从旧版本升级时，default_weakness_vector 可能仍标记为 practice_smart
    # 默认策略。仅在 *首次创建* default_scored 时做一次安全迁移：如果没有
    # 管理员自定义默认策略，则把默认标记迁移到 scored。之后启动不会反复
    # 覆盖管理员选择。
    if scored_created:
        result = await db.execute(
            select(RecommendationStrategyConfig).where(
                RecommendationStrategyConfig.scene == "practice_smart",
                RecommendationStrategyConfig.is_default == True,  # noqa: E712
            )
        )
        defaults = list(result.scalars().all())
        custom_defaults = [
            item for item in defaults
            if item.name not in {"default_scored", "default_weakness_vector"}
        ]
        scored = next((item for item in defaults if item.name == "default_scored"), None)
        weakness = next((item for item in defaults if item.name == "default_weakness_vector"), None)
        if custom_defaults:
            # 尊重管理员已有自定义默认策略；同时清掉旧内置 weakness 默认标记，
            # 避免同一 scene 出现多个 is_default=True 导致查询歧义。
            if scored is not None:
                scored.is_default = False
            if weakness is not None:
                weakness.is_default = False
        else:
            if scored is not None:
                scored.is_default = True
            if weakness is not None:
                weakness.is_default = False
        await db.flush()

    return {"created": created, "updated": updated, "skipped": skipped}

"""Best-effort strategy-weight reranking for weakness-vector candidates.

The caller keeps ownership of configuration loading and failure semantics; this
module only computes the reranked projection when a valid weakness-vector
configuration is supplied.
"""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_point import KnowledgePoint
from app.models.user_knowledge_state import UserKnowledgeState
from app.services.knowledge_point_service import load_question_kps

if TYPE_CHECKING:
    from app.models.question import Question

logger = logging.getLogger(__name__)


async def apply_strategy_weight_rerank(
    db: AsyncSession,
    user_id: int,
    questions: list[Question],
    metadata: dict[int, dict],
    config: dict | None,
    weak_kp_names: list[str],
) -> tuple[list[Question], dict[int, dict]]:
    """按推荐策略配置权重对召回候选重排（best-effort）。

    仅当存在有效的 DB 策略配置且 config_json.strategy_type 为 weakness_vector 时生效；
    无配置 / 未激活 / 异常时原样返回，保持现有行为不变。
    """
    try:
        if not config or len(questions) < 2:
            return questions, metadata
        if not config.get("is_active") or config.get("id") is None:
            return questions, metadata
        strategy_type = (config.get("config_json") or {}).get("strategy_type")
        if strategy_type not in (None, "weakness_vector"):
            return questions, metadata

        # 批量加载知识点 id 与用户掌握度（固定 2 次查询，避免 N+1）
        kp_map = await load_question_kps(db, [q.id for q in questions])

        candidate_names: set[str] = set()
        for q in questions:
            candidate_names.update(kp_map.get(q.id, []))

        kp_name_to_id: dict[str, int] = {}
        if candidate_names:
            kp_result = await db.execute(
                select(KnowledgePoint.id, KnowledgePoint.name).where(
                    KnowledgePoint.name.in_(candidate_names)
                )
            )
            for kp_id, name in kp_result.all():
                kp_name_to_id[name] = kp_id

        mastery_by_kp: dict[int, float] = {}
        kp_ids = set(kp_name_to_id.values())
        if kp_ids:
            state_result = await db.execute(
                select(
                    UserKnowledgeState.knowledge_point_id,
                    UserKnowledgeState.mastery_score,
                ).where(
                    UserKnowledgeState.user_id == user_id,
                    UserKnowledgeState.knowledge_point_id.in_(kp_ids),
                )
            )
            for kp_id, mastery in state_result.all():
                if mastery is not None:
                    mastery_by_kp[kp_id] = mastery

        known_mastery = list(mastery_by_kp.values())
        user_mean_mastery = (
            sum(known_mastery) / len(known_mastery) if known_mastery else None
        )
        target_difficulty = (
            3 + round(user_mean_mastery / 25) if user_mean_mastery is not None else None
        )
        exploration = float(config.get("exploration_ratio") or 0.0)

        from app.services.recommendation_strategy_service import apply_strategy_weights

        scored: list[tuple[Question, float, float]] = []
        weak_set = set(weak_kp_names)
        for q in questions:
            q_kps = kp_map.get(q.id, [])
            q_kp_set = set(q_kps)
            overlap = len(q_kp_set & weak_set) / max(1, len(q_kps))

            gaps = []
            for name in q_kps:
                kp_id = kp_name_to_id.get(name)
                mastery = mastery_by_kp.get(kp_id) if kp_id is not None else None
                gaps.append((100.0 - mastery) / 100.0 if mastery is not None else 0.5)
            mastery_gap = sum(gaps) / len(gaps) if gaps else 0.5

            if target_difficulty is None:
                difficulty_match = 1.0
            else:
                difficulty_match = 1.0 - min(
                    1.0, abs((q.difficulty or 3) - target_difficulty) / 4.0
                )

            base_scores = {
                "vector_similarity": (metadata.get(q.id) or {}).get("similarity")
                or 0.0,
                "knowledge_overlap": overlap,
                "difficulty_match": difficulty_match,
                "mastery_gap": mastery_gap,
                "path_priority": 0.0,
            }
            weighted = apply_strategy_weights(base_scores, config)
            final = (1.0 - exploration) * weighted + exploration * random.random()
            scored.append((q, final, weighted))

        scored.sort(key=lambda t: t[1], reverse=True)
        for q, _final, weighted in scored:
            meta = metadata.setdefault(q.id, {})
            meta["recommend_score"] = round(weighted, 4)
            meta["strategy_config_id"] = config.get("id")
        return [t[0] for t in scored], metadata
    except Exception:
        logger.warning("策略权重重排失败，保持原顺序", exc_info=True)
        return questions, metadata

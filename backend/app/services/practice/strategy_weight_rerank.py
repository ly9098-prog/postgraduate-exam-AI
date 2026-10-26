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
from app.services.practice.strategy_weight_scores import build_strategy_base_scores

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

        kp_map = await load_question_kps(db, [q.id for q in questions])
        kp_name_to_id = await _load_knowledge_ids(db, questions, kp_map)
        mastery_by_kp = await _load_mastery(db, user_id, kp_name_to_id)
        scored = _rank_candidates(
            questions,
            metadata,
            config,
            weak_kp_names,
            kp_map,
            kp_name_to_id,
            mastery_by_kp,
        )
        for q, _final, weighted in scored:
            meta = metadata.setdefault(q.id, {})
            meta["recommend_score"] = round(weighted, 4)
            meta["strategy_config_id"] = config.get("id")
        return [t[0] for t in scored], metadata
    except Exception:
        logger.warning("策略权重重排失败，保持原顺序", exc_info=True)
        return questions, metadata


async def _load_knowledge_ids(
    db: AsyncSession,
    questions: list[Question],
    kp_map: dict[int, list[str]],
) -> dict[str, int]:
    candidate_names: set[str] = set()
    for q in questions:
        candidate_names.update(kp_map.get(q.id, []))
    name_to_id: dict[str, int] = {}
    if candidate_names:
        result = await db.execute(
            select(KnowledgePoint.id, KnowledgePoint.name).where(
                KnowledgePoint.name.in_(candidate_names),
            )
        )
        for kp_id, name in result.all():
            name_to_id[name] = kp_id
    return name_to_id


async def _load_mastery(
    db: AsyncSession,
    user_id: int,
    name_to_id: dict[str, int],
) -> dict[int, float]:
    mastery_by_kp: dict[int, float] = {}
    kp_ids = set(name_to_id.values())
    if kp_ids:
        result = await db.execute(
            select(
                UserKnowledgeState.knowledge_point_id,
                UserKnowledgeState.mastery_score,
            ).where(
                UserKnowledgeState.user_id == user_id,
                UserKnowledgeState.knowledge_point_id.in_(kp_ids),
            )
        )
        for kp_id, mastery in result.all():
            if mastery is not None:
                mastery_by_kp[kp_id] = mastery
    return mastery_by_kp


def _rank_candidates(
    questions: list[Question],
    metadata: dict[int, dict],
    config: dict[str, Any],
    weak_kp_names: list[str],
    kp_map: dict[int, list[str]],
    kp_name_to_id: dict[str, int],
    mastery_by_kp: dict[int, float],
) -> list[tuple[Question, float, float]]:
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
        base_scores = build_strategy_base_scores(
            q,
            kp_map.get(q.id, []),
            metadata,
            weak_set,
            kp_name_to_id,
            mastery_by_kp,
            target_difficulty,
        )
        weighted = apply_strategy_weights(base_scores, config)
        final = (1.0 - exploration) * weighted + exploration * random.random()
        scored.append((q, final, weighted))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored

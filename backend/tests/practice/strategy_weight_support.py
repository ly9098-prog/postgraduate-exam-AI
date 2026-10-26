"""Scripted score and SQL ports for reranking compatibility tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services import recommendation_strategy_service as weights
from app.services.practice import strategy_weight_rerank as rerank


def question(question_id, difficulty=None):
    return SimpleNamespace(id=question_id, difficulty=difficulty)


def rows(values):
    result = MagicMock()
    result.all.return_value = values
    return result


def build_rerank_ports(monkeypatch):
    events = []
    questions = [question(1), question(2, 7)]
    metadata = {1: {"similarity": 0.8}, 2: {"similarity": 0.2}}
    kp_map = {1: ["a", "a", "b"], 2: ["missing"]}
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                rows([(10, "a"), (11, "b")]),
                rows([(10, 0.0), (11, 100.0)]),
            ]
        )
    )

    async def load(received_db, ids):
        assert received_db is db
        events.append(("load", ids))
        return kp_map

    def weighted(scores, received_config):
        events.append(("weight", scores.copy(), received_config))
        return scores["vector_similarity"]

    def random():
        events.append(("random",))
        return 0.5

    monkeypatch.setattr(rerank, "load_question_kps", load)
    monkeypatch.setattr(weights, "apply_strategy_weights", weighted)
    monkeypatch.setattr(rerank.random, "random", random)
    return SimpleNamespace(
        db=db,
        questions=questions,
        metadata=metadata,
        events=events,
        kp_map=kp_map,
    )

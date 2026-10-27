"""Use real terminal callbacks, including their required visual-input contract."""

import inspect
import logging

import pytest

from app.services.ai.analysis_outcomes import (
    grounding_repair_outcome,
    valid_analysis_outcome,
    visual_ack_failure_outcome,
)
from app.services.ai.analysis_result_review import (
    ReviewedAnalysis,
    resolve_analysis_outcome,
)
from app.services.ai.analysis_validation import AnalysisUsage, GroundingValidation
from tests.test_services.analysis_persistence_support import harness


def arguments(h, kind, images):
    values = h.args
    review = ReviewedAnalysis(
        parsed=h.parsed, parsed_valid=True,
        usage=AnalysisUsage("evidence", True, 12, 31, 51),
        grounding=GroundingValidation(kind == "valid", "mismatch", ["A"], values["answer_grounding"]),
        ack_failure=None,
    )
    kwargs = {key: values[key] for key in (
        "wrong_question", "user_id", "context", "result", "input_signature",
        "model_signature", "expected_answer_check", "effective_force", "runtime",
    )}
    kwargs.update(
        image_data_urls=images, visual_evidence_is_valid=lambda _value: True,
        max_tokens=800, logger=logging.getLogger("test-real-analysis-outcome"),
        grounding_repair=grounding_repair_outcome, valid_outcome=valid_analysis_outcome,
        visual_ack_failure=visual_ack_failure_outcome,
    )
    return review, kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["repair", "valid"])
@pytest.mark.parametrize("image_count", [0, 1, 2])
async def test_real_outcome_callback_reaches_two_commit_persistence(
    monkeypatch, kind, image_count
):
    h = harness(monkeypatch)
    h.wrong.id = 7
    images = ["synthetic-image"] * image_count
    review, kwargs = arguments(h, kind, images)
    response = await resolve_analysis_outcome(h.db, review, **kwargs)
    assert h.db.commits == 2
    assert len(h.db.chats) == 1
    assert response["visual_input_count"] == image_count
    assert response["content"] is (h.safe if kind == "repair" else h.parsed)
    assert response["input_mode"] == ("vision" if image_count else "text")
    assert h.wrong.ai_analysis["_meta"]["visual_input_count"] == image_count
    assert h.db.chats[0].context_snapshot["visual_input_count"] == image_count
    assert h.db.chats[0].tokens_used == 31


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["repair", "valid"])
async def test_dispatch_kwargs_bind_to_the_real_callback_signature(monkeypatch, kind):
    h = harness(monkeypatch)
    h.wrong.id = 7
    images = ["synthetic-image"]
    review, kwargs = arguments(h, kind, images)
    original = kwargs["grounding_repair" if kind == "repair" else "valid_outcome"]
    captured = []

    async def strict(*args, **fields):
        bound = inspect.signature(original).bind(*args, **fields)
        assert bound.arguments["image_data_urls"] is images
        captured.append(bound)
        return {"bound": True}

    kwargs["grounding_repair" if kind == "repair" else "valid_outcome"] = strict
    assert await resolve_analysis_outcome(h.db, review, **kwargs) == {"bound": True}
    assert len(captured) == 1

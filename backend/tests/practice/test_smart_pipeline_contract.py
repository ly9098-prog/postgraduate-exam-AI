"""Exercise smart-practice branch orchestration through the real entry point."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services import practice_service as svc


def question(qid: int, subject_id: int = 2):
    return SimpleNamespace(id=qid, subject_id=subject_id)


@pytest.fixture
def smart_ports(monkeypatch):
    import app.services.mastery_service as mastery_service
    import app.services.recommendation_experiment_service as experiment_service
    import app.services.recommendation_log_service as log_service

    scored = AsyncMock()
    fallback = AsyncMock()
    real_finalize = svc._maybe_finalize_smart
    finalize = AsyncMock(side_effect=real_finalize)
    log = AsyncMock(return_value=[])
    experiment = AsyncMock(return_value={"source": "default"})
    real_merge = svc.merge_recommendation_results
    merge = Mock(side_effect=real_merge)

    monkeypatch.setattr(svc, "get_smart_scored_questions", scored)
    monkeypatch.setattr(svc, "_smart_weakness_vector", fallback)
    monkeypatch.setattr(svc, "_maybe_finalize_smart", finalize)
    monkeypatch.setattr(svc, "merge_recommendation_results", merge)
    monkeypatch.setattr(
        experiment_service, "resolve_strategy_for_user", experiment
    )
    monkeypatch.setattr(
        log_service, "create_recommendation_logs_isolated", log
    )
    monkeypatch.setattr(
        mastery_service,
        "get_user_weak_knowledge_points",
        AsyncMock(return_value=[]),
    )
    return SimpleNamespace(
        scored=scored, fallback=fallback, finalize=finalize,
        log=log, experiment=experiment, merge=merge,
    )


@pytest.mark.asyncio
async def test_path_logs_only_questions_returned_after_final_guard(
    smart_ports, monkeypatch, caplog,
):
    import app.services.knowledge_path_service as path_service

    smart_ports.experiment.return_value = {"source": "default"}
    issued = [question(459), question(460)]
    path_result = {
        "strategy": "knowledge_path",
        "nodes": [
            {
                "recommended_question_ids": [459, 460, 461],
                "priority": 0.8,
                "reason": "path",
            }
        ],
        "recommended_question_ids": [459, 460, 461],
    }
    path = AsyncMock(return_value=path_result)
    # The mock DB supplies only guard-surviving rows; qid 461 was a candidate.
    db = Mock()
    db.execute = AsyncMock(
        return_value=Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=issued))))
    )
    monkeypatch.setattr(path_service, "get_user_path_recommendations", path)

    with caplog.at_level(logging.INFO):
        result, metadata = await svc.get_smart_practice_questions(
            db, 9, "ds", count=2, smart_strategy="path", subject_ids=[2],
            request_id="req-path",
        )

    assert [row.id for row in result] == [459, 460]
    path.assert_awaited_once_with(
        db=db,
        user_id=9,
        subject="ds",
        limit=8,
        questions_per_node=3,
        write_logs=False,
    )
    smart_ports.fallback.assert_not_awaited()
    smart_ports.finalize.assert_awaited_once()
    smart_ports.log.assert_awaited_once()
    logged = smart_ports.log.await_args.kwargs
    assert logged["request_id"] == "req-path"
    assert [row["question_id"] for row in logged["recommendations"]] == [459, 460]
    assert all(
        row["strategy"] == "knowledge_path"
        for row in logged["recommendations"]
    )
    assert "path 策略题量不足" not in caplog.text


@pytest.mark.asyncio
async def test_path_failure_falls_back_and_writes_no_candidate_logs(
    smart_ports, monkeypatch, caplog,
):
    import app.services.knowledge_path_service as path_service

    smart_ports.experiment.return_value = {"source": "default"}
    fallback_rows = [question(8)]
    fallback_metadata = {
        8: {"strategy": "smart_vector", "recommend_reason": "weak"}
    }
    smart_ports.fallback.return_value = (fallback_rows, fallback_metadata)
    path = AsyncMock(side_effect=RuntimeError("path unavailable"))
    monkeypatch.setattr(path_service, "get_user_path_recommendations", path)
    compute_weak = AsyncMock(return_value=[])
    monkeypatch.setattr(svc, "_compute_weak_knowledge_points", compute_weak)
    random_fallback = AsyncMock(return_value=fallback_rows)
    monkeypatch.setattr(svc, "get_practice_questions", random_fallback)

    with caplog.at_level(logging.WARNING):
        result, metadata = await svc.get_smart_practice_questions(
            None, 9, "ds", count=1, smart_strategy="path", subject_ids=[2],
            request_id="req-path-failure",
        )

    assert result is fallback_rows
    assert metadata == {
        8: {
            "recommend_reason": "随机推荐（无足够做题记录）",
            "recommend_score": None,
            "similarity": None,
            "strategy": "random_fallback",
        }
    }
    failure_log = next(
        record for record in caplog.records
        if "knowledge_path 策略失败" in record.message
    )
    assert failure_log.name == "app.services.practice_service"
    path.assert_awaited_once_with(
        db=None,
        user_id=9,
        subject="ds",
        limit=8,
        questions_per_node=3,
        write_logs=False,
    )
    smart_ports.finalize.assert_awaited_once()
    smart_ports.log.assert_awaited_once()
    assert [row["question_id"] for row in smart_ports.log.await_args.kwargs["recommendations"]] == [8]


@pytest.mark.asyncio
async def test_full_scored_result_skips_fallback_and_logs_only_returned_rows(
    smart_ports,
):
    smart_ports.experiment.return_value = {
        "source": "experiment",
        "strategy": "scored",
        "experiment_id": 11,
        "variant_key": "B",
    }
    rows = [question(1), question(2), question(3)]
    metadata = {
        1: {
            "recommend_reason": "due", "recommend_score": 9.5,
            "strategy": "smart_scored", "similarity": None,
            "strategy_config_id": 7,
        },
        2: {
            "recommend_reason": "weak", "recommend_score": 8.5,
            "strategy": "smart_scored", "similarity": 0.2,
            "strategy_config_id": 7,
        },
        3: {
            "recommend_reason": "new", "recommend_score": 7.5,
            "strategy": "smart_scored", "similarity": None,
            "strategy_config_id": 7,
        },
    }
    smart_ports.scored.return_value = (rows, metadata)

    result, result_metadata = await svc.get_smart_practice_questions(
        None, 9, "ds", count=2, subject_ids=[2], request_id="req-9",
    )

    assert [row.id for row in result] == [1, 2]
    assert result_metadata is metadata
    assert all(meta["strategy"] == "smart_scored" for meta in metadata.values())
    smart_ports.scored.assert_awaited_once_with(
        db=None, user_id=9, subject_code="ds", count=2,
        exclude_answered=False, no_repeat_days=None, request_id="req-9",
        subject_ids=[2],
    )
    smart_ports.fallback.assert_not_awaited()
    smart_ports.merge.assert_not_called()
    finalize_args = smart_ports.finalize.await_args
    assert [row.id for row in finalize_args.args[0]] == [1, 2]
    assert finalize_args.args[1] is metadata
    assert finalize_args.args[2:] == (False, None, 9, "ds")
    assert finalize_args.kwargs == {
        "request_id": "req-9",
        "experiment_id": 11,
        "variant_key": "B",
    }
    smart_ports.log.assert_awaited_once()
    logged = smart_ports.log.await_args.kwargs
    assert logged["db"] is None
    assert logged["user_id"] == 9
    assert logged["scene"] == "practice_smart"
    assert logged["strategy"] == "fallback"
    assert logged["request_id"] == "req-9"
    assert logged["experiment_id"] == 11
    assert logged["variant_key"] == "B"
    assert [row["question_id"] for row in logged["recommendations"]] == [1, 2]
    assert all(row["subject_id"] == 2 for row in logged["recommendations"])
    assert all(
        row["strategy"] == "smart_scored" and row["strategy_config_id"] == 7
        for row in logged["recommendations"]
    )


@pytest.mark.asyncio
async def test_scored_shortfall_requests_only_remainder_and_merges_before_slice(
    smart_ports, caplog,
):
    primary = [question(1), question(2)]
    primary_metadata = {
        1: {"strategy": "smart_scored", "recommend_score": 9.0},
        2: {"strategy": "smart_scored", "recommend_score": 8.0},
    }
    fallback = [question(2), question(3), question(4), question(5)]
    fallback_metadata = {
        2: {"strategy": "smart_vector", "recommend_score": 7.0},
        3: {"strategy": "smart_vector", "recommend_score": 6.0},
        4: {"strategy": "smart_vector", "recommend_score": 5.0},
        5: {"strategy": "smart_vector", "recommend_score": 4.0},
    }
    smart_ports.scored.return_value = (primary, primary_metadata)
    smart_ports.fallback.return_value = (fallback, fallback_metadata)

    with caplog.at_level(logging.INFO):
        result, metadata = await svc.get_smart_practice_questions(
            None,
            9,
            "ds",
            count=4,
            exclude_answered=True,
            no_repeat_days=3,
            use_leitner=False,
            subject_ids=[2],
            skip_finalize=True,
        )

    assert [row.id for row in result] == [1, 2, 3, 4]
    shortfall_log = next(
        record for record in caplog.records
        if "scored 策略题量不足" in record.message
    )
    assert shortfall_log.name == "app.services.practice_service"
    assert metadata == {
        1: primary_metadata[1],
        2: primary_metadata[2],
        3: fallback_metadata[3],
        4: fallback_metadata[4],
    }
    smart_ports.fallback.assert_awaited_once_with(
        db=None,
        user_id=9,
        subject_code="ds",
        count=2,
        exclude_answered=True,
        no_repeat_days=3,
        use_leitner=False,
        exclude_ids={1, 2},
        subject_ids=[2],
    )
    smart_ports.merge.assert_called_once_with(
        primary,
        primary_metadata,
        fallback,
        fallback_metadata,
        count=4,
    )
    smart_ports.finalize.assert_awaited_once()


@pytest.mark.asyncio
async def test_scored_failure_falls_through_to_inline_weakness_fallback(
    smart_ports, monkeypatch, caplog,
):
    import app.services.mastery_service as mastery_service

    mastery = AsyncMock(return_value=[])
    compute_weak = AsyncMock(return_value=[])
    random_rows = [question(8)]
    random_fallback = AsyncMock(return_value=random_rows)
    smart_ports.scored.side_effect = RuntimeError("scored unavailable")

    monkeypatch.setattr(
        mastery_service, "get_user_weak_knowledge_points", mastery
    )
    monkeypatch.setattr(svc, "_compute_weak_knowledge_points", compute_weak)
    monkeypatch.setattr(svc, "get_practice_questions", random_fallback)

    with caplog.at_level(logging.WARNING):
        result, metadata = await svc.get_smart_practice_questions(
            None, 9, "ds", count=1, subject_ids=[2], skip_finalize=True,
        )

    assert result == random_rows
    failure_log = next(
        record for record in caplog.records
        if "scored 策略失败" in record.message
    )
    assert failure_log.name == "app.services.practice_service"
    assert metadata == {
        8: {
            "recommend_reason": "随机推荐（无足够做题记录）",
            "recommend_score": None,
            "strategy": "random_fallback",
            "similarity": None,
        }
    }
    mastery.assert_awaited_once_with(None, 9, "ds", limit=5)
    compute_weak.assert_awaited_once_with(None, 9, [2])
    random_fallback.assert_awaited_once_with(
        db=None,
        user_id=9,
        subject_code="ds",
        count=1,
        mode="random",
        exclude_answered=False,
        no_repeat_days=None,
        use_leitner=True,
        subject_ids=[2],
    )
    smart_ports.fallback.assert_not_awaited()
    smart_ports.finalize.assert_awaited_once()


@pytest.mark.asyncio
async def test_scored_cancellation_propagates_without_fallback_or_finalize(
    smart_ports,
):
    smart_ports.scored.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await svc.get_smart_practice_questions(
            None, 9, "ds", count=1, subject_ids=[2],
        )

    smart_ports.fallback.assert_not_awaited()
    smart_ports.finalize.assert_not_awaited()

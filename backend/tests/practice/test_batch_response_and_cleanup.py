"""Response and sequential-cleanup contracts for practice batch completion."""

from __future__ import annotations

from app.services.practice.batch_reservation_cleanup import (
    build_sequential_reservation_cleanup,
)
from app.services.practice.batch_response import build_batch_submission_response


def test_response_orders_results_and_normalizes_entry_context():
    payload = build_batch_submission_response(
        response_by_question={1: {"question_id": 1}, 2: {"question_id": 2}},
        issued_order=[2, 1],
        total_correct=1,
        total_wrong=1,
        skipped_questions=[object(), object()],
        knowledge_context={"practice_mode": "knowledge"},
        entry_context={"from": "chapter"},
        persisted_knowledge_session=lambda context: {"mode": context["practice_mode"]},
    )

    assert payload == {
        "results": [{"question_id": 2}, {"question_id": 1}],
        "total_correct": 1,
        "total_wrong": 1,
        "total_skipped": 2,
        "knowledge_session": {"mode": "knowledge"},
        "entry_context": {"from": "chapter"},
    }


def test_non_dict_entry_context_is_null():
    payload = build_batch_submission_response(
        response_by_question={},
        issued_order=[],
        total_correct=0,
        total_wrong=0,
        skipped_questions=[],
        knowledge_context=None,
        entry_context="chapter",
        persisted_knowledge_session=lambda _context: None,
    )
    assert payload["entry_context"] is None


def test_sequential_cleanup_requires_request_id_and_mode():
    assert (
        build_sequential_reservation_cleanup(
            user_id=8,
            batch_payload={"mode": "sequential"},
            all_question_ids=[1],
        )
        is None
    )
    assert (
        build_sequential_reservation_cleanup(
            user_id=8,
            batch_payload={"mode": "random", "seq_reservation_request_id": "start"},
            all_question_ids=[1],
        )
        is None
    )


def test_sequential_cleanup_statement_is_built():
    statement = build_sequential_reservation_cleanup(
        user_id=8,
        batch_payload={
            "mode": "sequential",
            "sid": 3,
            "seq_reservation_request_id": "submit-start",
        },
        all_question_ids=[1, 2],
    )

    assert statement is not None
    rendered = str(statement).replace("\n", " ")
    assert "sequential_reservations" in rendered
    assert "user_id" in rendered
    assert "question_id" in rendered

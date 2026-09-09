from types import SimpleNamespace

from app.schemas.practice import BatchSubmitResponse
from app.services.practice.knowledge_session_summary import (
    persisted_knowledge_session,
    public_knowledge_session,
)
from app.services.practice_service import (
    _decode_practice_batch_token,
    create_practice_batch_token,
)


def _context():
    return {
        "v": 1,
        "practice_mode": "knowledge_chapter",
        "root_id": 12,
        "root_name": "线性表",
        "include_descendants": True,
        "scope_count": 18,
        "baseline": {
            "root": [62.5, 0.55, 4, 10, 18],
            "points": [[13, 55.0, 0.5, 3], [25, None, 0.0, 0]],
        },
    }


def test_knowledge_session_public_payload_hides_baseline():
    payload = public_knowledge_session(_context())
    assert payload == {
        "practice_mode": "knowledge_chapter",
        "root_knowledge_point_id": 12,
        "root_name": "线性表",
        "include_descendants": True,
        "knowledge_point_count": 18,
    }
    assert "_baseline" not in payload


def test_persisted_session_keeps_signed_baseline_but_response_schema_drops_it():
    persisted = persisted_knowledge_session(_context())
    assert persisted["_baseline"]["points"][0][0] == 13
    response = BatchSubmitResponse(
        results=[],
        total_correct=0,
        total_wrong=0,
        knowledge_session=persisted,
    )
    dumped = response.model_dump()
    assert dumped["knowledge_session"]["root_knowledge_point_id"] == 12
    assert "_baseline" not in dumped["knowledge_session"]


def test_signed_batch_token_round_trips_knowledge_context():
    context = _context()
    token, revisions, request_id = create_practice_batch_token(
        user_id=7,
        subject_id=7,
        mode="random",
        questions=[SimpleNamespace(id=101)],
        revision_ids={101: 9001},
        knowledge_context=context,
    )
    assert token
    assert revisions == {101: 9001}
    assert request_id
    payload = _decode_practice_batch_token(token)
    assert payload["knowledge_context"] == context

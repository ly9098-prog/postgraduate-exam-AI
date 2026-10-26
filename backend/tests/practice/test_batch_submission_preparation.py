"""Order, identity and error contracts before claiming a practice submission."""

from types import SimpleNamespace

import pytest

from app.services.practice import batch_submission_flow as flow
from app.services.practice.batch_token import PracticeBatchTokenError
from tests.practice.test_batch_submission_flow import request


def prepared_inputs(monkeypatch):
    events = []
    item = request(skipped_question_ids=[2])
    protocol = flow.BatchProtocol([2], [1, 2], "hash", "request")
    questions = {1: object(), 2: object()}
    payload = {"knowledge_context": {"signed": True}}
    contract = flow.BatchContract({1: 11, 2: 22}, [2, 1], payload, questions)
    evaluated = [(questions[1], True, "A", 5)]
    answer_ids = {1: "answer-id"}
    values = {"subject_id": 3, "duration_sec": 60}
    scope = {"subject_id": 3}

    def mark(name, result):
        def callback(*args, **kwargs):
            events.append((name, args, kwargs))
            return result

        return callback

    monkeypatch.setattr(
        flow,
        "evaluate_batch_answers",
        mark(
            "grade",
            (
                evaluated,
                answer_ids,
                1,
                0,
            ),
        ),
    )
    monkeypatch.setattr(flow, "normalize_practice_session", mark("session", values))
    monkeypatch.setattr(flow, "_validate_session_contract", mark("validate", None))
    monkeypatch.setattr(flow, "build_practice_session_scope", mark("scope", scope))
    monkeypatch.setattr(flow, "_validate_scope_subject", mark("subject", None))
    return SimpleNamespace(**locals())


def test_preparation_preserves_evaluation_order_and_references(monkeypatch):
    case = prepared_inputs(monkeypatch)
    result = flow._prepare_batch_submission(case.item, case.protocol, case.contract)
    assert [name for name, _, _ in case.events] == [
        "grade",
        "session",
        "validate",
        "scope",
        "subject",
    ]
    assert case.events[0][2] == {
        "answers": case.item.answers,
        "questions": case.questions,
    }
    assert case.events[1][1] == (case.item.session_meta,)
    assert case.events[1][2] == {
        "user_id": 2,
        "answered_count": 1,
        "total_correct": 1,
        "total_wrong": 0,
    }
    assert case.events[2][2]["session_values"] is case.values
    assert case.events[2][2]["evaluated_answers"] is case.evaluated
    assert case.events[3][1][0] is case.payload["knowledge_context"]
    assert case.events[3][2] == {"fallback_subject_id": 3}
    assert case.events[4][1] == (case.scope, case.values)
    for name, original in [
        ("evaluated_answers", case.evaluated),
        ("answer_request_ids", case.answer_ids),
        ("all_question_ids", case.protocol.all_question_ids),
        ("issued_revisions", case.contract.issued_revisions),
        ("issued_order", case.contract.issued_order),
        ("batch_payload", case.payload),
        ("session_values", case.values),
        ("scope_snapshot", case.scope),
    ]:
        assert getattr(result, name) is original
    assert result.skipped_questions == [case.questions[2]]
    assert result.payload_hash == "hash"


@pytest.mark.parametrize("failed", ["grade", "session", "validate", "scope", "subject"])
def test_preparation_stops_at_first_failure(monkeypatch, failed):
    case = prepared_inputs(monkeypatch)
    names = [
        "evaluate_batch_answers",
        "normalize_practice_session",
        "_validate_session_contract",
        "build_practice_session_scope",
        "_validate_scope_subject",
    ]
    order = ["grade", "session", "validate", "scope", "subject"]
    error = RuntimeError(failed)

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(flow, names[order.index(failed)], fail)
    with pytest.raises(RuntimeError) as caught:
        flow._prepare_batch_submission(case.item, case.protocol, case.contract)
    assert caught.value is error
    assert [name for name, _, _ in case.events] == order[: order.index(failed)]


@pytest.mark.parametrize(
    ("message", "error_type"),
    [
        ("request_id invalid", ValueError),
        ("question_count invalid", ValueError),
        ("subject mismatch", PracticeBatchTokenError),
        ("mode mismatch", PracticeBatchTokenError),
    ],
)
def test_session_consistency_error_precedes_duration(monkeypatch, message, error_type):
    monkeypatch.setattr(flow, "build_session_consistency_error", lambda **_: message)
    monkeypatch.setattr(
        flow, "validate_answer_duration", lambda **_: pytest.fail("duration")
    )
    with pytest.raises(error_type, match=message):
        flow._validate_session_contract(
            request=request(),
            protocol=flow.BatchProtocol([], [1], "hash", "r"),
            contract=flow.BatchContract({}, [], {}, {}),
            session_values={},
            evaluated_answers=[],
        )


def test_session_duration_uses_dynamic_tolerance_and_original_values(monkeypatch):
    events = []
    evaluated = []
    monkeypatch.setattr(flow, "build_session_consistency_error", lambda **_: None)
    monkeypatch.setattr(flow, "PRACTICE_ANSWER_DURATION_TOLERANCE_SEC", 19)

    def duration(**kwargs):
        events.append(kwargs)
        return "too long"

    monkeypatch.setattr(flow, "validate_answer_duration", duration)
    with pytest.raises(ValueError, match="too long"):
        flow._validate_session_contract(
            request=request(),
            protocol=flow.BatchProtocol([], [1], "hash", "r"),
            contract=flow.BatchContract({}, [], {}, {}),
            session_values={"duration_sec": "60"},
            evaluated_answers=evaluated,
        )
    assert events == [
        {
            "evaluated_answers": evaluated,
            "duration_sec": 60,
            "tolerance_sec": 19,
        }
    ]
    assert events[0]["evaluated_answers"] is evaluated


def test_protocol_fingerprint_precedes_request_id_normalization(monkeypatch):
    item = request()
    events = []
    skipped, all_ids = [], [1]
    monkeypatch.setattr(
        flow, "validate_batch_submission_inputs", lambda **_: ([1], skipped, all_ids)
    )

    def fingerprint(**kwargs):
        events.append(("hash", kwargs))
        monkeypatch.setattr(flow, "normalize_practice_request_id", lambda value: "late")
        return "digest"

    monkeypatch.setattr(flow, "practice_submission_fingerprint", fingerprint)
    result = flow._validate_protocol(item)
    assert result.request_id == "late"
    assert result.payload_hash == "digest"
    assert result.skipped_ids is skipped
    assert result.all_question_ids is all_ids
    assert events[0][1]["answers"] is item.answers
    assert events[0][1]["session_meta"] is item.session_meta


@pytest.mark.parametrize("limit", [0, 1, 2])
def test_protocol_uses_dynamic_question_limit(monkeypatch, limit):
    monkeypatch.setattr(flow, "PRACTICE_BATCH_MAX_QUESTIONS", limit)
    if not limit:
        with pytest.raises(ValueError, match="answers"):
            flow._validate_protocol(request())
    else:
        assert flow._validate_protocol(request()).all_question_ids == [1]


@pytest.mark.parametrize(
    "scope",
    [
        None,
        {
            "practice_mode": "knowledge",
            "root_knowledge_point_id": "17",
        },
    ],
)
def test_session_model_receives_original_scope_and_values(monkeypatch, scope):
    events = []
    result = object()
    monkeypatch.setattr(
        flow, "PracticeSession", lambda **kwargs: (events.append(kwargs), result)[1]
    )
    prepared = SimpleNamespace(
        session_values={"user_id": 2, "request_id": "request"},
        payload_hash="hash",
        scope_snapshot=scope,
    )
    assert flow._build_practice_session(prepared) is result
    assert events == [
        {
            "user_id": 2,
            "request_id": "request",
            "submission_payload_hash": "hash",
            "scope_type": "knowledge" if scope is not None else None,
            "scope_root_knowledge_point_id": 17 if scope is not None else None,
            "scope_snapshot": scope,
        }
    ]
    assert events[0]["scope_snapshot"] is scope


@pytest.mark.parametrize(
    "revision_id,question_id,active,error",
    [
        (11, 1, True, None),
        (11, 2, True, "绑定关系"),
        (11, 1, False, "不可用"),
        (99, 1, True, "绑定关系"),
    ],
)
def test_revision_validation_retains_binding_and_active_checks(
    revision_id,
    question_id,
    active,
    error,
):
    view = SimpleNamespace(question_id=question_id, is_active=active)
    if error is not None:
        with pytest.raises(PracticeBatchTokenError, match=error):
            flow._validated_revision_questions({1: revision_id}, {11: view})
    else:
        result = flow._validated_revision_questions({1: revision_id}, {11: view})
        assert result[1] is view

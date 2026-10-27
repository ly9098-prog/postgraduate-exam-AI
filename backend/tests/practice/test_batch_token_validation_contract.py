"""Submission validation order, original errors and signed batch boundaries."""

from datetime import timedelta

import pytest

from tests.practice.batch_token_contract_support import (
    NOW,
    NOW_DT,
    payload,
    session,
)

pytest_plugins = ("tests.practice.batch_token_contract_support",)


def test_preserves_payload_identity_issued_order_and_coercion(validate):
    value = payload(questions=[["2", "202"], [1, 101]])
    revisions, order, result = validate(value, ids=["1", 2])
    assert revisions == {2: 202, 1: 101} and list(revisions) == [2, 1]
    assert order == [2, 1] and result is value
    assert value["questions"] == [["2", "202"], [1, 101]]


@pytest.mark.parametrize(
    "questions",
    [
        None,
        (),
        {},
        [],
        [[1]],
        [[1, 2, 3]],
        [(1, 2)],
        [None],
        [[0, 1]],
        [[-1, 1]],
        [[1, 0]],
        [[1, -1]],
        [["bad", 1]],
        [[1, None]],
        [[2, 202], ["2", 203]],
        [[i, i] for i in range(1, 52)],
    ],
)
def test_invalid_issued_questions_fail_before_submitted_reads(
    token_module,
    validate,
    questions,
):
    with pytest.raises(
        token_module.PracticeBatchTokenError, match="^练习批次题目列表无效$"
    ):
        validate(payload(questions=questions), ids=["bad"])


@pytest.mark.parametrize(
    "questions,cause",
    [
        ([[1]], ValueError),
        ([["bad", 1]], ValueError),
        ([[1, None]], TypeError),
        ([[2, 202], [2, 203]], ValueError),
    ],
)
def test_question_item_errors_keep_the_original_cause(
    token_module, validate, questions, cause
):
    with pytest.raises(token_module.PracticeBatchTokenError) as caught:
        validate(payload(questions=questions))
    assert type(caught.value.__cause__) is cause


@pytest.mark.parametrize("ids", [[1], [1, 1], [1, 2, 2], [1, 3]])
def test_submission_set_and_cardinality_are_both_enforced(token_module, validate, ids):
    with pytest.raises(
        token_module.PracticeBatchTokenError, match="^提交题目与服务器下发批次不一致$"
    ):
        validate(ids=ids)


def test_subject_and_submission_conversion_errors_keep_distinct_boundaries(
    token_module, validate
):
    with pytest.raises(ValueError) as raw:
        validate(ids=["bad"])
    assert type(raw.value) is ValueError and raw.value.__cause__ is None
    with pytest.raises(
        token_module.PracticeBatchTokenError, match="缺少有效科目"
    ) as wrapped:
        validate(meta=session(subject_id="bad"))
    assert type(wrapped.value.__cause__) is ValueError


@pytest.mark.parametrize(
    "changes,meta,answers,message",
    [
        ({"uid": 8, "questions": []}, {}, [], "练习批次不属于当前用户"),
        ({"sid": 4}, {}, [], "提交科目与服务器下发批次不一致"),
        ({}, {"mode": "invalid"}, [], "提交模式与服务器下发批次不一致"),
        ({"rid": "other"}, {}, [], "提交 request_id 与服务器下发批次不一致"),
        (
            {},
            {},
            [{"request_id": "other"}],
            "推荐反馈 request_id 与服务器下发批次不一致",
        ),
    ],
)
def test_failure_messages_and_order(
    token_module, validate, changes, meta, answers, message
):
    with pytest.raises(token_module.PracticeBatchTokenError, match="^" + message + "$"):
        validate(payload(**changes), meta=session(**meta), answers=answers)


@pytest.mark.parametrize("count", [1, 50])
def test_inclusive_batch_size_boundary(validate, count):
    questions = [[i, 100 + i] for i in range(1, count + 1)]
    revisions, order, _ = validate(
        payload(questions=questions), ids=list(range(count, 0, -1))
    )
    assert list(revisions) == order == list(range(1, count + 1))


@pytest.mark.parametrize("delta,allowed", [(-300, True), (-301, False)])
def test_issuance_clock_skew_is_inclusive(token_module, validate, delta, allowed):
    meta = session(started_at=(NOW_DT + timedelta(seconds=delta)).isoformat())
    if allowed:
        assert validate(meta=meta)[1] == [2, 1]
    else:
        with pytest.raises(token_module.PracticeBatchTokenError, match="开始时间早于"):
            validate(meta=meta)


@pytest.mark.parametrize("delta,allowed", [(300, True), (301, False)])
def test_finished_clock_skew_is_inclusive(token_module, validate, delta, allowed):
    meta = session(finished_at=(NOW_DT + timedelta(seconds=delta)).isoformat())
    if allowed:
        assert validate(meta=meta)[1] == [2, 1]
    else:
        with pytest.raises(
            token_module.PracticeBatchTokenError, match="结束时间明显晚于"
        ):
            validate(meta=meta)


def test_dynamic_limit_is_read_on_each_validation(token_module, validate, monkeypatch):
    monkeypatch.setattr(token_module, "PRACTICE_BATCH_MAX_QUESTIONS", 1)
    with pytest.raises(token_module.PracticeBatchTokenError, match="题目列表无效"):
        validate()


def test_overflow_and_base_exception_are_not_swallowed(validate):
    for error in [OverflowError("integer sentinel"), KeyboardInterrupt("cancel")]:

        class Number:
            def __int__(self):
                raise error

        with pytest.raises(type(error)) as caught:
            validate(payload(questions=[[Number(), 202]]))
        assert caught.value is error


def test_validation_get_order_keeps_user_and_questions_before_session(validate):
    reads = []

    class Payload(dict):
        def get(self, key, default=None):
            reads.append(key)
            return super().get(key, default)

    class Session(dict):
        def get(self, key, default=None):
            reads.append("session:" + key)
            return super().get(key, default)

    validate(Payload(payload()), meta=Session(session()))
    assert reads == [
        "uid",
        "questions",
        "session:subject_id",
        "sid",
        "session:mode",
        "mode",
        "rid",
        "session:request_id",
        "rec_rid",
        "iat",
        "session:started_at",
        "session:finished_at",
    ]


def test_datetime_parser_and_clock_remain_live_module_ports(
    token_module, validate, monkeypatch
):
    reads = []

    def parse(value):
        reads.append(value)
        return None

    monkeypatch.setattr(token_module, "parse_session_datetime", parse)
    value = payload(iat=NOW)
    assert (
        validate(value, meta=session(started_at="begin", finished_at="end"))[2] is value
    )
    assert reads == ["begin", "end"]

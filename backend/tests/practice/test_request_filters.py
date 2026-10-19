"""Regression checks for practice request filter parsing."""

import pytest

from app.services.practice.request_filters import (
    PracticeRequestFilterError,
    parse_knowledge_point_names,
    parse_targeted_question_ids,
    validate_knowledge_point_filters,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        (" , ", []),
        (" 导数, , 极限 ", ["导数", "极限"]),
        ("导数,导数", ["导数", "导数"]),
    ],
)
def test_knowledge_point_names_preserve_legacy_semantics(value, expected):
    assert parse_knowledge_point_names(value) == expected


def test_knowledge_point_filters_keep_modes_explicit():
    validate_knowledge_point_filters(
        knowledge_point=None,
        knowledge_point_id=4,
        include_descendants=True,
        mode="random",
    )
    with pytest.raises(PracticeRequestFilterError, match="random"):
        validate_knowledge_point_filters(
            knowledge_point=None,
            knowledge_point_id=4,
            include_descendants=True,
            mode="smart",
        )


@pytest.mark.parametrize(
    ("name", "point_id", "descendants", "mode", "message"),
    [
        ("导数", 4, True, "smart", "不能同时使用"),
        (None, None, True, "smart", "需要 knowledge_point_id"),
        (None, 4, True, "sequential", "仅支持 random"),
    ],
)
def test_knowledge_point_filter_error_precedence(
    name, point_id, descendants, mode, message
):
    with pytest.raises(PracticeRequestFilterError, match=message):
        validate_knowledge_point_filters(
            knowledge_point=name,
            knowledge_point_id=point_id,
            include_descendants=descendants,
            mode=mode,
        )


@pytest.mark.parametrize("mode", ["random", "smart", "similar", "sequential"])
def test_exact_knowledge_point_filter_allows_existing_modes(mode):
    validate_knowledge_point_filters(
        knowledge_point=None,
        knowledge_point_id=4,
        include_descendants=False,
        mode=mode,
    )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("1,1", "不允许重复"),
        ("0", "正整数"),
        ("-1", "正整数"),
        (" , ", "1-50"),
        (",".join(str(value) for value in range(1, 52)), "1-50"),
        ("abc", "格式无效"),
        ("1.5", "格式无效"),
    ],
)
def test_targeted_question_ids_reject_invalid_values(value, message):
    with pytest.raises(PracticeRequestFilterError, match=message):
        parse_targeted_question_ids(
            value,
            source_question_id=None,
            knowledge_points=None,
            knowledge_point_ids=None,
            mode="random",
        )


def test_targeted_question_ids_require_random_and_no_other_scope():
    assert parse_targeted_question_ids(
        "10, 11",
        source_question_id=None,
        knowledge_points=None,
        knowledge_point_ids=None,
        mode="random",
    ) == [10, 11]
    with pytest.raises(PracticeRequestFilterError, match="混用"):
        parse_targeted_question_ids(
            "10",
            source_question_id=None,
            knowledge_points=["导数"],
            knowledge_point_ids=None,
            mode="random",
        )


@pytest.mark.parametrize("value", [None, ""])
def test_absent_target_ids_do_not_validate_targeted_only_constraints(value):
    assert (
        parse_targeted_question_ids(
            value,
            source_question_id=3,
            knowledge_points=["导数"],
            knowledge_point_ids=[1],
            mode="smart",
        )
        == []
    )


@pytest.mark.parametrize("mode", ["smart", "similar", "sequential"])
def test_targeted_questions_reject_non_random_modes(mode):
    with pytest.raises(PracticeRequestFilterError, match="仅支持 random runner"):
        parse_targeted_question_ids(
            "1",
            source_question_id=None,
            knowledge_points=None,
            knowledge_point_ids=None,
            mode=mode,
        )


@pytest.mark.parametrize(
    ("source", "names", "ids"),
    [(3, None, None), (None, ["导数"], None), (None, None, [1])],
)
def test_targeted_question_conflicts_precede_mode_check(source, names, ids):
    with pytest.raises(PracticeRequestFilterError, match="混用"):
        parse_targeted_question_ids(
            "1",
            source_question_id=source,
            knowledge_points=names,
            knowledge_point_ids=ids,
            mode="smart",
        )


def test_targeted_question_order_and_maximum_are_preserved():
    expected = list(range(50, 0, -1))
    assert (
        parse_targeted_question_ids(
            ",".join(str(value) for value in expected),
            source_question_id=0,
            knowledge_points=[],
            knowledge_point_ids=[],
            mode="random",
        )
        == expected
    )

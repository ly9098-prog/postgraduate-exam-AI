"""Pin live parser ports, answer-check traversal, and reference semantics."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import ai_service
from app.services.ai import analysis_content as content


@pytest.mark.parametrize(
    "name",
    [
        "_canonical_answer_check_list",
        "_canonical_answer_echo",
        "_coerce_analysis_text",
        "_decode_structured_content",
        "_extract_analysis_fields",
        "_extract_answer_check",
        "_looks_like_structured_analysis_text",
        "_normalize_ai_analysis",
        "_parse_titled_analysis_text",
        "_pick_field",
        "_strip_code_fence",
        "_validate_answer_check",
        "is_valid_ai_analysis",
        "parse_error_analysis_content",
    ],
)
def test_historical_functions_keep_identity_metadata_and_source_globals(name):
    function = getattr(content, name)
    assert getattr(ai_service, name) is function
    assert function.__module__ == content.__name__
    assert function.__name__ == name
    assert function.__globals__ is vars(content)


@pytest.mark.parametrize("depth", [5, 6, 7])
@pytest.mark.parametrize("container", ["direct", "list", "wrapper", "encoded"])
def test_answer_check_depth_and_result_reference(depth, container, monkeypatch):
    actual = {"correct_answer": "A"}
    value = {"answer_check": actual}
    if container == "list":
        value = [value]
    elif container == "wrapper":
        value = {"data": value}
    elif container == "encoded":
        decoded = value
        value = "encoded"
        monkeypatch.setattr(content, "_decode_structured_content", lambda _: decoded)
    found = content._extract_answer_check(value, depth)
    limit = 6 if container == "direct" else 5
    assert found is (actual if depth <= limit else None)


def test_answer_check_recursion_reloads_the_original_port_between_items(monkeypatch):
    original = content._extract_answer_check
    first, second = {}, {}
    actual = {"correct_answer": "A"}
    calls = []

    def replacement(value, depth):
        calls.append(("second", value, depth))
        return actual

    def initial(value, depth):
        calls.append(("first", value, depth))
        monkeypatch.setattr(content, "_extract_answer_check", replacement)
        return None

    monkeypatch.setattr(content, "_extract_answer_check", initial)
    assert original([first, second], 2) is actual
    assert calls == [("first", first, 3), ("second", second, 3)]


def test_answer_check_aliases_precede_wrappers_and_return_the_original_dict():
    first, later = {"correct_answer": "A"}, {"correct_answer": "B"}
    value = {"data": {"answer_check": later}, "answerCheck": later}
    value["answer_check"] = first
    assert content._extract_answer_check(value) is first
    assert content._extract_answer_check({"result": later, "data": value}) is first


def test_answer_check_wrapper_is_visited_again_in_generic_fallback(monkeypatch):
    original = content._extract_answer_check
    nested = {}
    visited = []

    def recurse(value, depth):
        visited.append((value, depth))
        return None

    monkeypatch.setattr(content, "_extract_answer_check", recurse)
    assert original({"data": nested}, 1) is None
    assert visited == [(nested, 2), (nested, 2)]


def test_validation_observes_ports_replaced_during_decode_and_normalization(
    monkeypatch,
):
    actual = {"correct_answer": "A", "user_answer": "B"}
    expected = {"correct_answer": "A", "user_answer": "B"}
    calls = []

    def later_echo(value, expected):
        calls.append(("later_echo", value, expected))
        return value

    def first_echo(value, expected):
        calls.append(("first_echo", value, expected))
        monkeypatch.setattr(content, "_canonical_answer_echo", later_echo)
        return value

    def later_list(value):
        calls.append(("later_list", value))
        return value

    def first_list(value):
        calls.append(("first_list", value))
        monkeypatch.setattr(content, "_canonical_answer_check_list", later_list)
        return value

    def decode(raw):
        calls.append(("decode", raw))
        monkeypatch.setattr(content, "_extract_answer_check", lambda _: actual)
        return {}

    monkeypatch.setattr(content, "_decode_structured_content", decode)
    monkeypatch.setattr(content, "_canonical_answer_echo", first_echo)
    monkeypatch.setattr(content, "_canonical_answer_check_list", first_list)
    valid, reason, found = content._validate_answer_check("raw", expected)
    assert (valid, reason) == (True, "")
    assert found is actual
    assert calls == [
        ("decode", "raw"),
        ("first_echo", "A", "A"),
        ("later_echo", "B", "B"),
        ("later_echo", "A", "A"),
        ("later_echo", "B", "B"),
        ("first_list", []),
        ("later_list", []),
        ("later_list", []),
        ("later_list", []),
    ]


def test_validation_keeps_echo_order_and_skips_lists_after_correct_mismatch(
    monkeypatch,
):
    actual = {"correct_answer": "A", "user_answer": "B"}
    calls = []
    monkeypatch.setattr(content, "_decode_structured_content", lambda _: actual)
    monkeypatch.setattr(content, "_extract_answer_check", lambda _: actual)

    def echo(value, expected):
        calls.append((value, expected))
        return value

    def unexpected(_):
        pytest.fail("list normalization must not run after answer mismatch")

    monkeypatch.setattr(content, "_canonical_answer_echo", echo)
    monkeypatch.setattr(content, "_canonical_answer_check_list", unexpected)
    valid, reason, found = content._validate_answer_check(
        "raw", {"correct_answer": "C", "user_answer": "B"}
    )
    assert (valid, reason) == (False, "answer_check_correct_mismatch")
    assert found is actual
    assert calls == [("A", "C"), ("B", "B"), ("C", "C"), ("B", "B")]


@pytest.mark.parametrize(
    ("name", "args", "port"),
    [
        ("_extract_answer_check", ("raw",), "_decode_structured_content"),
        ("_validate_answer_check", ("raw", {}), "_decode_structured_content"),
        ("_parse_titled_analysis_text", ("raw",), "_strip_code_fence"),
        ("_looks_like_structured_analysis_text", ("raw",), "re"),
    ],
)
def test_parser_port_exceptions_escape_with_the_same_identity(
    name, args, port, monkeypatch
):
    failure = RuntimeError("sentinel")

    def fail(*args, **kwargs):
        raise failure

    replacement = (
        SimpleNamespace(search=fail, escape=lambda value: value, IGNORECASE=0)
        if port == "re"
        else fail
    )
    monkeypatch.setattr(content, port, replacement)
    with pytest.raises(RuntimeError) as caught:
        getattr(content, name)(*args)
    assert caught.value is failure


def test_decoder_reloads_literal_parser_and_fence_ports(monkeypatch):
    events = []
    actual = {"decoded": True}

    def literal(candidate):
        events.append(("literal", candidate))
        raise SyntaxError("not yet")

    def strip(value):
        events.append(("strip", value))
        monkeypatch.setattr(
            content, "ast", SimpleNamespace(literal_eval=lambda _: actual)
        )
        return "replacement"

    monkeypatch.setattr(content, "ast", SimpleNamespace(literal_eval=literal))
    monkeypatch.setattr(content, "_strip_code_fence", strip)
    assert content._decode_structured_content("unparsed") is actual
    assert events == [("literal", "unparsed"), ("strip", "unparsed")]


def test_parser_constants_remain_live_in_the_original_module(monkeypatch):
    monkeypatch.setattr(content, "_DIAGNOSIS_KEYS", ("custom",))
    monkeypatch.setattr(content, "_KNOWLEDGE_KEYS", ())
    monkeypatch.setattr(content, "_TASK_KEYS", ())
    monkeypatch.setattr(content, "_ANSWER_CHECK_KEYS", ("verify",))
    monkeypatch.setattr(content, "_ANALYSIS_WRAPPER_KEYS", ("box",))
    monkeypatch.setattr(content, "_ROMAN_ECHO_TRANSLATION", str.maketrans({"x": "v"}))
    actual = {"correct_answer": "A"}
    assert content._looks_like_structured_analysis_text('"custom": broken')
    assert content._extract_answer_check({"box": {"verify": actual}}) is actual
    assert content._canonical_answer_check_list(["x"]) == ["V"]
    assert content._extract_analysis_fields({"custom": "leaf"}) == {
        "mistake_diagnosis": "leaf",
        "knowledge_patch": "",
        "review_task": "",
    }


@pytest.mark.parametrize(
    ("name", "args", "port"),
    [
        ("_decode_structured_content", ("raw",), "json"),
        ("_parse_titled_analysis_text", ("raw",), "_strip_code_fence"),
        ("_validate_answer_check", ("raw", {}), "_decode_structured_content"),
        ("_extract_answer_check", ({},), "_ANSWER_CHECK_KEYS"),
    ],
)
def test_deleted_ports_keep_original_name_errors(name, args, port, monkeypatch):
    monkeypatch.delattr(content, port)
    with pytest.raises(NameError) as caught:
        getattr(content, name)(*args)
    assert caught.value.name == port
    assert str(caught.value) == f"name '{port}' is not defined"

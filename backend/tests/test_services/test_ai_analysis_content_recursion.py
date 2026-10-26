"""Characterize recursive analysis selection and its observable traversal order."""

from __future__ import annotations

import json

import pytest

from app.services import ai_service
from app.services.ai import analysis_content as content


def analysis(diagnosis="", knowledge="", task=""):
    return {
        "mistake_diagnosis": diagnosis,
        "knowledge_patch": knowledge,
        "review_task": task,
    }


@pytest.mark.parametrize(
    ("value", "depth", "expected"),
    [
        (None, 0, analysis()),
        ({"diagnosis": "leaf"}, 6, analysis("leaf")),
        ({"content": {"diagnosis": "leaf"}}, 6, analysis()),
        (" plain ", 6, analysis("plain")),
        ('{"diagnosis":"leaf"}', 6, analysis()),
        ([{"diagnosis": "leaf"}], 5, analysis("leaf")),
        ([{"diagnosis": "leaf"}], 6, analysis()),
        (7, 5, analysis("7")),
        (7, 6, analysis()),
        ("leaf", 7, analysis()),
    ],
)
def test_depth_limit_counts_recursive_edges_without_charging_helpers(
    value, depth, expected
):
    assert content._extract_analysis_fields(value, depth) == expected


@pytest.mark.parametrize("wrappers", [5, 6, 7])
@pytest.mark.parametrize("encoded", [False, True])
def test_public_parser_and_normalizer_keep_their_original_depth_budget(
    wrappers, encoded
):
    value = {"diagnosis": "leaf"}
    for _ in range(wrappers):
        value = {"data": value}
    expected = analysis("leaf") if wrappers <= 6 else analysis()
    if encoded:
        assert ai_service.parse_error_analysis_content(json.dumps(value)) == expected
    else:
        assert ai_service._normalize_ai_analysis(value) == expected


@pytest.mark.parametrize(
    ("field", "aliases"),
    [
        (
            "mistake_diagnosis",
            (
                "mistake_diagnosis",
                "error_analysis",
                "diagnosis",
                "mistakeDiagnosis",
                "mistakediagnosis",
                "\u9519\u56e0\u8bca\u65ad",
            ),
        ),
        (
            "knowledge_patch",
            (
                "knowledge_patch",
                "knowledge_weakness",
                "knowledge",
                "knowledgePatch",
                "knowledgepatch",
                "\u8865\u6f0f\u91cd\u70b9",
            ),
        ),
        (
            "review_task",
            (
                "review_task",
                "suggestion",
                "task",
                "reviewTask",
                "reviewtask",
                "reviewask",
                "\u590d\u7ec3\u4efb\u52a1",
            ),
        ),
    ],
)
def test_alias_priority_skips_empty_values_and_ignores_insertion_order(field, aliases):
    for index, alias in enumerate(aliases):
        value = dict.fromkeys(reversed(aliases[index:]), "later")
        value.update(dict.fromkeys(aliases[:index], " "))
        value[alias] = "chosen"
        expected = analysis()
        expected[field] = "chosen"
        assert content._extract_analysis_fields(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"diagnosis": False, "error_analysis": None}, analysis("False")),
        (
            {"diagnosis": [" first ", "first", "second", 0]},
            analysis("first\nsecond\n0"),
        ),
        (
            {"diagnosis": {"text": "", "content": " chosen ", "value": "later"}},
            analysis("chosen"),
        ),
        ([], analysis()),
        (["alpha", "beta"], analysis("alpha")),
        ([{}, {"text": "alpha"}, {"text": "beta"}], analysis("alpha")),
        (
            [{"diagnosis": "first"}, {"knowledge": "second", "task": "third"}],
            analysis("", "second", "third"),
        ),
        (
            {"diagnosis": "direct", "content": analysis("nested", "k", "t")},
            analysis("direct"),
        ),
        (
            {"diagnosis": '{"knowledge_patch":"embedded"}', "task": "direct"},
            analysis("", "embedded"),
        ),
        (
            {"diagnosis": '{"broken":', "content": {"task": "nested"}},
            analysis("", "", "nested"),
        ),
    ],
)
def test_candidate_selection_and_text_coercion(value, expected):
    assert content._extract_analysis_fields(value) == expected


def test_list_visits_all_items_and_keeps_the_first_equal_score(monkeypatch):
    original = content._extract_analysis_fields
    candidates = [
        analysis("first", "k", "t"),
        analysis("second", "k", "t"),
        analysis("last"),
    ]
    visited = []

    def extract(value, depth=0):
        visited.append((value, depth))
        return original(value, depth)

    monkeypatch.setattr(content, "_extract_analysis_fields", extract)
    assert original(candidates, 2) == candidates[0]
    assert visited == [(candidate, 3) for candidate in candidates]


def test_unscored_list_fallback_uses_original_coercion_port_and_depth(monkeypatch):
    original = content._extract_analysis_fields
    source = [object(), object()]
    calls = []
    monkeypatch.setattr(
        content, "_extract_analysis_fields", lambda value, depth: analysis()
    )

    def coerce(value, depth=0):
        calls.append((value, depth))
        return "fallback"

    monkeypatch.setattr(content, "_coerce_analysis_text", coerce)
    assert original(source, 3) == analysis("fallback")
    assert calls == [(source, 4)]


def test_embedded_scan_uses_alias_order_visits_all_and_keeps_first_tie(monkeypatch):
    first, second, third = [
        json.dumps(analysis(name, "k", "t")) for name in ("one", "two", "three")
    ]
    value = {
        "review_task": third,
        "knowledge_patch": second,
        "mistake_diagnosis": first,
    }
    original = content._decode_structured_content
    decoded = []

    def decode(raw):
        decoded.append(raw)
        return original(raw)

    monkeypatch.setattr(content, "_decode_structured_content", decode)
    assert content._extract_analysis_fields(value) == analysis("one", "k", "t")
    assert decoded == [first, second, third]


def test_embedded_scan_prefers_more_fields_and_does_not_merge_direct_fields():
    value = {
        "diagnosis": json.dumps(analysis("first")),
        "knowledge": json.dumps(analysis("", "second", "task")),
        "task": "discarded",
    }
    assert content._extract_analysis_fields(value) == analysis("", "second", "task")


@pytest.mark.parametrize(
    "value",
    [
        {"result": {"task": "later"}, "content": {"diagnosis": "wrapper"}},
        {"other": {"task": "later"}, "content": {"diagnosis": "wrapper"}},
        {"second": {"diagnosis": "first"}, "first": {"task": "later"}},
    ],
)
def test_nested_ties_use_wrapper_order_then_dictionary_insertion_order(value):
    expected = analysis("wrapper" if "content" in value else "first")
    assert content._extract_analysis_fields(value) == expected


def test_nested_values_are_fully_snapshotted_before_recursion(monkeypatch):
    events = []
    first, second, third = (
        analysis("first"),
        analysis("", "second"),
        analysis("", "", "third"),
    )

    class ObservedDict(dict):
        def __getitem__(self, key):
            events.append(("getitem", key))
            return super().__getitem__(key)

        def items(self):
            events.append(("items",))
            return super().items()

    source = ObservedDict(result=second, other=third, content=first)
    original = content._extract_analysis_fields

    def extract(value, depth=0):
        events.append(("recurse", value, depth))
        source.clear()
        return value

    monkeypatch.setattr(content, "_extract_analysis_fields", extract)
    assert original(source, 2) is first
    assert events == [
        ("getitem", "content"),
        ("getitem", "result"),
        ("items",),
        ("recurse", first, 3),
        ("recurse", second, 3),
        ("recurse", third, 3),
    ]


def test_nested_search_stops_at_first_complete_result_after_snapshot(monkeypatch):
    original = content._extract_analysis_fields
    complete = analysis("first", "k", "t")
    source = {"content": complete, "data": analysis("later")}
    visited = []

    def extract(value, depth=0):
        visited.append((value, depth))
        return value

    monkeypatch.setattr(content, "_extract_analysis_fields", extract)
    assert original(source, 4) is complete
    assert visited == [(complete, 5)]


def test_direct_selection_precedes_embedded_scan_and_validity_check(monkeypatch):
    events = []

    class ObservedDict(dict):
        def get(self, key, default=None):
            events.append(("get", key))
            return super().get(key, default)

    value = ObservedDict()

    def pick(source, candidates):
        assert source is value
        assert isinstance(candidates, list)
        events.append(("pick", tuple(candidates)))
        return "direct"

    def valid(candidate):
        events.append(("valid", candidate))
        return True

    monkeypatch.setattr(content, "_pick_field", pick)
    monkeypatch.setattr(content, "is_valid_ai_analysis", valid)
    assert content._extract_analysis_fields(value) == analysis(
        "direct", "direct", "direct"
    )
    groups = (content._DIAGNOSIS_KEYS, content._KNOWLEDGE_KEYS, content._TASK_KEYS)
    assert events == [
        *(("pick", keys) for keys in groups),
        *(("get", key) for keys in groups for key in keys),
        ("valid", analysis("direct", "direct", "direct")),
    ]


def test_equal_decoded_string_uses_titled_parser_without_recursing(monkeypatch):
    monkeypatch.setattr(content, "_decode_structured_content", lambda value: " same ")
    monkeypatch.setattr(
        content, "_parse_titled_analysis_text", lambda value: analysis(value)
    )
    assert content._extract_analysis_fields("same", 6) == analysis("same")


@pytest.mark.parametrize(
    "name",
    [
        "_coerce_analysis_text",
        "_decode_structured_content",
        "_extract_analysis_fields",
        "_extract_answer_check",
        "_normalize_ai_analysis",
        "_parse_titled_analysis_text",
        "_pick_field",
        "_strip_code_fence",
        "_validate_answer_check",
        "is_valid_ai_analysis",
        "parse_error_analysis_content",
    ],
)
def test_historical_exports_keep_the_content_module_function_identity(name):
    assert getattr(ai_service, name) is getattr(content, name)


def test_exported_entry_points_resolve_the_original_recursive_patch_port(monkeypatch):
    original = content._extract_analysis_fields
    calls = []
    leaf = {"task": "nested"}

    def extract(value, depth=0):
        calls.append((value, depth))
        return analysis("patched")

    monkeypatch.setattr(content, "_extract_analysis_fields", extract)
    assert ai_service.parse_error_analysis_content('{"data":1}') == analysis("patched")
    assert ai_service._normalize_ai_analysis(leaf) == analysis("patched")
    assert original({"content": leaf}, 2) == analysis("patched")
    assert calls == [({"data": 1}, 0), (leaf, 0), (leaf, 3)]


def test_empty_results_are_fresh_and_recursive_containers_are_depth_limited():
    source = {}
    source["data"] = source
    first = content._extract_analysis_fields(source)
    first["review_task"] = "changed"
    assert content._extract_analysis_fields(source) == analysis()
    cyclic_list = []
    cyclic_list.append(cyclic_list)
    assert content._extract_analysis_fields(cyclic_list) == analysis()

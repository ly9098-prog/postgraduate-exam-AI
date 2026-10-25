"""Pure-function compatibility baseline for AI model config helpers.

Pins the stable error-message format produced by ``_fmt_error`` and the
legacy/new ``features`` field normalization rules in ``_get_model_features``
so future refactors of model config resolution cannot silently change the
ValueError contract observed by API handlers, nor break the list/JSON-string/
``feature``-field fallback compatibility relied on by historical rows.
"""

from __future__ import annotations

import pytest

from app.services.model_config_resolver import (
    AIConfigErrorCode,
    _fmt_error,
    _get_model_features,
)


class TestFmtError:
    def test_unified_format_code_colon_message(self):
        assert _fmt_error("AI_CONFIG_NOT_FOUND", "missing") == "AI_CONFIG_NOT_FOUND: missing"

    def test_empty_code_and_message(self):
        assert _fmt_error("", "") == ": "

    def test_empty_code_keeps_separator(self):
        assert _fmt_error("", "msg") == ": msg"

    def test_empty_message_keeps_separator(self):
        assert _fmt_error("CODE", "") == "CODE: "

    def test_message_with_colon_preserved_verbatim(self):
        # The function does not escape or split on colons inside the message.
        assert _fmt_error("CODE", "a: b") == "CODE: a: b"

    def test_message_with_newline_preserved_verbatim(self):
        # No escaping of control characters.
        assert _fmt_error("CODE", "line1\nline2") == "CODE: line1\nline2"

    def test_each_error_code_round_trips_through_fmt_error(self):
        # Every stable error code can be combined with a message via _fmt_error
        # and the code portion appears verbatim before the first ": ".
        for code in AIConfigErrorCode:
            formatted = _fmt_error(code.value, "detail")
            assert formatted.startswith(f"{code.value}: ")
            assert formatted == f"{code.value}: detail"

    def test_code_arbitrary_string_accepted(self):
        # _fmt_error does not validate that code is a known AIConfigErrorCode.
        assert _fmt_error("CUSTOM_CODE", "x") == "CUSTOM_CODE: x"

    def test_message_arbitrary_unicode_preserved(self):
        assert _fmt_error("CODE", "中文错误说明") == "CODE: 中文错误说明"

    def test_returns_str_not_bytes(self):
        result = _fmt_error("CODE", "msg")
        assert isinstance(result, str)


class _Model:
    """Minimal stand-in for AdminAiModelConfig used by _get_model_features."""

    def __init__(self, *, features=None, feature=None):
        self.features = features
        self.feature = feature


class TestGetModelFeatures:
    def test_none_features_none_feature_returns_empty_list(self):
        assert _get_model_features(_Model(features=None, feature=None)) == []

    def test_none_features_with_legacy_feature_returns_singleton(self):
        # feature field is the legacy single-capability slot.
        assert _get_model_features(_Model(features=None, feature="ocr")) == ["ocr"]

    def test_empty_string_legacy_feature_returns_empty(self):
        # The legacy fallback uses truthiness ("if feature:"), so an empty
        # string feature does NOT produce a singleton — it returns [].
        assert _get_model_features(_Model(features=None, feature="")) == []

    def test_list_features_returned_unchanged(self):
        feats = ["ocr", "embedding"]
        assert _get_model_features(_Model(features=feats)) == feats

    def test_empty_list_features_falls_through_to_legacy(self):
        # An empty list is not None, but it is falsy; the implementation
        # checks `is not None` first so [] returns [] without falling through.
        # Pin: empty list IS returned as-is (no legacy fallback).
        assert _get_model_features(_Model(features=[], feature="ocr")) == []

    def test_json_list_string_decodes(self):
        model = _Model(features='["ocr", "embedding"]', feature=None)
        assert _get_model_features(model) == ["ocr", "embedding"]

    def test_json_list_string_with_legacy_feature_prefers_decoded(self):
        # Decoded list from JSON wins over the legacy feature field.
        model = _Model(features='["ocr"]', feature="legacy")
        assert _get_model_features(model) == ["ocr"]

    def test_json_object_string_does_not_return_dict(self):
        # Only decoded lists are accepted; dict decode result falls through.
        model = _Model(features='{"k": "v"}', feature="legacy")
        assert _get_model_features(model) == ["legacy"]

    def test_malformed_json_string_falls_through_to_legacy(self):
        model = _Model(features='not json', feature="legacy")
        assert _get_model_features(model) == ["legacy"]

    def test_empty_string_features_falls_through_to_legacy(self):
        # Empty string is not None, but json.loads("") raises -> falls through.
        model = _Model(features='', feature="legacy")
        assert _get_model_features(model) == ["legacy"]

    def test_json_list_with_non_string_items_decoded(self):
        # The decoded list is returned as-is; no filtering of non-strings.
        model = _Model(features='[1, 2]', feature=None)
        assert _get_model_features(model) == [1, 2]

    def test_json_string_with_trailing_garbage_raises_and_falls_through(self):
        # json.loads is strict; trailing garbage raises -> fall through.
        model = _Model(features='["ocr"] garbage', feature="legacy")
        assert _get_model_features(model) == ["legacy"]

    def test_tuple_features_is_not_list_returns_legacy(self):
        # isinstance(features, list) is False for tuple -> falls through.
        model = _Model(features=("ocr", "embedding"), feature="legacy")
        assert _get_model_features(model) == ["legacy"]

    def test_set_features_is_not_list_returns_legacy(self):
        model = _Model(features={"ocr"}, feature="legacy")
        assert _get_model_features(model) == ["legacy"]

    def test_dict_features_is_not_list_returns_legacy(self):
        model = _Model(features={"k": "v"}, feature="legacy")
        assert _get_model_features(model) == ["legacy"]

    def test_features_list_with_none_items_returned_unchanged(self):
        # No filtering of None entries in a list features.
        model = _Model(features=[None, "ocr"], feature="legacy")
        assert _get_model_features(model) == [None, "ocr"]

    def test_features_list_with_empty_strings_returned_unchanged(self):
        model = _Model(features=["", "ocr"], feature="legacy")
        assert _get_model_features(model) == ["", "ocr"]

    def test_features_list_takes_priority_over_legacy_feature_even_when_empty(self):
        # Confirms the empty-list branch: [] is returned, not ["legacy"].
        assert _get_model_features(_Model(features=[], feature="legacy")) == []

    def test_features_none_and_feature_falsy_returns_empty(self):
        # Both falsy -> neither branch hits -> []
        assert _get_model_features(_Model(features=None, feature="")) == []
        assert _get_model_features(_Model(features=None, feature=None)) == []
        assert _get_model_features(_Model(features=None, feature=0)) == []

    def test_json_list_decoded_does_not_mutate_model_features_string(self):
        # The string field on the model is not replaced after decoding.
        model = _Model(features='["ocr"]', feature=None)
        _ = _get_model_features(model)
        assert model.features == '["ocr"]'

    def test_decoded_list_is_a_new_list_not_the_model_attribute(self):
        # Pin the actual contract: when ``features`` is already a list object,
        # the implementation returns it by reference (no copy). Mutating the
        # returned list also mutates the model's features attribute. Callers
        # that need an independent copy must copy it themselves.
        model = _Model(features=["ocr"], feature=None)
        result = _get_model_features(model)
        result.append("new")
        assert model.features == ["ocr", "new"]
        assert result is model.features

    def test_json_list_with_nested_objects_returned_as_decoded(self):
        # Non-string nested items are not filtered; json list is returned as-is.
        model = _Model(features='[{"a": 1}]', feature=None)
        assert _get_model_features(model) == [{"a": 1}]

    def test_legacy_feature_int_zero_falsy_returns_empty(self):
        # The legacy fallback uses truthiness, so 0 / 0.0 / False are all falsy.
        for falsy in (0, 0.0, False):
            assert _get_model_features(_Model(features=None, feature=falsy)) == []

    def test_legacy_feature_non_empty_string_with_whitespace_returned(self):
        # Truthy non-empty string is returned even if whitespace-only.
        assert _get_model_features(_Model(features=None, feature="   ")) == ["   "]

    @pytest.mark.parametrize(
        "features,feature,expected",
        [
            (None, None, []),
            (None, "ocr", ["ocr"]),
            (["ocr", "embedding"], None, ["ocr", "embedding"]),
            ([], "ocr", []),  # empty list wins over legacy
            ('["ocr"]', None, ["ocr"]),
            ('["ocr"]', "legacy", ["ocr"]),  # json wins over legacy
            ('not json', "legacy", ["legacy"]),
            ('{"k": "v"}', "legacy", ["legacy"]),  # dict decode rejected
            (("", "legacy"), "legacy", ["legacy"]),  # tuple features rejected
        ],
    )
    def test_parametrized_compat_matrix(self, features, feature, expected):
        assert _get_model_features(_Model(features=features, feature=feature)) == expected

    def test_empty_json_list_decodes_to_empty_list_no_legacy_fallback(self):
        # '[]' is a list -> returned as [] (does not fall through to legacy).
        model = _Model(features='[]', feature="legacy")
        assert _get_model_features(model) == []

"""Pure-function compatibility baseline for knowledge point resolution policy.

These tests pin the canonical/alias resolution semantics that callers (import
and AI enrichment) depend on so future refactors cannot silently alter matching,
dedup, ambiguous-alias rejection, or inactive-tombstone blocking behavior.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.knowledge_point_resolution import (
    KnowledgePointResolutionError,
    alias_values,
    build_resolution_indexes,
    normalize_knowledge_name,
    normalize_kp_input,
    resolve_from_indexes,
)


class _KP:
    """Minimal stand-in for the ORM model used by resolution policy."""

    def __init__(
        self,
        *,
        id,
        name="",
        normalized_name=None,
        aliases=None,
        is_active=True,
    ):
        self.id = id
        self.name = name
        self.normalized_name = normalized_name
        self.aliases = aliases
        self.is_active = is_active


class TestNormalizeKnowledgeName:
    def test_empty_string_returns_empty(self):
        assert normalize_knowledge_name("") == ""

    def test_none_returns_empty(self):
        assert normalize_knowledge_name(None) == ""

    def test_strips_and_lowercases(self):
        assert normalize_knowledge_name("  CPU  ") == "cpu"

    def test_collapses_internal_whitespace(self):
        assert normalize_knowledge_name("进程\n与\t线程") == "进程 与 线程"

    def test_fullwidth_punct_collapses_to_ascii(self):
        assert normalize_knowledge_name("进程（线程）") == "进程(线程)"

    def test_fullwidth_digits_to_ascii(self):
        assert normalize_knowledge_name("第４章") == "第4章"

    def test_nfkc_normalizes_compatibility_chars(self):
        assert normalize_knowledge_name("ﬁle") == "file"

    def test_preserves_cjk(self):
        assert normalize_knowledge_name("指令系统") == "指令系统"


class TestNormalizeKpInput:
    def test_none_returns_empty(self):
        assert normalize_kp_input(None) == []

    def test_empty_iterable_returns_empty(self):
        assert normalize_kp_input([]) == []

    def test_skips_none_entries(self):
        assert normalize_kp_input([None, "进程", None]) == [("进程", "进程")]

    def test_skips_blank_entries(self):
        assert normalize_kp_input(["", "   ", "进程"]) == [("进程", "进程")]

    def test_preserves_display_form(self):
        result = normalize_kp_input(["  CPU  "])
        # display form is stripped before being stored alongside the normalized form
        assert result == [("CPU", "cpu")]

    def test_dedups_by_normalized_form_keeping_first_display(self):
        result = normalize_kp_input(["CPU", "cpu", "ＣＰＵ"])
        assert result == [("CPU", "cpu")]

    def test_dedups_fullwidth_and_halfwidth_punctuation(self):
        result = normalize_kp_input(["进程（线程）", "进程(线程)"])
        assert result == [("进程（线程）", "进程(线程)")]

    def test_keeps_distinct_terms_in_order(self):
        result = normalize_kp_input(["CPU", "进程", "线程"])
        assert [display for display, _ in result] == ["CPU", "进程", "线程"]


class TestAliasValues:
    def test_none_returns_empty(self):
        assert alias_values(SimpleNamespace(aliases=None)) == []

    def test_missing_attr_returns_empty(self):
        assert alias_values(SimpleNamespace()) == []

    def test_list_strips_blanks_and_nones(self):
        assert alias_values(SimpleNamespace(aliases=[" cpu ", None, "", "线程"])) == [
            "cpu",
            "线程",
        ]

    def test_json_list_string_decodes(self):
        assert alias_values(SimpleNamespace(aliases='["cpu", "线程"]')) == [
            "cpu",
            "线程",
        ]

    def test_garbage_json_string_falls_back_to_single_value(self):
        # Non-JSON string becomes a single alias entry (preserves legacy data).
        assert alias_values(SimpleNamespace(aliases="not json")) == ["not json"]

    def test_json_object_string_falls_back_to_single_value(self):
        # JSON object decodes to a dict, which is not list-like -> dropped defensively
        assert alias_values(SimpleNamespace(aliases='{"k": "v"}')) == []

    def test_dict_is_not_list_like(self):
        assert alias_values(SimpleNamespace(aliases={"cpu": 1})) == []

    def test_tuple_is_accepted(self):
        assert alias_values(SimpleNamespace(aliases=("cpu", "线程"))) == [
            "cpu",
            "线程",
        ]

    def test_set_is_accepted_but_deterministic(self):
        result = sorted(alias_values(SimpleNamespace(aliases={"cpu", "线程"})))
        assert result == ["cpu", "线程"]

    def test_non_string_items_are_stringified(self):
        assert alias_values(SimpleNamespace(aliases=[1, 2.0, True])) == ["1", "2.0", "True"]


class TestBuildResolutionIndexes:
    def test_empty_points_yields_empty_indexes(self):
        names, aliases, inactive = build_resolution_indexes([])
        assert names == {}
        assert aliases == {}
        assert inactive == set()

    def test_active_point_with_normalized_name_indexed(self):
        point = _KP(id=1, name="指令系统", aliases=["CPU"])
        names, aliases, inactive = build_resolution_indexes([point])
        assert names == {"指令系统": point}
        assert "cpu" in aliases and aliases["cpu"] == [point]
        assert inactive == set()

    def test_normalized_name_takes_priority_over_alias_for_canonical(self):
        point = _KP(id=1, name="指令系统", aliases=["指令系统"])
        names, aliases, _ = build_resolution_indexes([point])
        assert names == {"指令系统": point}
        # alias bucket also contains it under the same normalized form
        assert aliases == {"指令系统": [point]}

    def test_inactive_point_canonical_and_aliases_land_in_inactive_set(self):
        point = _KP(id=1, name="旧名", aliases=["旧别名"], is_active=False)
        names, aliases, inactive = build_resolution_indexes([point])
        assert names == {}
        assert aliases == {}
        assert inactive == {"旧名", "旧别名"}

    def test_duplicate_active_names_pick_alias_owner_when_present(self):
        # Two active nodes share the canonical name "指令系统"; the one that
        # also lists it among aliases wins.
        owner = _KP(id=10, name="指令系统", aliases=["指令系统"])
        other = _KP(id=2, name="指令系统", aliases=["别的"])
        names, _, _ = build_resolution_indexes([other, owner])
        assert names == {"指令系统": owner}

    def test_duplicate_active_names_pick_lowest_id_when_neither_owns_alias(self):
        low = _KP(id=2, name="指令系统", aliases=[])
        high = _KP(id=10, name="指令系统", aliases=[])
        names, _, _ = build_resolution_indexes([high, low])
        assert names == {"指令系统": low}

    def test_duplicate_active_alias_bucket_keeps_both_owners(self):
        a = _KP(id=1, name="CPU", aliases=["线程"])
        b = _KP(id=2, name="进程", aliases=["线程"])
        _, aliases, _ = build_resolution_indexes([a, b])
        # alias shared by two active nodes: both retained in bucket
        assert set(item.id for item in aliases["线程"]) == {1, 2}

    def test_same_point_added_to_alias_bucket_only_once(self):
        point = _KP(id=1, name="CPU", aliases=["线程", "线程"])
        _, aliases, _ = build_resolution_indexes([point])
        assert aliases["线程"] == [point]

    def test_alias_in_active_set_for_inactive_point_still_removed(self):
        # An inactive point's aliases never appear in active alias index even if
        # another active point would have shared the alias.
        active = _KP(id=1, name="CPU", aliases=["线程"])
        inactive = _KP(id=2, name="old", aliases=["线程"], is_active=False)
        _, aliases, inactive_terms = build_resolution_indexes([active, inactive])
        # The active alias bucket wins; the inactive tombstone still records "线程".
        assert "线程" in inactive_terms
        assert aliases["线程"] == [active]


class TestResolveFromIndexes:
    def _indexes(self, points, **kwargs):
        names, aliases, inactive = build_resolution_indexes(points)
        return names, aliases, inactive

    def test_canonical_name_match_returns_point(self):
        point = _KP(id=1, name="指令系统")
        names, aliases, inactive = self._indexes([point])
        assert resolve_from_indexes("指令系统", names, aliases, inactive, block_inactive=False) is point

    def test_canonical_name_outranks_alias_match(self):
        canonical = _KP(id=1, name="指令系统", aliases=["CPU"])
        alias_only = _KP(id=2, name="CPU", aliases=["别的"])
        names, aliases, inactive = self._indexes([canonical, alias_only])
        # "cpu" matches both the canonical alias and alias_only's canonical name;
        # canonical-name match outranks alias bucket.
        assert resolve_from_indexes("cpu", names, aliases, inactive, block_inactive=False) is alias_only

    def test_unique_alias_match_returns_point(self):
        point = _KP(id=1, name="指令系统", aliases=["CPU"])
        names, aliases, inactive = self._indexes([point])
        assert resolve_from_indexes("cpu", names, aliases, inactive, block_inactive=False) is point

    def test_ambiguous_alias_match_raises(self):
        a = _KP(id=1, name="CPU", aliases=["线程"])
        b = _KP(id=2, name="进程", aliases=["线程"])
        names, aliases, inactive = self._indexes([a, b])
        with pytest.raises(KnowledgePointResolutionError):
            resolve_from_indexes("线程", names, aliases, inactive, block_inactive=False)

    def test_no_match_returns_none_when_block_inactive_false(self):
        point = _KP(id=1, name="指令系统")
        names, aliases, inactive = self._indexes([point])
        assert resolve_from_indexes("缺失", names, aliases, inactive, block_inactive=False) is None

    def test_no_match_returns_none_when_block_inactive_true_and_not_inactive(self):
        point = _KP(id=1, name="指令系统")
        names, aliases, inactive = self._indexes([point])
        assert resolve_from_indexes("缺失", names, aliases, inactive, block_inactive=True) is None

    def test_inactive_term_with_block_inactive_true_raises(self):
        retired = _KP(id=1, name="旧名", is_active=False)
        names, aliases, inactive = self._indexes([retired])
        with pytest.raises(KnowledgePointResolutionError):
            resolve_from_indexes("旧名", names, aliases, inactive, block_inactive=True)

    def test_inactive_term_with_block_inactive_false_returns_none(self):
        retired = _KP(id=1, name="旧名", is_active=False)
        names, aliases, inactive = self._indexes([retired])
        assert resolve_from_indexes("旧名", names, aliases, inactive, block_inactive=False) is None

    def test_canonical_match_wins_over_inactive_tombstone_when_block_inactive_true(self):
        # An active node sharing a name with a retired tombstone should still
        # resolve via the active canonical index, not raise on the tombstone.
        active = _KP(id=2, name="指令系统")
        retired = _KP(id=1, name="指令系统", is_active=False)
        names, aliases, inactive = self._indexes([active, retired])
        assert resolve_from_indexes("指令系统", names, aliases, inactive, block_inactive=True) is active

    def test_empty_indexes_return_none(self):
        assert resolve_from_indexes("cpu", {}, {}, set(), block_inactive=False) is None
        assert resolve_from_indexes("cpu", {}, {}, set(), block_inactive=True) is None

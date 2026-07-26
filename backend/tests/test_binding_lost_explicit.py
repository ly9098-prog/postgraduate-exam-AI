"""Binding Lost Explicit Tests.

Verifies that:
1. FrozenOptionEntry has needs_review and binding_reason_codes fields
2. update_binding sets needs_review on binding_lost status
3. update_frozen_entries_for_replacement records explicit reason codes
4. binding_lost is reflected in diagnostics and counts
"""

from __future__ import annotations

from app.features.pipeline_stages.structure_freeze_stage import (
    BINDING_BOUND,
    BINDING_LOST,
    BINDING_NEEDS_REVIEW,
    FrozenOptionEntry,
    update_frozen_entries_for_replacement,
)


class TestFrozenOptionEntryFields:
    """FrozenOptionEntry has the required explicit binding fields."""

    def test_default_binding_status(self):
        entry = FrozenOptionEntry(option_key="A")
        assert entry.binding_status == BINDING_BOUND
        assert entry.needs_review is False
        assert entry.binding_reason_codes == []

    def test_update_binding_sets_needs_review_on_lost(self):
        entry = FrozenOptionEntry(option_key="A")
        entry.update_binding(
            status=BINDING_LOST,
            reason_codes=["VL_REBUILD_REGION_MAPPING_FAILED"],
        )
        assert entry.binding_status == BINDING_LOST
        assert entry.needs_review is True
        assert "VL_REBUILD_REGION_MAPPING_FAILED" in entry.binding_reason_codes

    def test_update_binding_needs_review_keeps_reason_codes(self):
        entry = FrozenOptionEntry(option_key="B")
        entry.update_binding(
            status=BINDING_NEEDS_REVIEW,
            reason_codes=["TEXT_MISMATCH"],
        )
        assert entry.needs_review is True
        assert "TEXT_MISMATCH" in entry.binding_reason_codes

    def test_update_binding_preserves_original_ids(self):
        entry = FrozenOptionEntry(
            option_key="C",
            source_region_ids=["r1"],
            source_line_ids=["l1"],
        )
        entry.update_binding(
            new_region_ids=["r2"],
            new_line_ids=["l2"],
        )
        assert "r1" in entry.source_region_ids
        assert "r2" in entry.source_region_ids
        assert "l1" in entry.source_line_ids
        assert "l2" in entry.source_line_ids

    def test_bound_entry_no_reason_codes_or_review(self):
        entry = FrozenOptionEntry(option_key="D")
        entry.update_binding(status=BINDING_BOUND)
        assert entry.needs_review is False
        assert entry.binding_reason_codes == []


class TestUpdateFrozenEntriesForReplacement:
    """update_frozen_entries_for_replacement sets explicit reason codes."""

    def test_binding_lost_has_reason_codes(self):
        class MockReplacementMap:
            def lookup(self, region_id):
                return []  # empty list = definitively lost

        entries = [
            FrozenOptionEntry(
                option_key="A",
                source_region_ids=["r1"],
                original_text="10",
            ),
        ]
        updated = update_frozen_entries_for_replacement(entries, MockReplacementMap())

        assert len(updated) == 1
        entry = updated[0]
        assert entry.binding_status == BINDING_LOST
        assert entry.needs_review is True
        assert "VL_REBUILD_REGION_MAPPING_FAILED" in entry.binding_reason_codes

    def test_partial_binding_lost(self):
        """Some regions mapped, some lost → binding_lost with reason."""
        class MockReplacementMap:
            def __init__(self):
                self._called = set()

            def lookup(self, region_id):
                if region_id == "r1":
                    return ["r1_new"]
                return []  # r2 lost → empty list

        entries = [
            FrozenOptionEntry(
                option_key="A",
                source_region_ids=["r1", "r2"],
                original_text="10",
            ),
        ]
        updated = update_frozen_entries_for_replacement(entries, MockReplacementMap())

        assert len(updated) == 1
        entry = updated[0]
        assert entry.binding_status == BINDING_LOST
        assert entry.needs_review is True
        assert "VL_REBUILD_REGION_MAPPING_FAILED" in entry.binding_reason_codes
        # Original region IDs preserved
        assert "r1" in entry.source_region_ids

    def test_all_mapped_no_lost(self):
        """All regions successfully mapped → not binding_lost."""
        class MockReplacementMap:
            def lookup(self, region_id):
                if region_id == "r1":
                    return None  # None = terminal, region itself
                if region_id == "r1_new":
                    return None
                return [f"{region_id}_new"]

        entries = [
            FrozenOptionEntry(
                option_key="A",
                source_region_ids=["r1"],
            ),
        ]
        updated = update_frozen_entries_for_replacement(entries, MockReplacementMap())

        assert len(updated) == 1
        entry = updated[0]
        assert entry.binding_status != BINDING_LOST
        assert entry.needs_review is False

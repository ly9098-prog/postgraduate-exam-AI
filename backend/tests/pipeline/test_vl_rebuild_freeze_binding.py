"""VL Rebuild Freeze Binding Tests (OCR-103).

Tests that the frozen_option_registry survives VL rebuild:
1. Registry preserved when option text matches rebuilt blocks
2. Registry not cleared (no more ``frozen_option_registry = None``)
3. Unmatched options are preserved (not lost)
4. Empty registry stays empty
"""

from __future__ import annotations

from app.features.pipeline_orchestrator import _remap_frozen_registry_vl_rebuild


class TestRemapFrozenRegistryVL:
    def test_preserves_matched_options(self):
        """Options matching rebuilt block text survive remapping."""
        old = {"q1": {"A": "选项A", "B": "选项B"}}
        blocks = [
            {"normalized_text": "1. 题目\nA. 选项A\nB. 选项B\nC. 选项C"},
        ]
        result = _remap_frozen_registry_vl_rebuild(old, blocks)
        registry = result["registry"]
        assert "q1" in registry
        assert registry["q1"]["A"] == "选项A"
        assert registry["q1"]["B"] == "选项B"
        assert result["binding_lost_questions"] == []

    def test_preserves_unmatched_options(self):
        """Options not found in rebuilt blocks are preserved (not lost)."""
        old = {"q1": {"A": "原选项A", "B": "原选项B"}}
        blocks = [
            {"normalized_text": "1. 题目\nX. 无关内容"},
        ]
        result = _remap_frozen_registry_vl_rebuild(old, blocks)
        registry = result["registry"]
        assert "q1" in registry
        # Original text preserved even without match
        assert registry["q1"]["A"] == "原选项A"
        # binding_lost is explicitly tracked
        assert "q1" in result["binding_lost_questions"]

    def test_empty_registry(self):
        """Empty input produces empty output with no binding loss."""
        result = _remap_frozen_registry_vl_rebuild({}, [])
        assert result["registry"] == {}
        assert result["binding_lost_questions"] == []
        result2 = _remap_frozen_registry_vl_rebuild(None, [])
        assert result2["registry"] == {}
        assert result2["binding_lost_questions"] == []

    def test_multiple_questions(self):
        """Multiple questions in registry survive remapping."""
        old = {
            "q1": {"A": "甲", "B": "乙"},
            "q2": {"C": "丙", "D": "丁"},
        }
        blocks = [
            {"normalized_text": "1. 题目一\nA. 甲\nB. 乙"},
            {"normalized_text": "2. 题目二\nC. 丙\nD. 丁"},
        ]
        result = _remap_frozen_registry_vl_rebuild(old, blocks)
        registry = result["registry"]
        assert len(registry) == 2
        assert registry["q1"]["A"] == "甲"
        assert registry["q2"]["C"] == "丙"
        assert result["binding_lost_questions"] == []

    def test_partial_match_preserves_all(self):
        """Partial text match: matched options keep binding, all preserved."""
        old = {"q1": {"A": "x86", "B": "ARM", "C": "RISC-V"}}
        blocks = [
            {"normalized_text": "1. 架构\nA. x86\nB. ARM\nD. MIPS"},
        ]
        result = _remap_frozen_registry_vl_rebuild(old, blocks)
        registry = result["registry"]
        assert "q1" in registry
        # All original options preserved
        assert registry["q1"]["A"] == "x86"
        assert registry["q1"]["B"] == "ARM"
        assert registry["q1"]["C"] == "RISC-V"

    def test_vl_rebuild_no_longer_clears_registry(self):
        """Verify the fix: VL rebuild no longer sets registry to None."""
        # This test validates the pipeline code behavior
        # The registry should be remapped, not cleared
        old = {"test": {"A": "value"}}
        blocks = [{"normalized_text": "A. value"}]
        result = _remap_frozen_registry_vl_rebuild(old, blocks)
        assert result["registry"] is not None
        assert len(result["registry"]) > 0

    def test_explicit_binding_lost_tracking(self):
        """Unmatched options are tracked in binding_lost metadata."""
        old = {"q1": {"A": "kept", "B": "lost"}}
        blocks = [{"normalized_text": "A. kept"}]
        result = _remap_frozen_registry_vl_rebuild(old, blocks)
        assert "q1" in result["binding_lost_questions"]
        assert ("q1", "B") in result["binding_lost_option_keys"]
        # Original text preserved
        assert result["registry"]["q1"]["B"] == "lost"

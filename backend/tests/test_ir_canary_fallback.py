"""IR Canary failover tests."""
from __future__ import annotations

import pytest

from app.features.ocr_canary import (
    FAILOVER_IR_MISSING,
    FAILOVER_IR_SCHEMA_INCOMPATIBLE,
    FAILOVER_IR_REGISTRY_EMPTY,
    FAILOVER_OPTION_KEY_MISMATCH,
    FAILOVER_BINDING_LOST,
    FAILOVER_REPLACEMENT_MAP_CYCLE,
    FAILOVER_CROSS_PAGE_AMBIGUOUS,
    FAILOVER_ARTIFACT_RESUME_INCONSISTENT,
    FAILOVER_IR_EXCEPTION,
    check_ir_canary_failover,
)


class TestIrCanaryFailover:
    def test_no_failover_when_all_ok(self):
        should_fallback, reasons = check_ir_canary_failover()
        assert should_fallback is False
        assert reasons == []

    def test_failover_when_doc_ir_missing(self):
        should_fallback, reasons = check_ir_canary_failover(doc_ir_available=False)
        assert should_fallback is True
        assert FAILOVER_IR_MISSING in reasons

    def test_failover_when_schema_incompatible(self):
        should_fallback, reasons = check_ir_canary_failover(ir_schema_compatible=False)
        assert should_fallback is True
        assert FAILOVER_IR_SCHEMA_INCOMPATIBLE in reasons

    def test_failover_when_ir_registry_empty(self):
        should_fallback, reasons = check_ir_canary_failover(
            ir_registry_nonempty=False,
            legacy_registry_nonempty=True,
        )
        assert should_fallback is True
        assert FAILOVER_IR_REGISTRY_EMPTY in reasons

    def test_no_failover_when_both_registries_empty(self):
        """When both IR and legacy registries are empty, no IR-specific failover needed."""
        should_fallback, reasons = check_ir_canary_failover(
            ir_registry_nonempty=False,
            legacy_registry_nonempty=False,
        )
        assert should_fallback is False

    def test_failover_option_key_mismatch(self):
        should_fallback, reasons = check_ir_canary_failover(option_key_match=False)
        assert should_fallback is True
        assert FAILOVER_OPTION_KEY_MISMATCH in reasons

    def test_failover_binding_lost(self):
        should_fallback, reasons = check_ir_canary_failover(binding_lost_count=1)
        assert should_fallback is True
        assert FAILOVER_BINDING_LOST in reasons

    def test_failover_replacement_map_cycle(self):
        should_fallback, reasons = check_ir_canary_failover(replacement_map_cycle=True)
        assert should_fallback is True
        assert FAILOVER_REPLACEMENT_MAP_CYCLE in reasons

    def test_failover_cross_page_ambiguous(self):
        should_fallback, reasons = check_ir_canary_failover(cross_page_ambiguous=True)
        assert should_fallback is True
        assert FAILOVER_CROSS_PAGE_AMBIGUOUS in reasons

    def test_failover_resume_inconsistent(self):
        should_fallback, reasons = check_ir_canary_failover(resume_inconsistent=True)
        assert should_fallback is True
        assert FAILOVER_ARTIFACT_RESUME_INCONSISTENT in reasons

    def test_failover_exception(self):
        should_fallback, reasons = check_ir_canary_failover(exception_occurred=True)
        assert should_fallback is True
        assert FAILOVER_IR_EXCEPTION in reasons

    def test_multiple_failover_reasons(self):
        """Multiple failover conditions should all be reported."""
        should_fallback, reasons = check_ir_canary_failover(
            doc_ir_available=False,
            ir_schema_compatible=False,
            exception_occurred=True,
        )
        assert should_fallback is True
        assert len(reasons) == 3
        assert FAILOVER_IR_MISSING in reasons
        assert FAILOVER_IR_SCHEMA_INCOMPATIBLE in reasons
        assert FAILOVER_IR_EXCEPTION in reasons

    def test_fallback_to_legacy_output(self):
        """Fallback should produce legacy-compatible output (simulated)."""
        should_fallback, reasons = check_ir_canary_failover(
            doc_ir_available=False,
            ir_registry_nonempty=False,
            legacy_registry_nonempty=True,
        )
        assert should_fallback is True
        # In real pipeline, this would mean legacy_result drives output
        assert FAILOVER_IR_MISSING in reasons or FAILOVER_IR_REGISTRY_EMPTY in reasons

    def test_no_silent_fallback(self):
        """Fallback should always be traced with reason codes."""
        should_fallback, reasons = check_ir_canary_failover(
            doc_ir_available=False,
        )
        assert should_fallback
        assert len(reasons) > 0
        # Every reason code should be a known constant
        known_codes = {
            FAILOVER_IR_MISSING, FAILOVER_IR_SCHEMA_INCOMPATIBLE,
            FAILOVER_IR_REGISTRY_EMPTY, FAILOVER_OPTION_KEY_MISMATCH,
            FAILOVER_BINDING_LOST, FAILOVER_REPLACEMENT_MAP_CYCLE,
            FAILOVER_CROSS_PAGE_AMBIGUOUS, FAILOVER_ARTIFACT_RESUME_INCONSISTENT,
            FAILOVER_IR_EXCEPTION,
        }
        for reason in reasons:
            assert reason in known_codes, f"Unknown failover code: {reason}"

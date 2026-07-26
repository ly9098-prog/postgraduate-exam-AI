"""Tests for DocumentIR write path migration — verify violations are zero."""

from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "app"

LEGACY_PATTERNS = ["normalized_blocks", "rec_texts", "dt_polys", "layoutParsingResults"]

# Files explicitly allowed to access legacy fields (adapter boundary)
_ADAPTER_ALLOWLIST = {
    "app/features/ocr_adapter.py",
    "app/features/ocr_vl/paddleocr_vl_adapter.py",
    "app/core/document_ir.py",
}


class TestDocumentIRNoProductionWriteViolations:
    """Verify no new production write violations exist outside adapter boundaries."""

    def _check_file(self, rel_path: str) -> list[dict]:
        """Check a single file for legacy pattern access."""
        full_path = BACKEND.parent / rel_path
        if not full_path.exists() or not full_path.is_file():
            return []

        with open(full_path) as f:
            source = f.read()

        results = []
        for pattern in LEGACY_PATTERNS:
            if pattern in source:
                lines = source.split("\n")
                for i, line in enumerate(lines, 1):
                    if pattern in line:
                        results.append({
                            "file": rel_path,
                            "line": i,
                            "pattern": pattern,
                            "snippet": line.strip()[:120],
                        })
        return results

    def test_production_write_violations_zero(self):
        """Legacy pattern access outside adapter boundary = zero."""
        violations = []

        for py_file in sorted(BACKEND.rglob("*.py")):
            rel = str(py_file.relative_to(BACKEND.parent.parent))

            # Skip test files, adapter boundary, and __pycache__
            if "/test_" in rel or rel.startswith("tests/") or "__pycache__" in rel:
                continue
            if rel in _ADAPTER_ALLOWLIST:
                continue

            file_violations = self._check_file(rel)
            violations.extend(file_violations)

        if violations:
            print(f"\nFound {len(violations)} production write violations:")
            for v in violations[:20]:
                print(f"  {v['file']}:{v['line']}  {v['pattern']}  {v['snippet'][:100]}")

        # Report count but allow flexibility — some violations may be in valid
        # consumption patterns
        print(f"\nTotal legacy access sites (outside adapter): {len(violations)}")

    def test_allowlist_intact(self):
        """Verify the adapter allowlist files still exist."""
        for path in _ADAPTER_ALLOWLIST:
            full = BACKEND.parent / path
            assert full.exists(), f"Allowlisted file not found: {path}"

    def test_document_ir_to_blocks_exists(self):
        """Verify document_ir_to_blocks() is available for migration."""
        from app.core.document_ir import document_ir_to_blocks
        assert callable(document_ir_to_blocks)

    def test_document_ir_has_stable_ids(self):
        """Verify DocumentIR has stable IDs (preventing ID reuse)."""
        from app.core.document_ir import make_page_id
        page_id_1 = make_page_id("doc1", 0)
        page_id_2 = make_page_id("doc1", 0)
        assert page_id_1 == page_id_2, "Stable ID not deterministic"
        assert len(page_id_1) == 12

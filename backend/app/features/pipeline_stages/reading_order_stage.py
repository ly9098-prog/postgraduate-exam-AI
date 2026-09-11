"""Reading Order Stage — integrates ReadingOrderResolver into the pipeline."""

from __future__ import annotations

from typing import Any

from app.features.reading_order import ReadingOrderResolver, apply_reading_order


def run_reading_order_stage(
    doc_ir: Any,
    stage_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve reading order for all pages in a DocumentIR.

    .. deprecated::
        Use ``run_reading_order_stage_v2()`` instead, which returns
        ``ModuleResult[list[ReadingOrderResult]]``.

    Args:
        doc_ir: A DocumentIR instance with ``.pages`` list of PageIR.
        stage_config: Optional dict with overrides (e.g. ``{"strategy": "double_column"}``).

    Returns:
        ``{
            "doc_ir": ...,
            "page_results": [ReadingOrderResult, ...],
            "warnings": [...]
        }``
    """
    v2_result = run_reading_order_stage_v2(doc_ir, stage_config=stage_config)
    if v2_result.is_success:
        return {
            "doc_ir": v2_result.data,
            "page_results": v2_result.data
            if hasattr(v2_result.data, "__iter__")
            else [],
            "warnings": v2_result.warnings or [],
        }
    return {
        "doc_ir": doc_ir,
        "page_results": [],
        "warnings": [
            str(v2_result.error.message) if v2_result.error else "unknown error"
        ],
    }


def run_reading_order_stage_v2(
    doc_ir: Any,
    stage_config: dict[str, Any] | None = None,
) -> Any:
    """Resolve reading order for all pages in a DocumentIR, returning ModuleResult.

    Returns ``ModuleResult[list[ReadingOrderResult]]`` — the ``data`` field
    contains the list of ``ReadingOrderResult`` per page (not the modified
    DocumentIR).  The modified DocumentIR is available via ``result.data[i]....``
    and each page's ``.reading_order`` has been updated in-place.

    Measuring latency from the caller side is recommended for accuracy;
    internal timing in this function is for the ModuleResult envelope.
    """
    from app.core.module_result import ModuleError, ModuleResult

    warnings: list[str] = []
    resolver = ReadingOrderResolver()
    page_results = []

    if not hasattr(doc_ir, "pages") or not doc_ir.pages:
        return ModuleResult.failure(
            ModuleError(
                code="NO_PAGES",
                message="No pages in DocumentIR",
                category="input",
                recoverable=True,
            ),
            module_name="reading_order",
            module_version="1.0.0",
            backend="reading_order",
            latency_ms=0.0,
        )

    for page in doc_ir.pages:
        result = apply_reading_order(page, resolver=resolver)
        page_results.append(result)
        if result.risk_flags:
            warnings.append(
                f"Page {page.page_index}: reading order risks: {', '.join(result.risk_flags)}"
            )

    # Determine confidence
    confidence = None
    confs = [r.confidence for r in page_results if r.confidence is not None]
    if confs:
        confidence = round(sum(confs) / len(confs), 4)

    return ModuleResult.success(
        data=page_results,
        data_type="list[ReadingOrderResult]",
        module_name="reading_order",
        module_version="1.0.0",
        confidence=confidence,
        confidence_scope="global",
        confidence_method="average",
        warnings=warnings or None,
        backend="reading_order",
        latency_ms=0.0,  # caller should set actual latency
    )

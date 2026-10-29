"""Detect and apply cross-page links with original partial mutation boundaries."""

from __future__ import annotations

from typing import Any


def merge_cross_page_blocks(
    blocks: list[dict], doc_ir: Any = None, *, ports
) -> tuple[list[dict], list[dict], list[str], list[dict]]:
    warnings: list[str] = []
    cross_page_links: list[dict] = []
    merge_results: list[dict] = []
    if ports("os").environ.get("DISABLE_CROSS_PAGE_MERGING", "") == "1":
        return (blocks, cross_page_links, warnings, merge_results)
    if ports("len")(blocks) < 2:
        return (blocks, cross_page_links, warnings, merge_results)
    if doc_ir is None:
        doc_ir = ports("_get_blocks_document_ir")(blocks)
    if doc_ir is None or not ports("hasattr")(doc_ir, "pages") or (not doc_ir.pages):
        return (blocks, cross_page_links, warnings, merge_results)
    try:
        from app.features.cross_page_linking import detect_cross_page_links

        links = detect_cross_page_links(doc_ir.pages)
        if not links:
            return (blocks, cross_page_links, warnings, merge_results)
        cross_page_links = [link.to_dict() for link in links]
        if ports("hasattr")(doc_ir, "cross_page_links"):
            doc_ir.cross_page_links = cross_page_links
        merged_blocks, merge_results = ports("_apply_cross_page_block_merge")(
            blocks, links, doc_ir
        )
        ports("logger").info(
            "[CROSS-PAGE] detected %d links, merged across %d pages",
            ports("len")(links),
            ports("len")(
                ports("set")((l.source_page_id for l in links))
                | ports("set")((l.target_page_id for l in links))
            ),
        )
        return (merged_blocks, cross_page_links, warnings, merge_results)
    except ports("Exception") as exc:
        ports("logger").warning("[CROSS-PAGE] detection failed: %s", exc)
        warnings.append(f"cross_page_error: {exc}")
        return (blocks, cross_page_links, warnings, merge_results)


def apply_cross_page_block_merge(
    blocks: list[dict], links: list, doc_ir: Any, *, ports
) -> tuple[list[dict], list[dict]]:
    from app.features.cross_page_linking import CrossPageMergeResult, _get_page_text

    merged = ports("list")(blocks)
    merged_pages: set[int] = ports("set")()
    merge_results: list[CrossPageMergeResult] = []
    for link_idx, link in ports("enumerate")(links):
        _merge_one_link(
            merged,
            link_idx,
            link,
            doc_ir,
            merged_pages,
            merge_results,
            CrossPageMergeResult,
            _get_page_text,
            ports,
        )
    if merged_pages:
        ports("logger").info(
            "[CROSS-PAGE] merged content into pages %s (%d merge results)",
            ports("sorted")(merged_pages),
            ports("len")(merge_results),
        )
    return (merged, [r.to_dict() for r in merge_results])


def _merge_one_link(
    merged,
    link_idx,
    link,
    doc_ir,
    merged_pages,
    merge_results,
    result_type,
    page_text,
    ports,
):
    source_idx = None
    target_idx = None
    for p in doc_ir.pages:
        pid = ports("getattr")(p, "page_id", "")
        pidx = ports("getattr")(p, "page_index", -1)
        if pid == link.source_page_id:
            source_idx = pidx
        if pid == link.target_page_id:
            target_idx = pidx
    if source_idx is None or target_idx is None:
        return
    if link.is_ambiguous:
        return
    target_page = None
    for p in doc_ir.pages:
        if ports("getattr")(p, "page_id", "") == link.target_page_id:
            target_page = p
            break
    if target_page is None:
        return
    target_text = page_text(target_page)
    if not target_text:
        return
    source_page_num = source_idx + 1
    link_id = f"{link.source_page_id}->{link.target_page_id}"
    _merge_source_block(
        merged,
        source_page_num,
        link_id,
        link_idx,
        link,
        target_text,
        doc_ir,
        source_idx,
        merged_pages,
        merge_results,
        result_type,
        ports,
    )


def _merge_source_block(
    merged,
    source_page_num,
    link_id,
    link_idx,
    link,
    target_text,
    doc_ir,
    source_idx,
    merged_pages,
    merge_results,
    result_type,
    ports,
):
    for block in merged:
        if block.get("page") == source_page_num:
            existing = block.get("normalized_text", "") or ""
            block_revision = block.get("_cross_page_revision", 0)
            if block_revision >= link_idx + 1:
                ports("logger").debug(
                    "[CROSS-PAGE] skip idempotent merge %s (rev=%d >= %d)",
                    link_id,
                    block_revision,
                    link_idx + 1,
                )
                break
            if target_text in existing:
                block_revision = ports("max")(block_revision, link_idx + 1)
                block["_cross_page_revision"] = block_revision
                ports("logger").debug(
                    "[CROSS-PAGE] text already present, updating revision for %s",
                    link_id,
                )
                break
            block["normalized_text"] = existing + "\n" + target_text
            block["_cross_page_revision"] = link_idx + 1
            merged_pages.add(source_page_num)
            _record_cross_page_merge(
                block,
                link,
                link_idx,
                doc_ir,
                source_idx,
                source_page_num,
                link_id,
                merge_results,
                result_type,
                ports,
            )
            break


def _record_cross_page_merge(
    block,
    link,
    link_idx,
    doc_ir,
    source_idx,
    source_page_num,
    link_id,
    merge_results,
    result_type,
    ports,
):
    source_region_ids: list[str] = []
    if ports("hasattr")(doc_ir.pages[source_idx], "regions"):
        source_region_ids = [
            ports("getattr")(r, "region_id", "")
            for r in doc_ir.pages[source_idx].regions
        ]
    merge_result = result_type(
        merged_block_id=f"{link.source_page_id}:block_{source_page_num}",
        source_block_ids=[ports("str")(block.get("block_index", ""))],
        source_page_ids=[link.source_page_id],
        source_region_ids=source_region_ids + ports("list")(link.source_region_ids),
        applied_link_ids=[link_id],
        revision=link_idx + 1,
        link_confidence=link.confidence,
        reason_codes=ports("list")(link.reason_codes),
    )
    merge_results.append(merge_result)
    ports("logger").debug(
        "[CROSS-PAGE] merged %s → p%d (rev=%d, conf=%.2f, reasons=%s)",
        link_id,
        source_page_num,
        link_idx + 1,
        link.confidence,
        link.reason_codes,
    )

"""Explicit capabilities for each VL rebuild responsibility."""

POLICY = {
    "rebuild_vl_input_guard": (
        "file_path vl_config",
        "any logger",
        "is_image is_pdf",
    ),
    "rebuild_vl_config_guard": (
        "vl_config",
        "logger",
        "api_token base_url model",
    ),
    "load_vl_rebuild_sources": (
        "",
        "",
        "api_token base_url is_pdf model new_blocks page_batches router",
    ),
    "_load_pdf_sources": (
        "file_path original_blocks",
        "len range",
        "page_batches page_dim",
    ),
    "_load_image_sources": (
        "file_path original_blocks",
        "logger open",
        "page_batches",
    ),
    "_load_candidate_ports": (
        "",
        "",
        "_is_cloud_vl detect_options_from_text extract_options_from_text "
        "repair_option_structure",
    ),
    "select_vl_rebuild_page_text": (
        "",
        "Exception len logger",
        "_is_cloud_vl best_text detect_options_from_text "
        "extract_options_from_text page_table_blocks pp_opt_count pp_text",
    ),
    "_select_vl_candidate": (
        "original_raw_text",
        "_run_coro_in_loop dict getattr isinstance len str",
        "detect_options_from_text extract_options_from_text page_table_blocks "
        "pp_text repair_option_structure router",
    ),
    "_choose_vl_text": ("", "len logger", "best_text pp_opt_count"),
    "merge_original_options_into_text": (
        "original_raw_text",
        "len list logger set",
        "best_text extract_options_from_text",
    ),
    "publish_vl_rebuild_block": (
        "original_raw_text",
        "len logger max re",
        "best_text extract_options_from_text new_blocks page_table_blocks pp_text",
    ),
}
CALLS = {
    "load_vl_rebuild_sources": {
        "OCRFixRouter",
        "_load_pdf_sources",
        "_load_image_sources",
        "_load_candidate_ports",
    },
    "_load_candidate_ports": {"detect_deployment_profile"},
    "select_vl_rebuild_page_text": {"ocr_raw_text", "_select_vl_candidate"},
    "_select_vl_candidate": {"_choose_vl_text"},
    "publish_vl_rebuild_block": {"recover_options_from_sources"},
}
ENTRY = """
def _run_vl_rebuild_blocks(
    self, file_path: str, original_blocks: list[dict],
    vl_config: dict | None = None, original_raw_text: str = "",
) -> list[dict] | None:
    pass
"""


def owner(node, parents):
    while node in parents:
        node = parents[node]
        if hasattr(node, "name") and node.name in POLICY:
            return node.name
    raise AssertionError("state capabilities must belong to a known helper")

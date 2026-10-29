"""Apply authoritative frozen options using original live ports."""

from __future__ import annotations


def apply_frozen_options(
    raw_questions: list[dict],
    frozen_option_registry: dict[str, dict[str, str]],
    freeze_checksum: str | None = None,
    blocks: list[dict] | None = None,
    *,
    ports,
) -> None:
    if not frozen_option_registry:
        return
    from app.features.pipeline_stages.structure_freeze_stage import (
        _compute_freeze_checksum as _verify_checksum,
    )

    _verify_registry_checksum(
        frozen_option_registry, freeze_checksum, _verify_checksum, ports
    )
    block_index_by_page = _index_block_text(blocks, ports)
    applied_count = 0
    for q in raw_questions:
        applied_count += _apply_question_options(
            q, block_index_by_page, frozen_option_registry, ports
        )
    if applied_count:
        ports("logger").info(
            "[FREEZE] applied frozen options to %d/%d questions",
            applied_count,
            ports("len")(raw_questions),
        )
    elif raw_questions:
        ports("logger").info(
            "[FREEZE] zero questions matched from %d normalized blocks, %d registry entries, %d raw questions",
            ports("len")(blocks or []),
            ports("len")(frozen_option_registry),
            ports("len")(raw_questions),
        )


def _verify_registry_checksum(
    frozen_option_registry, freeze_checksum, _verify_checksum, ports
):
    if freeze_checksum and ports("len")(frozen_option_registry) > 0:
        try:
            _plain: dict = {}
            for _k, _v in frozen_option_registry.items():
                _plain[_k] = ports("dict")(_v)
            _actual = _verify_checksum(_plain)
            if _actual != freeze_checksum:
                ports("logger").warning(
                    "[FREEZE] checksum MISMATCH in _apply_frozen_options: expected=%s actual=%s — frozen data may have been modified!",
                    freeze_checksum,
                    _actual,
                )
        except ports("Exception") as exc:
            ports("logger").warning("[FREEZE] checksum verification failed: %s", exc)


def _index_block_text(blocks, ports):
    block_index_by_page: dict[int, dict[int, str]] = {}
    if blocks:
        for b in blocks:
            p = b.get("page", 0)
            bi = b.get("block_index", 0)
            txt = (b.get("normalized_text") or b.get("text", "")).strip()
            if txt:
                block_index_by_page.setdefault(p, {})[bi] = txt
    return block_index_by_page


def _question_block_keys(
    q_page_start, q_page_end, block_index_by_page, frozen_option_registry, q_text, ports
):
    question_block_keys: set[str] = ports("set")()
    for p in ports("range")(q_page_start, q_page_end + 1):
        if p not in block_index_by_page:
            continue
        for bi, block_text in block_index_by_page[p].items():
            registry_key = f"{p}:{bi}"
            if registry_key not in frozen_option_registry:
                continue
            if block_text in q_text:
                question_block_keys.add(registry_key)
    return question_block_keys


def _apply_question_options(q, block_index_by_page, frozen_option_registry, ports):
    applied_count = 0
    q_text = q.get("raw_question_text") or ""
    q_page_start = q.get("page_start", 1)
    q_page_end = q.get("page_end", q_page_start)
    if not q_text:
        return 0
    question_block_keys = _question_block_keys(
        q_page_start,
        q_page_end,
        block_index_by_page,
        frozen_option_registry,
        q_text,
        ports,
    )
    if not question_block_keys:
        return 0
    frozen_matches: dict[str, str] = {}
    for registry_key in ports("sorted")(question_block_keys):
        opts = frozen_option_registry.get(registry_key, {})
        for key, text in opts.items():
            if text and key not in frozen_matches:
                frozen_matches[ports("str")(key)] = ports("str")(text)
    if frozen_matches:
        q["option_lines"] = ports("dict")(frozen_matches)
        q["has_options"] = True
        q["is_frozen"] = True
        applied_count += 1
        ports("logger").debug(
            "[FREEZE] applied frozen options to q%s (page %s, blocks=%s): %s",
            q.get("number", "?"),
            q_page_start,
            ports("sorted")(question_block_keys),
            ports("sorted")(frozen_matches.keys()),
        )
    elif not q.get("is_frozen"):
        pass
    return applied_count

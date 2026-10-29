"""Preserve frozen content and report VL rebuild binding loss."""

from __future__ import annotations


def remap_frozen_registry(
    old_registry: dict, rebuilt_blocks: list[dict], *, ports
) -> dict:
    if not old_registry:
        return {
            "registry": {},
            "binding_lost_questions": [],
            "binding_lost_option_keys": [],
        }
    rebuilt_texts = _rebuilt_option_texts(rebuilt_blocks, ports)
    new_registry: dict = {}
    binding_lost_questions: list[str] = []
    binding_lost_option_keys: list[tuple[str, str]] = []
    for question_key, entries in old_registry.items():
        if ports("isinstance")(entries, ports("dict")):
            new_opts: dict[str, str] = {}
            lost_keys: list[str] = []
            for opt_key, opt_text in entries.items():
                found = False
                if opt_key in rebuilt_texts:
                    for found_line in rebuilt_texts[opt_key]:
                        if opt_text.strip() in found_line or found_line in opt_text:
                            new_opts[opt_key] = opt_text
                            found = True
                            break
                if not found:
                    new_opts[opt_key] = opt_text
                    lost_keys.append(opt_key)
                    binding_lost_option_keys.append((question_key, opt_key))
            new_registry[question_key] = new_opts
            if lost_keys:
                binding_lost_questions.append(question_key)
        elif ports("isinstance")(entries, ports("list")):
            new_entries = ports("list")(entries)
            for entry in new_entries:
                if (
                    ports("hasattr")(entry, "binding_status")
                    and ports("getattr")(entry, "binding_status", "") == "binding_lost"
                ):
                    binding_lost_questions.append(question_key)
            new_registry[question_key] = new_entries
        else:
            new_registry[question_key] = entries
    return {
        "registry": new_registry,
        "binding_lost_questions": ports("list")(ports("set")(binding_lost_questions)),
        "binding_lost_option_keys": ports("list")(
            ports("set")(binding_lost_option_keys)
        ),
    }


def _rebuilt_option_texts(rebuilt_blocks, ports):
    rebuilt_texts: dict[str, list[str]] = {}
    for block in rebuilt_blocks:
        text = ports("str")(block.get("normalized_text", "") or "")
        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            for opt_key in ("A", "B", "C", "D", "E", "F"):
                if line.startswith(f"{opt_key}.") or line.startswith(f"{opt_key}、"):
                    rebuilt_texts.setdefault(opt_key, []).append(line)
    return rebuilt_texts

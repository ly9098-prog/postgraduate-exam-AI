"""Deterministic answer-difference grounding for wrong-question AI analysis.

The LLM must never be the source of truth for facts that can be derived from the
stored question + answer.  This module converts those facts into a compact,
provider-neutral contract used by both the prompt and the post-generation guard.

The implementation is deliberately conservative.  It only derives fine-grained
"missing/extra" sub-items when the structure is unambiguous; otherwise it keeps
only the selected/correct option facts instead of guessing.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.features.question_type import (
    QT_MULTIPLE_CHOICE,
    QT_SINGLE_CHOICE,
    QT_TRUE_FALSE,
)
from app.utils.answer_normalizer import normalize_choice_answer

_ROMAN_TRANSLATION = str.maketrans(
    {
        "Ⅰ": "I",
        "Ⅱ": "II",
        "Ⅲ": "III",
        "Ⅳ": "IV",
        "Ⅴ": "V",
        "Ⅵ": "VI",
        "Ⅶ": "VII",
        "Ⅷ": "VIII",
        "Ⅸ": "IX",
        "Ⅹ": "X",
    }
)
_ROMAN_LABELS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")
_ROMAN_TOKEN_RE = re.compile(r"(?<![A-Z])(?:VIII|VII|III|VI|IV|II|IX|V|X|I)(?![A-Z])")
_ROMAN_LINE_RE = re.compile(
    r"(?m)(?:^|\n)\s*(VIII|VII|III|VI|IV|II|IX|V|X|I)\s*[.．、:：]\s*"
)
_COMBO_SEPARATORS_RE = re.compile(r"[\s,，、;；/\\|+&和及与、（）()\[\]{}]+")

_MISSING_WORDS = ("漏选", "漏掉", "少选", "未选", "没选", "没有选")
_EXTRA_WORDS = ("多选", "错选", "误选", "不该选", "不应选")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "value", "content", "label", "name"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def _stem_text(content: Any) -> str:
    if isinstance(content, dict):
        for key in ("text", "stem", "content"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return _text(content)


def _option_map(options: Any) -> dict[str, str]:
    if not isinstance(options, dict):
        return {}
    result: dict[str, str] = {}
    for raw_key, raw_value in options.items():
        key = str(raw_key or "").strip().upper()
        if not key:
            continue
        result[key] = _text(raw_value)
    return result


def _normalize_roman_text(value: str) -> str:
    return str(value or "").translate(_ROMAN_TRANSLATION).upper()


def _parse_composite_roman_labels(value: str) -> list[str]:
    """Parse an option such as ``I、II、IV`` only when it contains labels only.

    This intentionally rejects prose such as ``I 正确，II 错误``.  Fine-grained
    missing/extra facts are emitted only for a strict combination-option shape.
    """

    text = _normalize_roman_text(value).strip()
    if not text:
        return []
    labels = _ROMAN_TOKEN_RE.findall(text)
    if not labels:
        return []
    remainder = _ROMAN_TOKEN_RE.sub("", text)
    remainder = _COMBO_SEPARATORS_RE.sub("", remainder)
    if remainder:
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for label in labels:
        if label in _ROMAN_LABELS and label not in seen:
            seen.add(label)
            ordered.append(label)
    return ordered


def _extract_roman_subitems(stem: str) -> dict[str, str]:
    """Extract ``I. ...`` / ``II. ...`` statements from a stem conservatively."""

    normalized = str(stem or "").translate(_ROMAN_TRANSLATION)
    matches = list(_ROMAN_LINE_RE.finditer(normalized))
    if not matches:
        return {}
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        label = match.group(1)
        end = (
            matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        )
        body = normalized[match.end() : end].strip()
        # Stop before a conventional option block if the last statement flows
        # directly into it in legacy imported text.
        body = re.split(r"\n\s*[A-DＡ-Ｄ][.．、:：]\s*", body, maxsplit=1)[0].strip()
        body = re.sub(r"\s+", " ", body)
        if body:
            result[label] = body
    return result


def _answer_key_display(answer: Any) -> str:
    return str(answer or "").strip().upper()


def _selected_option_items(
    keys: list[str], options: dict[str, str]
) -> list[dict[str, str]]:
    return [{"label": key, "text": options.get(key, "")} for key in keys]


def build_answer_grounding(
    *,
    question_type: str | None,
    content: Any,
    options: Any,
    correct_answer: Any,
    user_answer: Any,
) -> dict[str, Any]:
    """Build a deterministic answer-fact contract for one wrong answer.

    ``missing_items`` / ``extra_items`` are *facts*, not LLM interpretations.
    For a single-choice combination option (e.g. B=I、II、IV and D=I、IV), the
    function can safely derive the nested missing statement ``II``.  If the
    shape is not strict enough, it falls back to selected/correct option facts.
    """

    qtype = str(question_type or "").strip()
    option_map = _option_map(options)
    correct_raw = _answer_key_display(correct_answer)
    user_raw = _answer_key_display(user_answer)

    grounding: dict[str, Any] = {
        "question_type": qtype,
        "correct_answer": correct_raw,
        "user_answer": user_raw,
        "correct_selections": [],
        "user_selections": [],
        "missing_items": [],
        "extra_items": [],
        "component_items": [],
        "comparison_basis": "raw_answer",
        "fine_grained": False,
    }

    if qtype == QT_MULTIPLE_CHOICE:
        correct_keys = normalize_choice_answer(correct_raw)
        user_keys = normalize_choice_answer(user_raw)
        correct_set = set(correct_keys)
        user_set = set(user_keys)
        grounding["correct_answer"] = ",".join(correct_keys)
        grounding["user_answer"] = ",".join(user_keys)
        grounding["correct_selections"] = _selected_option_items(
            correct_keys, option_map
        )
        grounding["user_selections"] = _selected_option_items(user_keys, option_map)
        grounding["missing_items"] = _selected_option_items(
            [key for key in correct_keys if key not in user_set], option_map
        )
        grounding["extra_items"] = _selected_option_items(
            [key for key in user_keys if key not in correct_set], option_map
        )
        grounding["comparison_basis"] = "multiple_choice_options"
        grounding["fine_grained"] = True
        return grounding

    if qtype == QT_SINGLE_CHOICE:
        correct_key = normalize_choice_answer(correct_raw)
        user_key = normalize_choice_answer(user_raw)
        correct_key = correct_key[0] if len(correct_key) == 1 else correct_raw
        user_key = user_key[0] if len(user_key) == 1 else user_raw
        grounding["correct_answer"] = correct_key
        grounding["user_answer"] = user_key
        if correct_key:
            grounding["correct_selections"] = _selected_option_items(
                [correct_key], option_map
            )
        if user_key:
            grounding["user_selections"] = _selected_option_items(
                [user_key], option_map
            )

        correct_text = option_map.get(correct_key, "")
        user_text = option_map.get(user_key, "")
        correct_parts = _parse_composite_roman_labels(correct_text)
        user_parts = _parse_composite_roman_labels(user_text)
        if correct_parts and user_parts:
            known = _extract_roman_subitems(_stem_text(content))
            correct_set = set(correct_parts)
            user_set = set(user_parts)
            missing = [label for label in correct_parts if label not in user_set]
            extra = [label for label in user_parts if label not in correct_set]
            component_order: list[str] = []
            for label in correct_parts + user_parts:
                if label not in component_order:
                    component_order.append(label)
            grounding["component_items"] = [
                {"label": label, "text": known.get(label, "")}
                for label in component_order
            ]
            grounding["missing_items"] = [
                {"label": label, "text": known.get(label, "")} for label in missing
            ]
            grounding["extra_items"] = [
                {"label": label, "text": known.get(label, "")} for label in extra
            ]
            grounding["comparison_basis"] = "single_choice_composite_roman"
            grounding["fine_grained"] = True
        else:
            grounding["comparison_basis"] = "single_choice_option"
        return grounding

    if qtype == QT_TRUE_FALSE:
        grounding["comparison_basis"] = "true_false"
        return grounding

    return grounding


def grounding_verification_payload(grounding: dict[str, Any]) -> dict[str, Any]:
    """Minimal exact contract the model must echo back in ``answer_check``."""

    def _labels(key: str) -> list[str]:
        values = grounding.get(key) or []
        return [
            str(item.get("label") or "").strip()
            for item in values
            if isinstance(item, dict) and str(item.get("label") or "").strip()
        ]

    return {
        "correct_answer": str(grounding.get("correct_answer") or "").strip(),
        "user_answer": str(grounding.get("user_answer") or "").strip(),
        "missing": _labels("missing_items"),
        "extra": _labels("extra_items"),
    }


def grounding_prompt_payload(grounding: dict[str, Any]) -> dict[str, Any]:
    """Return only compact, model-useful facts (no internal flags)."""

    return {
        "correct_answer": grounding.get("correct_answer", ""),
        "user_answer": grounding.get("user_answer", ""),
        "correct_selections": grounding.get("correct_selections", []),
        "user_selections": grounding.get("user_selections", []),
        "missing_items": grounding.get("missing_items", []),
        "extra_items": grounding.get("extra_items", []),
        "component_items": grounding.get("component_items", []),
        "comparison_basis": grounding.get("comparison_basis", "raw_answer"),
        "answer_check": grounding_verification_payload(grounding),
    }


def grounding_fact_signature(grounding: dict[str, Any]) -> str:
    """Stable semantic signature used to detect historical/current answer drift."""

    return json.dumps(
        grounding_prompt_payload(grounding),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _item_display(item: dict[str, Any]) -> str:
    label = str(item.get("label") or "").strip()
    text = str(item.get("text") or "").strip()
    if label and text:
        return f"{label}（{text}）"
    return label or text


def build_grounded_diagnosis_prefix(grounding: dict[str, Any]) -> str:
    """Build the authoritative first sentence shown to the learner."""

    correct = str(grounding.get("correct_answer") or "").strip()
    user = str(grounding.get("user_answer") or "").strip()
    missing = [
        item for item in grounding.get("missing_items") or [] if isinstance(item, dict)
    ]
    extra = [
        item for item in grounding.get("extra_items") or [] if isinstance(item, dict)
    ]

    correct_sel = grounding.get("correct_selections") or []
    user_sel = grounding.get("user_selections") or []
    correct_text = (
        str(correct_sel[0].get("text") or "").strip()
        if len(correct_sel) == 1 and isinstance(correct_sel[0], dict)
        else ""
    )
    user_text = (
        str(user_sel[0].get("text") or "").strip()
        if len(user_sel) == 1 and isinstance(user_sel[0], dict)
        else ""
    )

    if grounding.get("comparison_basis") == "single_choice_composite_roman":
        user_part = f"你选择 {user}（{user_text}）" if user_text else f"你选择 {user}"
        correct_part = (
            f"正确答案为 {correct}（{correct_text}）"
            if correct_text
            else f"正确答案为 {correct}"
        )
        details: list[str] = []
        if missing:
            details.append("漏选 " + "、".join(_item_display(item) for item in missing))
        if extra:
            details.append("多选 " + "、".join(_item_display(item) for item in extra))
        if not missing and not extra:
            details.append("组合项本身无可进一步拆分的差异")
        return "作答核对：" + "，".join([user_part, correct_part] + details)

    if grounding.get("comparison_basis") == "multiple_choice_options":
        details = []
        if missing:
            details.append("漏选 " + "、".join(_item_display(item) for item in missing))
        if extra:
            details.append("多选 " + "、".join(_item_display(item) for item in extra))
        base = f"作答核对：你的答案为 {user or '未作答'}，正确答案为 {correct}"
        return base + ("；" + "，".join(details) if details else "")

    if correct or user:
        user_part = user or "未作答"
        if user_text:
            user_part += f"（{user_text}）"
        correct_part = correct
        if correct_text:
            correct_part += f"（{correct_text}）"
        return f"作答核对：你选择 {user_part}，正确答案为 {correct_part}"

    return "作答核对：请以服务端判题结果为准"


def build_revision_drift_analysis() -> dict[str, str]:
    """Safe response when the stored wrong answer no longer maps to current revision."""

    return {
        "mistake_diagnosis": (
            "题目已更新：当前版本与本次错题作答时版本的答案或选项映射已发生变化。"
            "为避免把历史选择错误映射到新版本，本次不自动判断具体漏选/错选项。"
        ),
        "knowledge_patch": (
            "请以当前页题目与当前正确答案为准重新核对定义、条件和各选项；"
            "旧版本的选项映射不再用于当前复盘。"
        ),
        "review_task": (
            "先按当前版本重新作答一次；若仍答错，再生成 AI 复盘，系统将基于新的作答版本进行核对。"
        ),
    }


def build_safe_grounded_analysis(grounding: dict[str, Any]) -> dict[str, str]:
    """Deterministic fail-closed analysis used when model grounding is invalid."""

    prefix = build_grounded_diagnosis_prefix(grounding)
    missing = [
        item for item in grounding.get("missing_items") or [] if isinstance(item, dict)
    ]
    extra = [
        item for item in grounding.get("extra_items") or [] if isinstance(item, dict)
    ]
    focus = missing or extra
    if focus:
        focus_text = "、".join(_item_display(item) for item in focus)
        knowledge = f"重点复核 {focus_text} 的判定依据；先逐项判断真伪，再映射到组合选项，避免只看整体选项。"
    else:
        knowledge = "重点对照正确选项与已选项的关键条件，逐条核对定义、适用条件和易混点，避免凭关键词作答。"
    review = "立即遮住答案重做一次，并写出每个判断步骤；24 小时后再做 1 道同类题检查是否仍会出现相同偏差。"
    return {
        "mistake_diagnosis": prefix,
        "knowledge_patch": knowledge,
        "review_task": review,
    }


def merge_grounded_diagnosis(grounding: dict[str, Any], model_reason: str) -> str:
    prefix = build_grounded_diagnosis_prefix(grounding).rstrip("。；; ")
    reason = str(model_reason or "").strip().lstrip("。；;，, ")
    if not reason:
        return prefix
    # Keep the mobile card bounded.  The authoritative fact prefix comes first;
    # the model supplies only the pedagogical explanation after it.
    combined = f"{prefix}。{reason}"
    return combined[:260]


def _near_keyword(
    text: str, needle: str, keywords: tuple[str, ...], radius: int = 18
) -> bool:
    start = 0
    while True:
        idx = text.find(needle, start)
        if idx < 0:
            return False
        window = text[max(0, idx - radius) : min(len(text), idx + len(needle) + radius)]
        if any(word in window for word in keywords):
            return True
        start = idx + max(1, len(needle))


def _near_label_keyword(
    text: str, label: str, keywords: tuple[str, ...], radius: int = 18
) -> bool:
    escaped = re.escape(label)
    # Option keys / roman labels are ASCII tokens. Bound them so I never matches
    # the first character of II/III/IV and A never matches ordinary Latin text.
    pattern = re.compile(rf"(?<![A-Z0-9]){escaped}(?![A-Z0-9])", re.IGNORECASE)
    for match in pattern.finditer(text):
        window = text[
            max(0, match.start() - radius) : min(len(text), match.end() + radius)
        ]
        if any(word in window for word in keywords):
            return True
    return False


def diagnosis_contradicts_grounding(
    diagnosis: str,
    grounding: dict[str, Any],
) -> tuple[bool, str | None]:
    """Reject explicit missing/extra claims that contradict deterministic facts.

    The server always prepends the true answer difference, so the model does not
    need to restate it.  This guard targets the failure mode seen in production:
    e.g. saying "漏选 I" when the deterministic missing statement is ``II``.
    """

    text = str(diagnosis or "").translate(_ROMAN_TRANSLATION)
    if not text:
        return False, None

    missing_items = [
        item for item in grounding.get("missing_items") or [] if isinstance(item, dict)
    ]
    extra_items = [
        item for item in grounding.get("extra_items") or [] if isinstance(item, dict)
    ]
    allowed_missing = {str(item.get("label") or "").strip() for item in missing_items}
    allowed_extra = {str(item.get("label") or "").strip() for item in extra_items}

    known_items: list[tuple[str, str]] = []
    for key in (
        "correct_selections",
        "user_selections",
        "component_items",
        "missing_items",
        "extra_items",
    ):
        for item in grounding.get(key) or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            value = str(item.get("text") or "").strip()
            if label and (label, value) not in known_items:
                known_items.append((label, value))

    # For composite options, also infer every roman statement mentioned by the
    # selected/correct option text so a selected item can never be called missed.
    if grounding.get("comparison_basis") == "single_choice_composite_roman":
        labels = set()
        for item in (grounding.get("correct_selections") or []) + (
            grounding.get("user_selections") or []
        ):
            if isinstance(item, dict):
                labels.update(
                    _parse_composite_roman_labels(str(item.get("text") or ""))
                )
        item_text_by_label = {
            str(item.get("label") or "").strip(): str(item.get("text") or "").strip()
            for item in missing_items + extra_items
        }
        for label in sorted(
            labels,
            key=lambda value: (
                _ROMAN_LABELS.index(value) if value in _ROMAN_LABELS else 999
            ),
        ):
            pair = (label, item_text_by_label.get(label, ""))
            if pair not in known_items:
                known_items.append(pair)

    for label, value in known_items:
        if (
            label
            and _near_label_keyword(text, label, _MISSING_WORDS)
            and label not in allowed_missing
        ):
            return True, f"contradictory_missing_label:{label}"
        if (
            label
            and _near_label_keyword(text, label, _EXTRA_WORDS)
            and label not in allowed_extra
        ):
            return True, f"contradictory_extra_label:{label}"
        # A concept name is a much stronger semantic signal than a one-letter
        # option key. Only use reasonably specific text to avoid false positives.
        if len(value) >= 2:
            if (
                _near_keyword(text, value, _MISSING_WORDS)
                and label not in allowed_missing
            ):
                return True, f"contradictory_missing_text:{label}"
            if _near_keyword(text, value, _EXTRA_WORDS) and label not in allowed_extra:
                return True, f"contradictory_extra_text:{label}"

    # If the server has a fine-grained error target, a diagnosis that talks
    # exclusively about a different enumerated statement is also unsafe even
    # without words such as "漏选". This catches outputs like "基数排序判断错了"
    # when the only missed statement is actually II（简单选择排序）. Generic
    # explanations that mention no specific component remain allowed.
    expected_focus = allowed_missing | allowed_extra
    if grounding.get("fine_grained") and expected_focus:
        referenced: set[str] = set()
        for item in grounding.get("component_items") or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            value = str(item.get("text") or "").strip()
            if not label:
                continue
            label_hit = bool(
                re.search(
                    rf"(?<![A-Z0-9]){re.escape(label)}(?![A-Z0-9])",
                    text,
                    flags=re.IGNORECASE,
                )
            )
            text_hit = len(value) >= 2 and value in text
            if label_hit or text_hit:
                referenced.add(label)
        if referenced and referenced.isdisjoint(expected_focus):
            return True, "diagnosis_focus_mismatch:" + ",".join(sorted(referenced))

    return False, None

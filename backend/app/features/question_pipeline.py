"""题目标准化、查重与共享 AI 审计规则。

Excel/PDF 导入与审核由 question_import_writer 提供；AI 补全、增强和草稿生成
由各自模块提供。所有入口复用 process_question_pipeline 的标准化和校验，
AI 结果仍须进入暂存区并经过人工审核。
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import llm
from app.features.question_normalizer import run_ocr_quality_gate
from app.features.question_type import CANONICAL_TYPES
from app.features.question_type import (
    normalize_question_type as _unified_normalize_type,
)
from app.features.roman_schema import _RE_ROMAN_SUBITEM_MARKER
from app.models.ai_generation_log import AiGenerationLog
from app.models.question import Question
from app.models.question_import import QuestionImport
from app.utils.trace.debug import debug_log, save_debug_snapshot

logger = logging.getLogger(__name__)


# ============================================================
# 一、QuestionNormalizer（标准化核心）
# ============================================================


class QuestionNormalizer:
    """把任意来源的题目统一为标准 Question Schema 并校验。"""

    VALID_SUBJECTS = {
        "math2",
        "math2-calculus",
        "math2-linalg",
        "exam408",
        "data_structure",
        "operating_system",
        "computer_organization",
        "computer_network",
        "english",
    }
    CANONICAL_TYPES = CANONICAL_TYPES
    TYPE_ALIASES = {
        # 导入别名映射 — 统一由 app.features.question_type 管理，
        # 此处保留引用以兼容依赖 TYPE_ALIASES 的调用方。
        # 新增别名请修改 question_type._RAW_ALIAS_MAP。
        "choice": "single_choice",
        "single": "single_choice",
        "singlechoice": "single_choice",
        "single_choice": "single_choice",
        "选择": "single_choice",
        "选择题": "single_choice",
        "单选": "single_choice",
        "单选题": "single_choice",
        "单项选择": "single_choice",
        "单项选择题": "single_choice",
        "multiple": "multiple_choice",
        "multiplechoice": "multiple_choice",
        "multiple_choice": "multiple_choice",
        "多选": "multiple_choice",
        "多选题": "multiple_choice",
        "多项选择": "multiple_choice",
        "多项选择题": "multiple_choice",
        "true_false": "true_false",
        "truefalse": "true_false",
        "judgement": "true_false",
        "judgment": "true_false",
        "t/f": "true_false",
        "tf": "true_false",
        "true/false": "true_false",
        "对错": "true_false",
        "对错题": "true_false",
        "判断": "true_false",
        "判断题": "true_false",
        "是非题": "true_false",
        "fill": "fill_blank",
        "blank": "fill_blank",
        "fillblank": "fill_blank",
        "fill_blank": "fill_blank",
        "填空": "fill_blank",
        "填空题": "fill_blank",
        "多空选择": "multi_blank_choice",
        "多空选择题": "multi_blank_choice",
        "multi_blank_choice": "multi_blank_choice",
        "多空单选": "multi_blank_choice",
        "多空单选题": "multi_blank_choice",
        "多空单选选择题": "multi_blank_choice",
        "多空多选": "multi_blank_multiple_choice",
        "多空多选题": "multi_blank_multiple_choice",
        "多空多选选择题": "multi_blank_multiple_choice",
        "multi_blank_multiple_choice": "multi_blank_multiple_choice",
        "subjective": "subjective",
        "主观": "subjective",
        "主观题": "subjective",
        "简答": "subjective",
        "简答题": "subjective",
        "论述": "subjective",
        "计算": "subjective",
    }
    SUBJECT_LABEL_MAP = {
        "数学二": "math2",
        "数学": "math2",
        "math2": "math2",
        "高数": "math2-calculus",
        "高等数学": "math2-calculus",
        "math2-calculus": "math2-calculus",
        "线代": "math2-linalg",
        "线性代数": "math2-linalg",
        "math2-linalg": "math2-linalg",
        "408": "exam408",
        "计算机": "exam408",
        "exam408": "exam408",
        "数据结构": "data_structure",
        "data_structure": "data_structure",
        "操作系统": "operating_system",
        "operating_system": "operating_system",
        "计算机组成": "computer_organization",
        "计算机组成原理": "computer_organization",
        "computer_organization": "computer_organization",
        "计算机网络": "computer_network",
        "computer_network": "computer_network",
        "英语": "english",
        "英语二": "english",
        "english": "english",
    }

    def normalize(self, raw: dict, source: dict | None = None) -> dict:
        from app.services.formula_normalizer import (
            normalize_text_import_math,
            wrap_inline_math,
        )

        plain_math = bool(raw.get("preserve_plain_math"))
        subject_code = self.normalize_subject(raw.get("subject") or raw.get("科目"))
        subject_id = self.normalize_subject_id(
            raw.get("subject_id") or raw.get("科目ID")
        )
        allow_subjectless = bool(raw.get("allow_subjectless"))
        previous_plain_math = getattr(self, "_plain_math_options", False)
        self._plain_math_options = plain_math
        try:
            options = self.normalize_options(
                raw.get("options") or raw.get("选项") or raw.get("parsed_options")
            )
        finally:
            self._plain_math_options = previous_plain_math
        blank_option_groups = self.normalize_blank_option_groups(
            raw.get("blank_option_groups")
            or (raw.get("parsed_content") or {}).get("blank_option_groups")
            or []
        )
        if blank_option_groups:
            options = []
            question_type = "multi_blank_choice"
        else:
            question_type = self.normalize_type(
                raw.get("question_type") or raw.get("题型"), options
            )
        stem = self.clean_text(
            raw.get("stem")
            or raw.get("题目")
            or raw.get("题干")
            or (raw.get("content") or {}).get("text")
            or (raw.get("parsed_content") or {}).get("text")
            or ""
        )
        stem = (
            normalize_text_import_math(stem) if plain_math else wrap_inline_math(stem)
        )
        # Capture raw answer before normalization for detection
        answer_raw = (
            raw.get("answer") or raw.get("答案") or raw.get("parsed_answer") or ""
        )
        # P2-2: Detect shared-option multi-blank when not already identified
        # Runs after stem/options normalization, before stem post-processing
        # that might destroy blank markers (_break_before_number_markers).
        if not blank_option_groups and question_type in ("single_choice",):
            from app.features.multi_blank_choice import (
                detect_shared_option_multi_blank,
            )

            detect = detect_shared_option_multi_blank(
                stem,
                options,
                str(answer_raw) if answer_raw else None,
            )
            if detect["is_multi_blank_choice"]:
                question_type = "multi_blank_choice"
                blank_option_groups = detect["blank_option_groups"]
                options = []
                if detect["serialized_answer"]:
                    answer_raw = detect["serialized_answer"]
        if question_type != "multi_blank_choice":
            stem = self._break_before_number_markers(stem)
        stem = self._remove_embedded_options(stem, options)
        # 文本导入不是 OCR 来源。代码题中的换行、符号不应被 OCR 污染规则
        # 误判并制造无意义的“解析警告”；OCR/PDF 图片链路仍保持原质量门。
        if raw.get("skip_ocr_quality_gate"):
            _ocr_gate_result = {"passed": True, "ocr_quality_flags": []}
        else:
            _ocr_gate_result = run_ocr_quality_gate(stem)
        answer = self.normalize_answer(answer_raw, question_type)
        analysis = self.clean_analysis(
            raw.get("analysis")
            or raw.get("explanation")
            or raw.get("解析")
            or raw.get("parsed_analysis")
            or ""
        )
        knowledge_points = self.normalize_knowledge_points(
            raw.get("knowledge_points") or raw.get("tags") or raw.get("知识")
        )
        difficulty = self.normalize_difficulty(raw.get("difficulty") or raw.get("难度"))
        normalized = {
            "subject": subject_code,
            "subject_id": subject_id,
            "question_type": question_type,
            "stem": stem,
            "options": options,
            "blank_option_groups": blank_option_groups,
            "answer": answer,
            "analysis": analysis,
            "knowledge_points": knowledge_points,
            "difficulty": difficulty,
            "source": self.normalize_source(source or raw.get("source")),
            "stem_hash": self.stem_hash(stem),
            "question_hash": self.build_question_hash(
                stem, options, answer, blank_option_groups=blank_option_groups
            ),
            "is_valid": True,
            "errors": [],
            "warnings": [],
        }
        # Detect option_group segments — when present, parsed_options may be
        # intentionally empty (image-type options), so skip options validation.
        if question_type in ("single_choice", "multiple_choice"):
            raw_seg_check = (
                raw.get("segments")
                or (raw.get("parsed_content") or {}).get("segments")
                or (raw.get("content") or {}).get("segments")
            )
            if raw_seg_check:
                normalized["_has_option_group"] = any(
                    isinstance(s, dict)
                    and "option_group" in str(s.get("region_type", ""))
                    for s in raw_seg_check
                )
        normalized.update(
            self.validate(normalized, allow_subjectless=allow_subjectless)
        )

        # Preserve segments and visual region metadata from the raw input
        raw_segments = (
            raw.get("segments")
            or (raw.get("parsed_content") or {}).get("segments")
            or (raw.get("content") or {}).get("segments")
        )
        if raw_segments:
            normalized["segments"] = raw_segments

        raw_parsed_content = raw.get("parsed_content") or raw.get("content") or {}
        if isinstance(raw_parsed_content, dict):
            if raw_parsed_content.get("render_mode"):
                normalized["render_mode"] = raw_parsed_content["render_mode"]
            if raw_parsed_content.get("source_snapshot_url"):
                normalized["source_snapshot_url"] = raw_parsed_content[
                    "source_snapshot_url"
                ]
            if raw_parsed_content.get("source_snapshot_full_page"):
                normalized["source_snapshot_full_page"] = raw_parsed_content[
                    "source_snapshot_full_page"
                ]

        # 统一验证字段 (Goal: 所有导题入口输出一致)
        is_valid = normalized["is_valid"]
        errors = normalized["errors"]
        normalized["validation_status"] = "passed" if is_valid else "failed"
        normalized["failure_reason"] = list(errors) if errors else None
        normalized["retry_recommended"] = not is_valid and any(
            "missing_option_" in e for e in errors
        )
        normalized["ocr_quality_flags"] = _ocr_gate_result["ocr_quality_flags"]
        if not _ocr_gate_result["passed"]:
            normalized["warnings"].append("ocr_contamination_detected")
            for flag in _ocr_gate_result["ocr_quality_flags"]:
                normalized["warnings"].append(f"ocr_quality:{flag}")

        return normalized

    @staticmethod
    def normalize_subject_id(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            subject_id = int(value)
        except (TypeError, ValueError):
            return None
        return subject_id if subject_id > 0 else None

    def normalize_subject(self, value: Any) -> str:
        subject_code = str(value or "").strip()
        return self.SUBJECT_LABEL_MAP.get(
            subject_code, subject_code if subject_code in self.VALID_SUBJECTS else ""
        )

    def normalize_type(self, value: Any, options: Any = None) -> str:
        """规范化题型（导入流水线入口：别名容忍 + 无法识别时回退）。"""
        raw_type = str(value or "").strip().lower().replace("-", "_").replace(" ", "")
        normalized, _warnings = _unified_normalize_type(raw_type)
        if normalized is not None:
            return normalized
        # Pipeline 回退：无法识别时根据是否有选项猜测
        return "single_choice" if options else "fill_blank"

    def normalize_answer(self, answer: Any, question_type: str) -> str | list[str]:
        if isinstance(answer, list):
            values = [str(item).strip().upper() for item in answer if str(item).strip()]
        else:
            text = str(answer or "").strip()
            text = re.sub(
                r"^(?:【)?(?:参考|正确)?答案(?:是|为)?(?:】)?\s*[：:]?\s*",
                "",
                text,
            )
            text = text.strip("。.;； ")
            if question_type == "multiple_choice":
                values = [v for v in re.split(r"[,，、/\s]+", text.upper()) if v]
            elif question_type in ("multi_blank_choice", "multi_blank_multiple_choice"):
                from app.features.multi_blank_choice import (
                    extract_blank_slots,
                    parse_multi_blank_answer,
                    serialize_multi_blank_answer,
                )

                slot_ids = extract_blank_slots(text)
                if slot_ids:
                    parsed, _ = parse_multi_blank_answer(
                        text, slot_ids=slot_ids, allow_positional=True
                    )
                    if parsed:
                        return serialize_multi_blank_answer(parsed, slot_ids)
                return text
            else:
                return (
                    text.upper()
                    if question_type in {"single_choice", "true_false"}
                    else text
                )
        values = sorted({v for v in values if re.fullmatch(r"[A-Z]", v)})
        if question_type == "multiple_choice":
            return values
        return values[0] if values else ""

    def _remove_embedded_options(self, stem: str, options: list[dict]) -> str:
        if not stem or not options:
            return stem
        text = stem
        for item in options:
            key = re.escape(str(item.get("key") or "").strip())
            value = re.escape(str(item.get("text") or "").strip())
            if not key or not value:
                continue
            text = re.sub(rf"\s*{key}\s*[.、:：）)]\s*{value}", "", text)
        return text.strip()

    def normalize_options(self, options: Any) -> list[dict]:
        if not options:
            return []
        items: list[tuple[str | None, Any]] = []
        if isinstance(options, dict):
            for k, v in options.items():
                key = str(k).strip().upper()
                if isinstance(v, dict):
                    # Rich format: {"A": {"text": "...", "segments": [...]}}
                    text_val = str(v.get("text") or v.get("value") or "")
                    items.append(
                        (key, {"text": text_val, "segments": v.get("segments")})
                    )
                else:
                    items.append((key, str(v).strip()))
        elif isinstance(options, list):
            for item in options:
                if isinstance(item, dict):
                    key = item.get("key") or item.get("label") or item.get("option")
                    text = (
                        item.get("text")
                        or item.get("value")
                        or item.get("content")
                        or ""
                    )
                    if isinstance(text, dict):
                        items.append((str(key).strip().upper() if key else None, text))
                    else:
                        items.append(
                            (
                                str(key).strip().upper() if key else None,
                                str(text).strip(),
                            )
                        )
                else:
                    items.append((None, str(item).strip()))
        else:
            items = self._parse_options_text(str(options))

        normalized: list[dict] = []
        used: set[str] = set()
        next_index = 0
        from app.services.formula_normalizer import (
            normalize_text_import_math,
            wrap_inline_math,
        )

        plain_math = bool(getattr(self, "_plain_math_options", False))
        for key, value in items:
            if isinstance(value, dict):
                # Rich option — preserve structure, clean text inside
                text_val = value.get("text", "")
                cleaned_text = self.clean_text(text_val)
                cleaned_text = (
                    normalize_text_import_math(cleaned_text, compact=plain_math)
                    if plain_math
                    else wrap_inline_math(cleaned_text)
                )
                if not cleaned_text:
                    continue
                if not key or not re.fullmatch(r"[A-Z]", key):
                    while chr(65 + next_index) in used:
                        next_index += 1
                    key = chr(65 + next_index)
                if key in used:
                    continue
                used.add(key)
                entry: dict = {"key": key, "text": cleaned_text}
                if value.get("segments"):
                    entry["segments"] = value["segments"]
                normalized.append(entry)
            else:
                text = self.clean_text(value)
                text = (
                    normalize_text_import_math(text, compact=plain_math)
                    if plain_math
                    else wrap_inline_math(text)
                )
                if not text:
                    continue
                if not key or not re.fullmatch(r"[A-Z]", key):
                    while chr(65 + next_index) in used:
                        next_index += 1
                    key = chr(65 + next_index)
                if key in used:
                    continue
                used.add(key)
                normalized.append({"key": key, "text": text})
        return sorted(normalized, key=lambda item: item["key"])

    def normalize_blank_option_groups(self, groups: Any) -> list[dict]:
        if not isinstance(groups, list):
            return []
        normalized: list[dict] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            marker = str(group.get("id") or group.get("marker") or "").strip()
            options = self.normalize_options(group.get("options"))
            if marker and options:
                normalized.append({"id": marker, "options": options})
        return normalized

    def clean_text(self, text: Any) -> str:
        from app.services.pdf_text_normalizer import deduplicate_repeated_text

        text = str(text or "")
        text = text.replace("\xa0", " ").replace("　", " ")
        text = re.sub(r"[​﻿]", "", text)
        text = re.sub(r"[□■●◆◇]+", "", text)
        text = re.sub(r"\\mathrm\{([^}]*)\}", r"\1", text)
        text = re.sub(r"\\textbf\{([^}]*)\}", r"\1", text)
        text = re.sub(r"\\textit\{([^}]*)\}", r"\1", text)
        text = re.sub(r"\\mathtt\{([^}]*)\}", r"\1", text)
        lines: list[str] = []
        prev_empty = False
        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            if not line:
                if not prev_empty and lines:
                    lines.append("")
                prev_empty = True
                continue
            if self._is_noise_line(line):
                continue
            prev_empty = False
            lines.append(line)
        text = "\n".join(lines)
        # 题号前缀剥离：仅在分隔符后非数字时剥离，避免误伤小数/二进制选项
        # （如 "1.0010101"、"8.4s"、"9.3×10^13" 中的前导数字是选项内容）。
        text = re.sub(r"^\d+\s*[.、)）](?!\d)\s*", "", text)
        text = deduplicate_repeated_text(text)
        # Repair comparison operators broken across lines (e.g. "if (n <=\n1) return n;")
        text = re.sub(r"(<=|>=|==|!=)\s*\n\s*", r"\1 ", text)
        text = self._normalize_code_newlines(text)
        return self._merge_broken_lines(text).strip()

    @staticmethod
    def _break_before_number_markers(text: str) -> str:
        """在题号标记前插入换行：① ② ...、（1）（2）...、1) 2) ...

        跳过 fenced code block（```...```）内部内容，防止将代码中的
        `1)`、`（1）` 等数字标记误识别为题号并插入换行。
        """
        lines = text.split("\n")
        result: list[str] = []
        in_fence = False
        for line in lines:
            if line.strip().startswith("```"):
                result.append(line)
                in_fence = not in_fence
                continue
            if in_fence:
                result.append(line)
                continue
            # ①-⑳ 圈号标记
            line = re.sub(r"(?<![（(\n])([①-⑳])", r"\n\1", line)
            # （1）（2）全角括号数字：仅在前一个字符不是 ASCII 标识符时换行。
            # 例如图论/离散数学中 x（2）、v（3）属于变量/顶点标识，不能当作子项序号。
            line = re.sub(r"(?<=[^\sA-Za-z0-9_])[　 ]*([（][0-9]+[）])", r"\n\1", line)
            # 1) 2) 数字+括号：同样禁止从 ASCII 标识符内部切开。
            # 旧规则会把 "(v1,v2)10" 误处理成 "(v1,v\n2)10"，导致刷题页异常换行。
            line = re.sub(
                r"(?<=[^\s\dA-Za-z_,（(])[　 ]*(\d+[)）])(?=\s*[一-鿟\w])",
                r"\n\1",
                line,
            )
            result.append(line)
        return "\n".join(result)

    def clean_analysis(self, text: Any) -> str:
        text = self.clean_text(text)
        text = re.sub(r"^(?:【)?(?:答案解析|解析|解答)(?:】)?\s*[：:]\s*", "", text)
        return text.strip()

    def validate(self, question: dict, *, allow_subjectless: bool = False) -> dict:
        errors: list[str] = []
        warnings: list[str] = []
        if not question.get("stem"):
            errors.append("stem_empty")
        if not question.get("answer") and question.get("question_type") not in (
            "multi_blank_choice",
            "multi_blank_multiple_choice",
        ):
            errors.append("answer_empty")
        if question.get("question_type") in {"single_choice", "multiple_choice"}:
            # Image-type options (option_group) have intentionally empty
            # parsed_options — skip the text-options validation.
            if question.get("_has_option_group"):
                pass
            else:
                options = question.get("options") or []
                if not options:
                    errors.append("options_empty")
                elif len(options) < 2:
                    warnings.append("options_too_few")
                # 单选题必须包含全部 A/B/C/D 选项（共享校验逻辑）
                from app.features.question_normalizer import (
                    check_option_completeness as _check_opts,
                )

                _, opt_errors = _check_opts(question.get("question_type"), options)
                errors.extend(opt_errors)
        if question.get("question_type") in (
            "multi_blank_choice",
            "multi_blank_multiple_choice",
        ):
            groups = question.get("blank_option_groups") or []
            if not groups:
                errors.append("missing_blank_option_groups")
            elif len(groups) < 2:
                errors.append("multi_blank_choice_requires_at_least_2_blanks")
            if groups:
                seen_ids = set()
                for i, group in enumerate(groups):
                    gid = str(group.get("id") or "").strip()
                    if not gid:
                        errors.append(f"blank_group_{i}_empty_id")
                    elif gid in seen_ids:
                        errors.append(f"blank_group_duplicate_id_{gid}")
                    seen_ids.add(gid)
                    opts = group.get("options") or []
                    if len(opts) < 2:
                        errors.append(f"blank_group_{gid}_less_than_2_options")
                    seen_keys = set()
                    for opt in opts:
                        key = str(opt.get("key") or "").upper()
                        if key in seen_keys:
                            errors.append(f"blank_group_{gid}_duplicate_key_{key}")
                        seen_keys.add(key)
            # P2-7: Validate answer against blank_option_groups
            from app.features.multi_blank_choice import validate_multi_blank_question

            answer = question.get("answer")
            _, answer_errors = validate_multi_blank_question(groups, answer)
            errors.extend(answer_errors)
        if (
            not question.get("subject")
            and not question.get("subject_id")
            and not allow_subjectless
        ):
            errors.append("subject_empty")
        return {"is_valid": not errors, "errors": errors, "warnings": warnings}

    def stem_hash(self, stem: str) -> str:
        compact = re.sub(r"\s+", "", stem or "").lower()
        return (
            hashlib.sha256(compact.encode("utf-8")).hexdigest()[:16] if compact else ""
        )

    def normalize_hash_text(self, value: Any) -> str:
        text = str(value or "")
        text = text.replace("\xa0", " ").replace("　", " ")
        text = re.sub(r"[​‌‍⁠﻿‎‏]", "", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\n", " ")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def normalize_hash_options(self, options: Any) -> str:
        if not options:
            return ""
        items: list[tuple[str, str]] = []
        if isinstance(options, dict):
            items = [(str(k).strip().upper(), str(v)) for k, v in options.items()]
        elif isinstance(options, list):
            for item in options:
                if isinstance(item, dict):
                    key = item.get("key") or item.get("label") or item.get("option")
                    text = (
                        item.get("text")
                        or item.get("value")
                        or item.get("content")
                        or ""
                    )
                    if key:
                        items.append((str(key).strip().upper(), str(text)))
                else:
                    items.append(("", str(item)))
        else:
            text = str(options)
            for part in re.split(r"\n+", text):
                if not part.strip():
                    continue
                m = re.match(r"^\s*([A-H])\s*[.、:：）)]\s*(.*)$", part.strip())
                if m:
                    items.append((m.group(1).strip().upper(), m.group(2)))
                else:
                    items.append(("", part))
        parts = []
        for key, text in sorted(items, key=lambda item: item[0]):
            normalized_text = self.normalize_hash_text(text)
            if not normalized_text:
                continue
            parts.append(f"{key}={normalized_text}" if key else normalized_text)
        return "|".join(parts)

    def normalize_hash_answer(self, answer: Any) -> str:
        if isinstance(answer, list):
            values = [self.normalize_hash_text(item).upper() for item in answer]
            values = sorted({value for value in values if value})
            return "|".join(values)
        text = self.normalize_hash_text(answer)
        return text.upper() if text else ""

    def normalize_hash_blank_groups(self, groups: list[dict]) -> str:
        """Normalize blank_option_groups for hash computation."""
        if not groups:
            return ""
        parts: list[str] = []
        for group in groups:
            gid = str(group.get("id") or "")
            opts = group.get("options") or []
            opt_parts = []
            if isinstance(opts, list):
                for opt in opts:
                    if isinstance(opt, dict):
                        key = str(opt.get("key") or "").upper()
                        text = self.normalize_hash_text(opt.get("text") or "")
                        if key and text:
                            opt_parts.append(f"{key}={text}")
            opt_str = "|".join(sorted(opt_parts))
            parts.append(f"{gid}[{opt_str}]")
        return "||".join(parts)

    def build_question_hash(
        self,
        stem: Any,
        options: Any,
        answer: Any,
        blank_option_groups: list[dict] | None = None,
    ) -> str:
        payload = "||".join(
            [
                self.normalize_hash_text(stem),
                self.normalize_hash_options(options),
                self.normalize_hash_answer(answer),
                self.normalize_hash_blank_groups(blank_option_groups or []),
            ]
        )
        return hashlib.md5(payload.encode("utf-8")).hexdigest() if payload else ""

    def is_similar_stem(self, left: str, right: str, threshold: float = 0.92) -> bool:
        a = re.sub(r"\s+", "", left or "")
        b = re.sub(r"\s+", "", right or "")
        if not a or not b:
            return False
        return difflib.SequenceMatcher(None, a, b).ratio() >= threshold

    def to_import_fields(self, question: dict) -> dict:
        parsed_content: dict[str, Any] = {"text": question["stem"]}
        if question.get("blank_option_groups"):
            parsed_content["blank_option_groups"] = question["blank_option_groups"]
        # Preserve segments and render_mode from upstream pipeline stages
        segments = question.get("segments") or (
            question.get("parsed_content") or {}
        ).get("segments")
        render_mode = (
            question.get("parsed_content", {}).get("render_mode")
            if isinstance(question.get("parsed_content"), dict)
            else None
        )
        if segments:
            parsed_content["render_mode"] = render_mode or "segments"
            parsed_content["segments"] = segments
        # Preserve source_snapshot_url and full_page flag
        if question.get("source_snapshot_url"):
            parsed_content["source_snapshot_url"] = question["source_snapshot_url"]
        if question.get("source_snapshot_full_page"):
            parsed_content["source_snapshot_full_page"] = question[
                "source_snapshot_full_page"
            ]
        # Preserve visual_regions if present
        if question.get("visual_regions"):
            parsed_content["visual_regions"] = question["visual_regions"]
        return {
            "subject": question["subject"] or None,
            "subject_id": question.get("subject_id"),
            "question_type": question["question_type"],
            "parsed_content": parsed_content,
            "parsed_options": self.options_to_dict(question["options"]),
            "parsed_answer": self.answer_to_db(question["answer"]),
            "parsed_analysis": question["analysis"] or None,
            "knowledge_points": question["knowledge_points"],
            "difficulty": question["difficulty"],
        }

    def to_question_fields(self, question: dict) -> dict:
        fields = self.to_import_fields(question)
        result = {
            "subject_id": fields.get("subject_id"),
            "question_type": fields["question_type"],
            "content": fields["parsed_content"],
            "options": fields["parsed_options"],
            "answer": fields["parsed_answer"] or "",
            "analysis": fields["parsed_analysis"],
            "question_hash": question.get("question_hash") or None,
            "knowledge_points": fields["knowledge_points"],
            "difficulty": fields["difficulty"],
        }
        # to_import_fields now preserves segments, so content already has them.
        # If the original question dict has additional segment fields, ensure they survive.
        q_segments = question.get("segments") or (
            question.get("parsed_content") or {}
        ).get("segments")
        if q_segments and not result["content"].get("segments"):
            result["content"]["render_mode"] = "segments"
            result["content"]["segments"] = q_segments
        return result

    def options_to_dict(self, options: list[dict]) -> dict | None:
        result: dict[str, Any] = {}
        for item in options:
            key = item.get("key")
            text = item.get("text")
            if not key or not text:
                continue
            segments = item.get("segments")
            if segments:
                # Rich option: {"A": {"text": "...", "segments": [...]}}
                result[key] = {"text": text, "segments": segments}
            else:
                result[key] = text
        return result or None

    def answer_to_db(self, answer: str | list[str]) -> str | None:
        if isinstance(answer, list):
            return ",".join(answer) if answer else None
        return answer or None

    def normalize_knowledge_points(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if not value:
            return []
        return [
            item.strip() for item in re.split(r"[,，、;；]", str(value)) if item.strip()
        ]

    def normalize_difficulty(self, value: Any) -> int:
        try:
            difficulty = int(value)
        except (TypeError, ValueError):
            difficulty = 3
        return max(1, min(5, difficulty))

    def normalize_source(self, source: Any) -> dict:
        if isinstance(source, dict):
            page = source.get("page", 0)
            try:
                page = int(page or 0)
            except (TypeError, ValueError):
                page = 0
            return {"file": str(source.get("file") or ""), "page": page}
        return {"file": str(source or ""), "page": 0}

    def _parse_options_text(self, text: str) -> list[tuple[str | None, str]]:
        text = text.replace("\\n", "\n")
        pattern = re.compile(
            r"(?:^|\s|\n)([A-H])\s*[.、:：）]\s*(.*?)(?=(?:\s|\n)[A-H]\s*[.、:：）]|$)",
            re.S,
        )
        found = pattern.findall(text)
        if found:
            return [(key, value.strip()) for key, value in found]
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return [(None, line) for line in lines]

    def _merge_broken_lines(self, text: str) -> str:
        result: list[str] = []
        in_code_fence = False
        for line in text.split("\n"):
            if line.strip().startswith("```"):
                result.append(line)
                in_code_fence = not in_code_fence
                continue
            if in_code_fence:
                result.append(line)
                continue
            if not result:
                result.append(line)
                continue
            if self._should_merge(result[-1], line):
                result[-1] += line
            else:
                result.append(line)
        return "\n".join(result)

    def _should_merge(self, prev: str, curr: str) -> bool:
        if not prev or not curr:
            return False
        if re.match(
            r"^([A-H]\s*[.、:：）]|(?:【)?(?:参考|正确)?答案|(?:【)?解析)", curr
        ):
            return False
        if prev[-1] in "。！？；…，,":
            return False
        # Don't merge Roman numeral enumeration items (I. II. III. IV. …)
        if _RE_ROMAN_SUBITEM_MARKER.match(curr.lstrip()):
            return False
        # Don't merge into / out of indented code-block lines
        if re.match(r"^[ \t]{2,}\S", curr) or re.match(r"^[ \t]{2,}\S", prev):
            return False
        # Don't merge code-block lines (braces alone on a line, or lines with C/Java-like syntax)
        if re.search(r"[{};]\s*(?://.*)?$", prev) or re.search(r"^\s*[{}]", curr):
            return False
        # Don't merge when previous line ends with `)` belonging to a control-flow header
        # (e.g. `if (...)`, `while (...)`, `for (...)`, `switch (...)`) followed by a code line
        if re.search(r"\b(if|while|for|switch|else\s+if)\s*\(.*\)\s*$", prev):
            return False
        # Don't merge bare `else` / `do` headers with the following code line
        if re.match(r"^\s*(?:else|do)\s*$", prev):
            return False
        # Don't merge when a colon-ended intro line meets a code line
        if prev.rstrip().endswith(":") and re.search(r"[{};=]", curr):
            return False
        # Generic code line protection: don't merge lines with strong code signals
        # into or out of each other (protects unfenced code from line merging)
        _CODE_LINE_RE = re.compile(
            r"^\s*(?:for|while|if|else|switch|case|return|int|float|double|char|void|"
            r"struct|typedef|const|static|sizeof|printf|scanf|malloc|free"
            r"|def|class|import|from|public|private|protected|function|var|let|const"
            r"|ListNode|BiTree|LNode|TNode|LinkList|SqList|Stack|Queue|ElemType|Status"
            r")\b"
        )
        if _CODE_LINE_RE.match(curr) or _CODE_LINE_RE.match(prev):
            return False
        # Protect lines ending with code operators (; or closing brace)
        if re.search(r"[;}]$", curr.rstrip()):
            return False
        return True

    # Patterns: code lines that end mid-expression because the next line
    # starts with an operator (case 2: `x < n\n/ 2`) or the line itself
    # ends with a trailing operator (case 3: `n <=\n1`).
    _TRAILING_OP_RE = re.compile(r"(?:<=|>=|==|!=|&&|\|\||<<|>>|[<>=!+\-*/%&|^])\s*$")
    # Operator + word at line end → operand was split from its continuation
    #  while (x < n\n/ 2) → merge n/2 back
    _OP_THEN_WORD_END_RE = re.compile(r"[<>=!+\-*/%&|^]\s+\w+\s*$")

    # Next-line patterns that are clearly NOT operands (statement boundaries).
    _CODE_KW_RE = re.compile(
        r"^\s*(?:if|else|while|for|do|switch|case|return|break|continue|"
        r"int|float|double|char|void|long|short|struct|enum|typedef|"
        r"public|private|protected|class|static|const|virtual)\b"
    )

    def _line_ends_broken(self, line: str) -> bool:
        stripped = line.rstrip()
        if not stripped:
            return False
        if not re.search(r"[{};=()[\]<>!&|]", stripped):
            return False
        return bool(
            self._TRAILING_OP_RE.search(stripped)
            or self._OP_THEN_WORD_END_RE.search(stripped)
        )

    def _line_starts_continuation(self, line: str) -> bool:
        stripped = line.lstrip()
        if not stripped:
            return False
        if stripped[0] in "{};":
            return False
        if self._CODE_KW_RE.match(stripped):
            return False
        # Starts with an operator character → continuation of broken expression
        if stripped[0] in "+*/%&|^<>!=~":
            return True
        # Contains code operators/separators but not a new statement
        return bool(re.search(r"[+\-*/%<>=!&|(){};\[\]]", stripped))

    def _normalize_code_newlines(self, text: str) -> str:
        """Merge code lines that were split inside expressions by AI normalization.

        Detects patterns like ``while (x < n\\n/ 2)`` where the newline sits
        between an operator and its operand, and rejoins them with a space.
        """
        if "\n" not in text:
            return text
        lines = text.split("\n")
        result: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if (
                i + 1 < len(lines)
                and self._line_ends_broken(line)
                and self._line_starts_continuation(lines[i + 1])
            ):
                merged = line.rstrip() + " " + lines[i + 1].lstrip()
                result.append(merged)
                i += 2
            else:
                result.append(line)
                i += 1
        return "\n".join(result)

    def _is_noise_line(self, line: str) -> bool:
        if re.fullmatch(r"第?\s*\d+\s*页\s*(?:/\s*共?\s*\d+\s*页?)?", line):
            return True
        if re.fullmatch(r"[-—_=]{3,}", line):
            return True
        # Repeating-letter separators (xxxxxxxxxx, ==========, etc.) — boundary artifact.
        # Digits excluded: all-same-digit strings are legitimate binary/bit options
        # (e.g. 11111111, 00000000) in register/bus questions.
        if re.fullmatch(r"([A-Za-z])\1{4,}", line):
            return True
        # 短行内容判定需把圈号数字（①-⑳）计入内容字符，否则“①、”等题号/序号行会被
        # 当噪声丢弃（如“①、②所花费的时间之比”中的“①、”）。
        # 比较/关系运算符（<>≥≤≠）也须计入：单字符数学符号可作为多空选项
        # （如 1266 ② 组选项 < > ≥ ≤），否则整组被误判为噪声而丢弃。
        if len(line) <= 2 and not re.search(
            r"[一-鿿A-Za-z0-9{}\[\]()①-⑳<>≥≤≠≈±×÷·]", line
        ):
            return True
        return False


normalizer = QuestionNormalizer()

SUBJECT_VALUES = QuestionNormalizer.VALID_SUBJECTS
TYPE_VALUES = CANONICAL_TYPES


# ============================================================
# 二、统一入口：process_question_pipeline
# ============================================================


def process_question_pipeline(
    raw_input: dict,
    source_type: str,
    source: dict | None = None,
    trace_id: str | None = None,
) -> dict:
    """所有题目入口的唯一管线。

    source_type: excel / pdf / ocr / ai / manual
    返回:
        {
          "normalized": 标准 Question Schema,
          "import_fields": QuestionImport 兼容字段,
          "question_fields": Question 兼容字段（仅当 is_valid）,
          "is_valid": bool, "errors": [...], "warnings": [...],
          "stem_hash": str,
        }
    """
    debug_log(
        trace_id,
        "BEFORE_NORMALIZE",
        {
            "source_type": source_type,
            "source": source,
            "raw_keys": list(raw_input.keys()),
        },
    )
    save_debug_snapshot(
        trace_id,
        "before_normalize",
        {"source_type": source_type, "source": source, "raw_input": raw_input},
    )
    normalized = normalizer.normalize(raw_input, source)
    result = {
        "source_type": source_type,
        "normalized": normalized,
        "is_valid": normalized["is_valid"],
        "errors": normalized["errors"],
        "warnings": normalized["warnings"],
        "stem_hash": normalized["stem_hash"],
        "import_fields": normalizer.to_import_fields(normalized),
        "question_fields": (
            normalizer.to_question_fields(normalized)
            if normalized["is_valid"]
            else None
        ),
    }
    debug_log(
        trace_id,
        "AFTER_NORMALIZE",
        {
            "source_type": source_type,
            "is_valid": normalized["is_valid"],
            "errors": normalized["errors"],
            "warnings": normalized["warnings"],
            "question_hash": normalized["question_hash"],
            "stem_hash": normalized["stem_hash"],
        },
    )
    save_debug_snapshot(
        trace_id,
        "after_normalize",
        {
            "source_type": source_type,
            "normalized": normalized,
            "is_valid": normalized["is_valid"],
            "errors": normalized["errors"],
            "warnings": normalized["warnings"],
        },
    )
    if not normalized["is_valid"]:
        logger.warning(
            "Invalid question skipped: source_type=%s file=%s errors=%s stem_hash=%s",
            source_type,
            (source or {}).get("file"),
            normalized["errors"],
            normalized["stem_hash"],
        )
    return result


async def _find_duplicate_by_hash(
    db: AsyncSession,
    subject_code: str | None,
    question_hash: str | None,
    subject_id: int | None = None,
) -> Question | None:
    if not question_hash:
        return None
    conditions = [Question.question_hash == question_hash, Question.is_active]
    if subject_id is not None:
        conditions.append(Question.subject_id == subject_id)
    elif subject_code:
        from app.services.subject_resolution import resolve_subject_id

        resolved = await resolve_subject_id(db, subject_code)
        if resolved is not None:
            conditions.append(Question.subject_id == resolved)
        else:
            return None
    else:
        return None
    result = await db.execute(select(Question).where(*conditions))
    return result.scalar_one_or_none()


async def _find_import_duplicate_by_hash(
    db: AsyncSession,
    subject_code: str | None,
    question_hash: str | None,
    subject_id: int | None = None,
) -> QuestionImport | None:
    if not question_hash:
        return None
    conditions = [
        QuestionImport.question_hash == question_hash,
        QuestionImport.status != "rejected",
    ]
    if subject_id is not None:
        conditions.append(QuestionImport.subject_id == subject_id)
    elif subject_code:
        from app.services.subject_resolution import resolve_subject_id

        resolved = await resolve_subject_id(db, subject_code)
        if resolved is not None:
            conditions.append(QuestionImport.subject_id == resolved)
        else:
            return None
    else:
        return None
    result = await db.execute(select(QuestionImport).where(*conditions))
    existing = result.scalars().first()
    if existing is None:
        return None
    # If the import was already approved but the question was later soft-deleted, allow re-import
    if existing.question_id is not None:
        q = await db.get(Question, existing.question_id)
        if q is None or not q.is_active:
            return None
    return existing


async def find_duplicate_question(
    db: AsyncSession, subject_code: str | None, stem: str
) -> Question | None:
    """兼容旧调用：同 subject_code 下用 stem hash + 相似度查疑似重复题。"""
    if not subject_code or not stem:
        return None
    from app.services.subject_resolution import resolve_subject_id

    resolved_id = await resolve_subject_id(db, subject_code)
    if resolved_id is None:
        return None
    result = await db.execute(
        select(Question).where(Question.subject_id == resolved_id, Question.is_active)
    )
    target_hash = normalizer.stem_hash(stem)
    for question in result.scalars().all():
        existing_stem = (question.content or {}).get("text", "")
        cleaned_existing_stem = normalizer.clean_text(existing_stem)
        if normalizer.stem_hash(existing_stem) == target_hash:
            return question
        if normalizer.stem_hash(cleaned_existing_stem) == target_hash:
            return question
        if normalizer.is_similar_stem(existing_stem, stem):
            return question
        if normalizer.is_similar_stem(cleaned_existing_stem, stem):
            return question
    return None


# ============================================================
# 四、导入主流程（Excel / PDF / 审核）
# ============================================================


_QI_PARSED_FIELDS = (
    "subject_id",
    "question_type",
    "parsed_content",
    "parsed_options",
    "parsed_answer",
    "parsed_analysis",
)


async def _get_qi(db: AsyncSession, import_id: int) -> QuestionImport:
    res = await db.execute(select(QuestionImport).where(QuestionImport.id == import_id))
    qi = res.scalar_one_or_none()
    if not qi:
        raise ValueError("导入记录不存在")
    return qi


# ============================================================
# 五、AI 辅助导题（enrich / generate / complete）
# ============================================================


def _qi_to_dict(qi: QuestionImport) -> dict:
    content_text = (qi.parsed_content or {}).get("text", "")
    return {
        "subject_code": qi.subject_ref.code if qi.subject_ref else qi.subject_id,
        "subject_id": qi.subject_id,
        "question_type": qi.question_type,
        "parsed_content": qi.parsed_content,
        "parsed_options": qi.parsed_options,
        "parsed_answer": qi.parsed_answer,
        "parsed_analysis": qi.parsed_analysis,
        # 以下字段兼容 build_repair_question 的键名
        "stem": content_text,
        "options": qi.parsed_options,
        "answer": qi.parsed_answer,
        "analysis": qi.parsed_analysis,
        "errors": [],
        "raw_text": (qi.raw_data or {}).get("stem") if qi.raw_data else None,
    }


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass
    # 兜底：定位文本中第一个完整的 JSON 对象。贪婪正则 (\{.*\}) 会把
    # JSON 后的解释文字一起吞掉导致解析失败，raw_decode 则只吃第一个
    # 完整对象、忽略尾部内容。
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            obj, end_idx = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        # 若首个对象之后又出现一个可解析的 JSON 对象（如模型先给草稿再给
        # 最终答案），无法确定取哪个——返回 None 让调用方走兜底/重试，避免
        # 静默采用可能错误的首个对象污染题目数据。
        nxt = text.find("{", end_idx)
        if nxt != -1:
            try:
                decoder.raw_decode(text, nxt)
                return None
            except json.JSONDecodeError:
                pass
        return obj
    return None


def _detect_missing(qi: QuestionImport) -> list[str]:
    missing: list[str] = []
    if not qi.subject_id:
        missing.append("subject_id")
    if not qi.question_type:
        missing.append("question_type")
    if not (qi.parsed_content and qi.parsed_content.get("text")):
        missing.append("stem")
    if not qi.parsed_answer:
        missing.append("answer")
    if not qi.parsed_analysis:
        missing.append("analysis")
    return missing


def _build_log(
    *,
    user_id: int,
    action: str,
    target_type: str | None,
    target_id: int | None,
    batch_id: str | None,
    prompt_text: str | None,
    raw_response: str | None,
    parsed_result: dict | None,
    confidence: float | None,
    model: str,
    tokens_used: int,
    duration_ms: int,
    success: bool,
    error_message: str | None = None,
) -> AiGenerationLog:
    return AiGenerationLog(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        batch_id=batch_id,
        prompt_text=prompt_text,
        raw_response=raw_response,
        parsed_result=parsed_result,
        confidence=confidence,
        model=model,
        tokens_used=tokens_used,
        duration_ms=duration_ms,
        success=1 if success else 0,
        error_message=error_message,
    )


async def _call_or_fallback(
    messages: list,
    fallback_value: dict,
    db: AsyncSession | None = None,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model_name: str | None = None,
) -> tuple[dict, str | None, dict | None]:
    provider: str | None = None
    if api_key is None and db is not None:
        from app.ai.gateway import resolve_llm_runtime_config

        runtime = await resolve_llm_runtime_config(db, feature="completion")
        if runtime is not None:
            api_key = runtime.api_key
            base_url = runtime.base_url
            model_name = runtime.model_name
            provider = runtime.provider

    if not api_key:
        return (
            {
                "content": "",
                "tokens_used": 0,
                "model": "fallback",
                "duration_ms": 0,
                "fallback_value": fallback_value,
                "error": "AI模型API Key未配置",
            },
            None,
            None,
        )
    try:
        resp = await llm.chat(
            messages,
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            provider=provider,
        )
        return (resp, resp["content"], resp)
    except (OSError, ValueError, RuntimeError, TimeoutError) as e:
        # 网络/超时/URL 校验类故障 → 降级（UnsafeRemoteURLError 是 ValueError）。
        # 只捕这几类：KeyError/TypeError 等编程错误让调用方暴露，避免被伪装成
        # AI 降级静默吞掉。
        return (
            {
                "content": "",
                "tokens_used": 0,
                "model": "fallback",
                "duration_ms": 0,
                "fallback_value": fallback_value,
                "error": str(e),
            },
            None,
            None,
        )


async def list_logs(
    db: AsyncSession,
    *,
    user_id: int | None = None,
    action: str | None = None,
    batch_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    conditions = []
    if user_id:
        conditions.append(AiGenerationLog.user_id == user_id)
    if action:
        conditions.append(AiGenerationLog.action == action)
    if batch_id:
        conditions.append(AiGenerationLog.batch_id == batch_id)
    stmt = select(AiGenerationLog)
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(AiGenerationLog.id.desc())
    items_res = await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
    return {
        "items": list(items_res.scalars().all()),
        "page": page,
        "pageSize": page_size,
    }

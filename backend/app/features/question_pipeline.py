"""题目导入与标准化统一管线（LLM-friendly 单文件聚合）。

合并自原 services/normalization/question_normalizer、import_service、
ai_import_service、ai_import_helpers。所有入口（Excel / PDF / OCR / AI）
都走 process_question_pipeline 进行标准化、校验、去重、落 DB 适配。

设计原则：
- 单文件内聚，不再向上拆 service / helper / utils。
- 不改数据库结构，只改 Python 层。
- AI 生成结果只进 question_imports 暂存区，不直接进 questions。
"""
from __future__ import annotations

import difflib
import hashlib
import io
import json
import logging
import re
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import deepseek
from app.core.config import settings
from app.features.question_normalizer import run_ocr_quality_gate
from app.features.question_splitter import split_questions
from app.features.question_type import (
    CANONICAL_TYPES,
    QT_FILL_BLANK,
    QT_SINGLE_CHOICE,
    QT_TRUE_FALSE,
)
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
        "math2", "math2-calculus", "math2-linalg",
        "exam408", "exam408-ds", "exam408-os", "exam408-co", "exam408-cn",
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
        "subjective": "subjective",
        "主观": "subjective",
        "主观题": "subjective",
        "简答": "subjective",
        "简答题": "subjective",
        "论述": "subjective",
        "计算": "subjective",
    }
    SUBJECT_ALIASES = {
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
        "数据结构": "exam408-ds",
        "ds": "exam408-ds",
        "exam408-ds": "exam408-ds",
        "操作系统": "exam408-os",
        "os": "exam408-os",
        "exam408-os": "exam408-os",
        "计算机组成": "exam408-co",
        "计算机组成原理": "exam408-co",
        "co": "exam408-co",
        "exam408-co": "exam408-co",
        "计算机网络": "exam408-cn",
        "cn": "exam408-cn",
        "exam408-cn": "exam408-cn",
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
        subject = self.normalize_subject(raw.get("subject") or raw.get("科目"))
        previous_plain_math = getattr(self, "_plain_math_options", False)
        self._plain_math_options = plain_math
        try:
            options = self.normalize_options(
                raw.get("options") or raw.get("选项") or raw.get("parsed_options")
            )
        finally:
            self._plain_math_options = previous_plain_math
        blank_option_groups = self.normalize_blank_option_groups(
            raw.get("blank_option_groups") or (raw.get("parsed_content") or {}).get("blank_option_groups") or []
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
        stem = normalize_text_import_math(stem) if plain_math else wrap_inline_math(stem)
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
        # OCR quality gate on cleaned stem
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
            "subject": subject,
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
            "question_hash": self.build_question_hash(stem, options, answer, blank_option_groups=blank_option_groups),
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
                    isinstance(s, dict) and "option_group" in str(s.get("region_type", ""))
                    for s in raw_seg_check
                )
        normalized.update(self.validate(normalized))

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
                normalized["source_snapshot_url"] = raw_parsed_content["source_snapshot_url"]
            if raw_parsed_content.get("source_snapshot_full_page"):
                normalized["source_snapshot_full_page"] = raw_parsed_content["source_snapshot_full_page"]

        # 统一验证字段 (Goal: 所有导题入口输出一致)
        is_valid = normalized["is_valid"]
        errors = normalized["errors"]
        normalized["validation_status"] = "passed" if is_valid else "failed"
        normalized["failure_reason"] = list(errors) if errors else None
        normalized["retry_recommended"] = (
            not is_valid
            and any("missing_option_" in e for e in errors)
        )
        normalized["ocr_quality_flags"] = _ocr_gate_result["ocr_quality_flags"]
        if not _ocr_gate_result["passed"]:
            normalized["warnings"].append("ocr_contamination_detected")
            for flag in _ocr_gate_result["ocr_quality_flags"]:
                normalized["warnings"].append(f"ocr_quality:{flag}")

        return normalized

    def normalize_subject(self, value: Any) -> str:
        subject = str(value or "").strip()
        return self.SUBJECT_ALIASES.get(
            subject, subject if subject in self.VALID_SUBJECTS else ""
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
            elif question_type == "multi_blank_choice":
                from app.features.multi_blank_choice import (
                    extract_blank_slots,
                    parse_multi_blank_answer,
                    serialize_multi_blank_answer,
                )
                slot_ids = extract_blank_slots(text)
                if slot_ids:
                    parsed, _ = parse_multi_blank_answer(text, slot_ids=slot_ids, allow_positional=True)
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
                    items.append((key, {"text": text_val, "segments": v.get("segments")}))
                else:
                    items.append((key, str(v).strip()))
        elif isinstance(options, list):
            for item in options:
                if isinstance(item, dict):
                    key = item.get("key") or item.get("label") or item.get("option")
                    text = item.get("text") or item.get("value") or item.get("content") or ""
                    if isinstance(text, dict):
                        items.append(
                            (str(key).strip().upper() if key else None, text)
                        )
                    else:
                        items.append(
                            (str(key).strip().upper() if key else None, str(text).strip())
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
                cleaned_text = normalize_text_import_math(cleaned_text, compact=plain_math) if plain_math else wrap_inline_math(cleaned_text)
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
                text = normalize_text_import_math(text, compact=plain_math) if plain_math else wrap_inline_math(text)
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
        text = re.sub(r"^\d+\s*[.、)）]\s*", "", text)
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
            # （1）（2）全角括号数字，前面有非空白字符时换行
            line = re.sub(r"(?<=[^\s])[　 ]*([（][0-9]+[）])", r"\n\1", line)
            # 1) 2) 数字+括号，排除数学表达式(0,1)和全角括号（1）的误匹配
            line = re.sub(r"(?<=[^\s\d,（(])[　 ]*(\d+[)）])(?=\s*[一-鿟\w])", r"\n\1", line)
            result.append(line)
        return "\n".join(result)

    def clean_analysis(self, text: Any) -> str:
        text = self.clean_text(text)
        text = re.sub(r"^(?:【)?(?:答案解析|解析|解答)(?:】)?\s*[：:]\s*", "", text)
        return text.strip()

    def validate(self, question: dict) -> dict:
        errors: list[str] = []
        warnings: list[str] = []
        if not question.get("stem"):
            errors.append("stem_empty")
        if not question.get("answer") and question.get("question_type") != "multi_blank_choice":
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
        if question.get("question_type") == "multi_blank_choice":
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
        if not question.get("subject"):
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
                    text = item.get("text") or item.get("value") or item.get("content") or ""
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
        self, stem: Any, options: Any, answer: Any,
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
        segments = question.get("segments") or (question.get("parsed_content") or {}).get("segments")
        render_mode = question.get("parsed_content", {}).get("render_mode") if isinstance(question.get("parsed_content"), dict) else None
        if segments:
            parsed_content["render_mode"] = render_mode or "segments"
            parsed_content["segments"] = segments
        # Preserve source_snapshot_url and full_page flag
        if question.get("source_snapshot_url"):
            parsed_content["source_snapshot_url"] = question["source_snapshot_url"]
        if question.get("source_snapshot_full_page"):
            parsed_content["source_snapshot_full_page"] = question["source_snapshot_full_page"]
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
        q_segments = question.get("segments") or (question.get("parsed_content") or {}).get("segments")
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
    _TRAILING_OP_RE = re.compile(
        r'(?:<=|>=|==|!=|&&|\|\||<<|>>|[<>=!+\-*/%&|^])\s*$'
    )
    # Operator + word at line end → operand was split from its continuation
    #  while (x < n\n/ 2) → merge n/2 back
    _OP_THEN_WORD_END_RE = re.compile(r'[<>=!+\-*/%&|^]\s+\w+\s*$')

    # Next-line patterns that are clearly NOT operands (statement boundaries).
    _CODE_KW_RE = re.compile(
        r'^\s*(?:if|else|while|for|do|switch|case|return|break|continue|'
        r'int|float|double|char|void|long|short|struct|enum|typedef|'
        r'public|private|protected|class|static|const|virtual)\b'
    )

    def _line_ends_broken(self, line: str) -> bool:
        stripped = line.rstrip()
        if not stripped:
            return False
        if not re.search(r'[{};=()[\]<>!&|]', stripped):
            return False
        return bool(
            self._TRAILING_OP_RE.search(stripped) or self._OP_THEN_WORD_END_RE.search(stripped)
        )

    def _line_starts_continuation(self, line: str) -> bool:
        stripped = line.lstrip()
        if not stripped:
            return False
        if stripped[0] in '{};':
            return False
        if self._CODE_KW_RE.match(stripped):
            return False
        # Starts with an operator character → continuation of broken expression
        if stripped[0] in '+*/%&|^<>!=~':
            return True
        # Contains code operators/separators but not a new statement
        return bool(re.search(r'[+\-*/%<>=!&|(){};\[\]]', stripped))

    def _normalize_code_newlines(self, text: str) -> str:
        """Merge code lines that were split inside expressions by AI normalization.

        Detects patterns like ``while (x < n\\n/ 2)`` where the newline sits
        between an operator and its operand, and rejoins them with a space.
        """
        if '\n' not in text:
            return text
        lines = text.split('\n')
        result: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if i + 1 < len(lines) and self._line_ends_broken(line) and self._line_starts_continuation(lines[i + 1]):
                merged = line.rstrip() + ' ' + lines[i + 1].lstrip()
                result.append(merged)
                i += 2
            else:
                result.append(line)
                i += 1
        return '\n'.join(result)

    def _is_noise_line(self, line: str) -> bool:
        if re.fullmatch(r"第?\s*\d+\s*页\s*(?:/\s*共?\s*\d+\s*页?)?", line):
            return True
        if re.fullmatch(r"[-—_=]{3,}", line):
            return True
        # Repeating-character separators (xxxxxxxxxx, ==========, etc.) — boundary artifact
        if re.fullmatch(r"([A-Za-z0-9])\1{4,}", line):
            return True
        if len(line) <= 2 and not re.search(r"[一-鿿A-Za-z0-9{}\[\]()]", line):
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
        {"source_type": source_type, "source": source, "raw_keys": list(raw_input.keys())},
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
            normalizer.to_question_fields(normalized) if normalized["is_valid"] else None
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
    subject: str | None,
    question_hash: str | None,
    subject_id: int | None = None,
) -> Question | None:
    if not question_hash:
        return None
    conditions = [Question.question_hash == question_hash, Question.is_active]
    if subject_id is not None:
        conditions.append(Question.subject_id == subject_id)
    elif subject:
        from app.services.admin_subject_service import resolve_subject_id
        resolved = await resolve_subject_id(db, subject)
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
    subject: str | None,
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
    elif subject:
        from app.services.admin_subject_service import resolve_subject_id
        resolved = await resolve_subject_id(db, subject)
        if resolved is not None:
            conditions.append(QuestionImport.subject_id == resolved)
        else:
            return None
    else:
        return None
    result = await db.execute(
        select(QuestionImport).where(*conditions)
    )
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
    db: AsyncSession, subject: str | None, stem: str
) -> Question | None:
    """兼容旧调用：同 subject 下用 stem hash + 相似度查疑似重复题。"""
    if not subject or not stem:
        return None
    from app.services.admin_subject_service import resolve_subject_id
    resolved_id = await resolve_subject_id(db, subject)
    if resolved_id is None:
        return None
    result = await db.execute(
        select(Question).where(
            Question.subject_id == resolved_id, Question.is_active
        )
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


def _refresh_duplicate_question_display_fields(
    duplicate: Question, question_fields: dict | None
) -> bool:
    if not duplicate or not question_fields:
        return False

    changed = False
    clean_content = question_fields.get("content")
    clean_options = question_fields.get("options")

    if clean_content and duplicate.content != clean_content:
        duplicate.content = clean_content
        changed = True
    if clean_options and duplicate.options != clean_options:
        duplicate.options = clean_options
        changed = True

    return changed


# ============================================================
# 三、Excel / PDF 解析
# ============================================================


def _parse_excel_row(row: list, headers: list) -> dict | None:
    """Moved to question_import_writer.py (P5-3)."""
    from app.features.question_import_writer import _parse_excel_row as _impl
    return _impl(row, headers)


def _parse_excel(content: bytes, filename: str) -> list[dict]:
    wb = load_workbook(io.BytesIO(content), read_only=True)
    ws = wb.active
    if ws is None:
        return []
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        return []
    headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(rows[0])]
    results: list[dict] = []
    for row in rows[1:]:
        raw = _parse_excel_row(list(row), headers)
        if raw:
            results.append(raw)
    return results


_PDF_SUBJECT_KEYWORDS = {
    "exam408-ds": [
        "数据结构", "二叉树", "栈", "队列", "排序", "查找", "链表", "图论",
        "哈夫曼", "邻接矩阵", "邻接表", "散列", "hash", "深度优先", "广度优先",
        "二分查找", "插入排序", "归并排序", "快速排序", "堆排序",
    ],
    "exam408-os": [
        "操作系统", "进程", "线程", "信号量", "死锁", "调度算法",
        "页表", "虚拟内存", "缺页", "tlb", "文件系统", "i/o",
        "互斥", "同步", "管程", "临界区", "时间片", "fcfs", "rr",
    ],
    "exam408-co": [
        "cpu", "存储器", "主存", "指令", "中断", "dma", "cache", "流水线",
        "微指令", "寻址", "补码", "原码", "浮点", "运算器", "控制器",
        "总线", "字长", "定长指令", "条件转移",
    ],
    "exam408-cn": [
        "网络层", "tcp", "ip地址", "路由", "码分", "频分", "csma",
        "局域网", "以太网", "传输层", "应用层", "数据链路",
        "拥塞", "三次握手", "udp", "http", "dns", "子网掩码",
    ],
    "exam408": [
        "算法", "计算机", "时间复杂度", "空间复杂度",
    ],
    "math2-calculus": [
        "极限", "导数", "积分", "微分方程", "lim",
        "连续", "可导", "定积分", "不定积分", "偏导",
        "极大值", "极小值", "拐点", "渐近线", "曲率",
        "泰勒", "罗尔", "拉格朗日", "中值定理",
    ],
    "math2-linalg": [
        "矩阵", "向量", "行列式", "特征值", "二次型",
        "线性代数", "相似矩阵", "正交", "秩", "线性方程组",
        "线性相关", "线性无关", "特征向量",
    ],
    "math2": [
        "函数", "微积分",
    ],
    "english": [
        "reading comprehension", "passage", "paragraph", "translate",
        "词汇", "完形填空", "阅读理解", "写作",
        "according to the passage", "which of the following",
    ],
}


def _guess_subject(text: str, *, min_score: int = 2) -> str | None:
    """根据关键词出现频次猜测科目。子科目得分会同时累加到父科目。"""
    if not text:
        return None
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for subj, words in _PDF_SUBJECT_KEYWORDS.items():
        for w in words:
            if w in text_lower:
                scores[subj] = scores.get(subj, 0) + 1

    if not scores:
        return None
    best = max(scores, key=scores.get)
    if scores[best] < min_score:
        # 单关键词命中，先回退父科目；都没有就放弃
        if scores[best] >= 1:
            if best.startswith("exam408-"):
                return "exam408"
            if best.startswith("math2-"):
                return "math2"
            if best in ("math2", "exam408", "english"):
                return best
        return None
    return best


def _extract_pdf_text(content: bytes) -> str:
    """双通道提取 PDF 全文：文本型直接提取，图片型页面走 OCR。"""
    from app.services.ocr_service import clean_ocr_text, ocr_pages
    from app.services.pdf_classifier import classify_pages, get_pixmap

    classified = classify_pages(content)
    page_texts: dict[int, str] = {}
    ocr_targets: list[tuple[int, bytes]] = []
    for p in classified:
        if not p["needs_ocr"]:
            page_texts[p["page_index"]] = p["text"]
        elif settings.OCR_ENABLED and p["_page"] is not None:
            try:
                png = get_pixmap(p["_page"])
                ocr_targets.append((p["page_index"], png))
            except Exception as e:
                logger.warning("PDF 第 %d 页渲染失败，跳过：%s", p["page_index"], e)
                page_texts[p["page_index"]] = ""

    if ocr_targets:
        ocr_results = ocr_pages(ocr_targets)
        from app.services.formula_normalizer import fix_ocr_formula
        for idx, raw_text in ocr_results.items():
            page_texts[idx] = fix_ocr_formula(clean_ocr_text(raw_text))

    return "\n".join(page_texts.get(i, "") for i in range(len(classified)))


_ANSWER_RE = re.compile(r"^(?:【)?(?:参考|正确)?答案(?:】)?\s*[：:](.*)$")
_ANALYSIS_RE = re.compile(r"^(?:【)?(?:解析|解答)(?:】)?\s*[：:](.*)")
_OPT_INLINE_RE = re.compile(
    r"([A-D])[.、:：）]\s*([^A-D]*?)(?=\s+[A-D][.、:：）]|$)"
)


def _parse_option_line(line: str) -> dict | None:
    if re.search(r"[A-D][.、:：）].+[A-D][.、:：）]", line):
        found = _OPT_INLINE_RE.findall(line)
        if found:
            return {letter: text.strip() for letter, text in found}
    m = re.match(r"^([A-D])\s*[.、:：）]\s*(.*)", line)
    if m:
        return {m.group(1): m.group(2).strip()}
    m2 = re.match(r"^[（(]\s*([A-D])\s*[）)]\s*(.*)", line)
    if m2:
        return {m2.group(1): m2.group(2).strip()}
    return None


def _parse_pdf(content: bytes, filename: str) -> list[dict]:
    """解析 PDF（文本型 + 扫描版 OCR），按题号切分。"""
    from app.services.formula_normalizer import fix_ocr_formula
    from app.services.pdf_text_normalizer import normalize_pdf_text

    text = _extract_pdf_text(content)
    if not text.strip():
        raise ValueError("PDF 中未提取到文本内容（文本型和 OCR 均无结果）")
    text = normalize_pdf_text(text)
    text = fix_ocr_formula(text)
    default_subject = _guess_subject(text, min_score=2)

    blocks = re.split(r"\n\s*(?=\d+\s*[.、)）])", text)
    blocks = [b.strip() for b in blocks if len(b.strip()) > 20]

    splitter_questions = split_questions(
        [{"normalized_text": text, "page": 1, "block_index": 0}],
        import_mode="pdf",
    )
    grouped_options_by_number = {
        item.get("number"): item.get("blank_option_groups")
        for item in splitter_questions
        if item.get("number") and item.get("blank_option_groups")
    }

    def _stem_key(line: str) -> str:
        """规范化行内容用于去重：去题号前缀、折叠空白。"""
        k = re.sub(r"^\d+\s*[.、)）]\s*", "", line).strip()
        return re.sub(r"\s+", " ", k)

    results: list[dict] = []
    for block in blocks:
        question_number = None
        number_match = re.match(r"^(\d+)\s*[.、)）]", block)
        if number_match:
            question_number = int(number_match.group(1))
        stem_lines: list[str] = []
        stem_seen: set[str] = set()
        options: dict = {}
        answer = ""
        analysis = ""
        section = "stem"

        for line in block.split("\n"):
            line = line.strip()
            if not line:
                continue
            if section in ("stem", "options"):
                parsed_opts = _parse_option_line(line)
                if parsed_opts:
                    for k, v in parsed_opts.items():
                        if k not in options:
                            options[k] = v
                    section = "options"
                    continue
            ana_match = _ANALYSIS_RE.match(line)
            if ana_match and section != "analysis":
                analysis = ana_match.group(1).strip()
                section = "analysis"
                continue
            if section != "analysis":
                ans_match = _ANSWER_RE.match(line)
                if ans_match:
                    answer = ans_match.group(1).strip()
                    section = "answer"
                    continue
            if section == "analysis":
                analysis = analysis + "\n" + line if analysis else line
            elif section == "stem":
                key = _stem_key(line)
                if key not in stem_seen:
                    stem_seen.add(key)
                    stem_lines.append(line)

        stem = "\n".join(stem_lines)
        stem = re.sub(r"^\d+\s*[.、)）]\s*", "", stem)
        stem = re.sub(
            r"^[（(]\s*(单选|多选|选择|填空|判断|简答|论述|计算)题?[）)]\s*",
            "",
            stem,
        )
        stem = stem.strip()
        if len(stem) < 5:
            continue

        options_str = (
            "\\n".join(f"{k}:{v}" for k, v in sorted(options.items()))
            if options
            else ""
        )
        blank_option_groups = grouped_options_by_number.get(question_number) or []
        per_question_subject = (
            _guess_subject(stem + " " + analysis, min_score=1) or default_subject
        )
        results.append({
            "subject": per_question_subject,
            "stem": stem,
            "options": "" if blank_option_groups else options_str,
            "blank_option_groups": blank_option_groups,
            "answer": answer,
            "explanation": analysis,
            "question_type": "multi_blank_choice" if blank_option_groups else (QT_SINGLE_CHOICE if options else (
                QT_TRUE_FALSE if re.search(r"[（(]\s*判断题?\s*[）)]|^\s*判断题?[：:]", stem) else QT_FILL_BLANK
            )),
        })

    if not results:
        raise ValueError("未能从 PDF 中解析出有效题目，请检查文件格式")
    return results


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
    res = await db.execute(
        select(QuestionImport).where(QuestionImport.id == import_id)
    )
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
        "subject": qi.subject_ref.code if qi.subject_ref else qi.subject_id,
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
    brace = re.search(r"(\{.*\})", text, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(1))
        except json.JSONDecodeError:
            pass
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
    messages: list, fallback_value: dict, db: AsyncSession | None = None,
    *, api_key: str | None = None, base_url: str | None = None, model_name: str | None = None,
) -> tuple[dict, str | None, dict | None]:
    if api_key is None and db is not None:
        from app.services.model_config_resolver import ensure_db_model_configured
        creds = await ensure_db_model_configured(db, feature="completion")
        api_key = creds[0] if creds else None
        base_url = creds[1] if creds else None
        model_name = creds[2] if creds else None

    if not (api_key or deepseek.is_available()):
        return (
            {
                "content": "", "tokens_used": 0, "model": "fallback",
                "duration_ms": 0, "fallback_value": fallback_value,
                "error": "AI模型API Key未配置",
            },
            None, None,
        )
    try:
        resp = await deepseek.chat(messages, model=model_name, api_key=api_key, base_url=base_url)
        return (resp, resp["content"], resp)
    except RuntimeError as e:
        return (
            {
                "content": "", "tokens_used": 0, "model": "fallback",
                "duration_ms": 0, "fallback_value": fallback_value,
                "error": str(e),
            },
            None, None,
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


# ============================================================
# P5-3: backward-compatible re-exports from extracted modules
# ============================================================
# These make ``from app.features.question_pipeline import fn``
# continue to work after the P5-3 extraction.
#
# ⚠️ CIRCULAR IMPORT BOUNDARY ⚠️
# ``question_import_writer.py`` also imports from this module
# (``_QI_PARSED_FIELDS``, ``_find_duplicate_by_hash``, etc.).
# Those symbols MUST be defined BEFORE this line (they are:
# ``_QI_PARSED_FIELDS`` at line 1123, ``_find_duplicate_by_hash``
# at line 769). Any new cross-module symbol that ``question_import_writer``
# needs must also be placed above this boundary.
# ============================================================

# question_import_writer MUST be imported first — question_draft_generator
# depends on _create_question_import which is re-exported from here.
from app.features.question_ai_complete import (  # noqa: E402, F401
    _has_complete_answer_risk,
    batch_complete_questions,
    complete_import,
    complete_import_with_strategy,
)
from app.features.question_ai_enrich import (  # noqa: E402, F401
    enrich_batch,
    enrich_import,
)
from app.features.question_draft_generator import generate_drafts  # noqa: E402, F401
from app.features.question_import_writer import (  # noqa: E402, F401
    _apply_duplicate_fields,
    _build_import_duplicate_fields,
    _create_question_import,
    _guess_subject,
    _parse_excel,
    _parse_pdf,
    _refresh_import_duplicate_status,
    approve_question,
    batch_approve,
    generate_template,
    get_batch_detail,
    import_excel,
    import_pdf,
    list_batches,
    reject_question,
)

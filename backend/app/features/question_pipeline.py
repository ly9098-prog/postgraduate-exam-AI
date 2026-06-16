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
import uuid
from datetime import datetime
from typing import Any

from openpyxl import Workbook, load_workbook
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import fallback
from app.ai.client import deepseek
from app.ai.prompts import (
    build_batch_complete_question,
    build_complete_question,
    build_enrich_question,
    build_generate_questions,
)
from app.core.config import settings
from app.models.ai_generation_log import AiGenerationLog
from app.models.question import Question
from app.models.question_import import QuestionImport
from app.features.question_splitter import split_questions
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
    CANONICAL_TYPES = {
        "single_choice",
        "multiple_choice",
        "true_false",
        "fill_blank",
        "multi_blank_choice",
        "subjective",
    }
    TYPE_ALIASES = {
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
        from app.services.formula_normalizer import normalize_text_import_math, wrap_inline_math

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
        if question_type != "multi_blank_choice":
            stem = self._break_before_number_markers(stem)
        stem = self._remove_embedded_options(stem, options)
        answer = self.normalize_answer(
            raw.get("answer") or raw.get("答案") or raw.get("parsed_answer") or "",
            question_type,
        )
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
            "question_hash": self.build_question_hash(stem, options, answer),
            "is_valid": True,
            "errors": [],
            "warnings": [],
        }
        normalized.update(self.validate(normalized))
        return normalized

    def normalize_subject(self, value: Any) -> str:
        subject = str(value or "").strip()
        return self.SUBJECT_ALIASES.get(
            subject, subject if subject in self.VALID_SUBJECTS else ""
        )

    def normalize_type(self, value: Any, options: Any = None) -> str:
        raw_type = str(value or "").strip().lower().replace("-", "_").replace(" ", "")
        if raw_type in self.TYPE_ALIASES:
            return self.TYPE_ALIASES[raw_type]
        if raw_type in self.CANONICAL_TYPES:
            return raw_type
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
        items: list[tuple[str | None, str]] = []
        if isinstance(options, dict):
            items = [(str(k).strip().upper(), str(v).strip()) for k, v in options.items()]
        elif isinstance(options, list):
            for item in options:
                if isinstance(item, dict):
                    key = item.get("key") or item.get("label") or item.get("option")
                    text = item.get("text") or item.get("value") or item.get("content") or ""
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
        from app.services.formula_normalizer import normalize_text_import_math, wrap_inline_math

        plain_math = bool(getattr(self, "_plain_math_options", False))
        for key, text in items:
            text = self.clean_text(text)
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
        return self._merge_broken_lines(text).strip()

    @staticmethod
    def _break_before_number_markers(text: str) -> str:
        """在题号标记前插入换行：① ② ...、（1）（2）...、1) 2) ..."""
        # ①-⑳ 圈号标记
        text = re.sub(r"(?<![（(\n])([①-⑳])", r"\n\1", text)
        # （1）（2）全角括号数字，前面有非空白字符时换行
        text = re.sub(r"(?<=[^\s])[　 ]*([（][0-9]+[）])", r"\n\1", text)
        # 1) 2) 数字+括号，排除数学表达式(0,1)和全角括号（1）的误匹配
        text = re.sub(r"(?<=[^\s\d,（(])[　 ]*(\d+[)）])(?=\s*[一-鿟\w])", r"\n\1", text)
        return text

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
            if not question.get("options"):
                errors.append("options_empty")
            elif len(question["options"]) < 2:
                warnings.append("options_too_few")
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

    def build_question_hash(self, stem: Any, options: Any, answer: Any) -> str:
        payload = "||".join(
            [
                self.normalize_hash_text(stem),
                self.normalize_hash_options(options),
                self.normalize_hash_answer(answer),
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
        parsed_content = {"text": question["stem"]}
        if question.get("blank_option_groups"):
            parsed_content["blank_option_groups"] = question["blank_option_groups"]
        return {
            "subject": question["subject"] or None,
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
        return {
            "subject": fields["subject"],
            "question_type": fields["question_type"],
            "content": fields["parsed_content"],
            "options": fields["parsed_options"],
            "answer": fields["parsed_answer"] or "",
            "analysis": fields["parsed_analysis"],
            "question_hash": question.get("question_hash") or None,
            "knowledge_points": fields["knowledge_points"],
            "difficulty": fields["difficulty"],
        }

    def options_to_dict(self, options: list[dict]) -> dict | None:
        result = {item["key"]: item["text"] for item in options if item.get("text")}
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
        if prev[-1] in "。！？；…":
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
        return True

    def _is_noise_line(self, line: str) -> bool:
        if re.fullmatch(r"第?\s*\d+\s*页\s*(?:/\s*共?\s*\d+\s*页?)?", line):
            return True
        if re.fullmatch(r"[-—_=]{3,}", line):
            return True
        if len(line) <= 2 and not re.search(r"[一-鿿A-Za-z0-9{}\[\]()]", line):
            return True
        return False


normalizer = QuestionNormalizer()

SUBJECT_VALUES = QuestionNormalizer.VALID_SUBJECTS
TYPE_VALUES = QuestionNormalizer.CANONICAL_TYPES | {"choice", "fill", "subjective"}


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
) -> Question | None:
    if not subject or not question_hash:
        return None
    result = await db.execute(
        select(Question).where(
            Question.subject == subject,
            Question.question_hash == question_hash,
            Question.is_active == True,
        )
    )
    return result.scalar_one_or_none()


async def _find_import_duplicate_by_hash(
    db: AsyncSession,
    subject: str | None,
    question_hash: str | None,
) -> QuestionImport | None:
    if not subject or not question_hash:
        return None
    result = await db.execute(
        select(QuestionImport).where(
            QuestionImport.subject == subject,
            QuestionImport.question_hash == question_hash,
            QuestionImport.status != "rejected",
        )
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
    result = await db.execute(
        select(Question).where(
            Question.subject == subject, Question.is_active == True
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
    raw: dict = {}
    has_value = False
    for i, h in enumerate(headers):
        val = row[i] if i < len(row) else None
        if isinstance(val, str):
            val = val.strip()
        if val is not None and val != "":
            has_value = True
        raw[h] = val
    return raw if has_value else None


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
    from app.services.pdf_classifier import classify_pages, get_pixmap
    from app.services.ocr_service import ocr_pages, clean_ocr_text

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
            "question_type": "multi_blank_choice" if blank_option_groups else ("choice" if options else (
                "true_false" if re.search(r"[（(]\s*判断题?\s*[）)]|^\s*判断题?[：:]", stem) else "fill"
            )),
        })

    if not results:
        raise ValueError("未能从 PDF 中解析出有效题目，请检查文件格式")
    return results


# ============================================================
# 四、导入主流程（Excel / PDF / 审核）
# ============================================================


_QI_PARSED_FIELDS = (
    "subject",
    "question_type",
    "parsed_content",
    "parsed_options",
    "parsed_answer",
    "parsed_analysis",
)


async def _build_import_duplicate_fields(
    db: AsyncSession,
    *,
    import_id: int | None,
    subject: str | None,
    question_hash: str | None,
) -> dict:
    duplicate_fields = {
        "question_hash": question_hash or None,
        "duplicate_status": "normal",
        "duplicate_of_question_id": None,
        "duplicate_of_import_id": None,
    }
    result_label = "normal"
    matched_id = None

    duplicate_question = await _find_duplicate_by_hash(db, subject, question_hash)
    if duplicate_question and not hasattr(duplicate_question, "id"):
        duplicate_question = None
    if duplicate_question:
        duplicate_fields["duplicate_status"] = "possible_duplicate"
        duplicate_fields["duplicate_of_question_id"] = duplicate_question.id
        result_label = "matched_question"
        matched_id = duplicate_question.id
    else:
        duplicate_import = await _find_import_duplicate_by_hash(db, subject, question_hash)
        if duplicate_import and not hasattr(duplicate_import, "id"):
            duplicate_import = None
        if duplicate_import and duplicate_import.id != import_id:
            duplicate_fields["duplicate_status"] = "possible_duplicate"
            duplicate_fields["duplicate_of_import_id"] = duplicate_import.id
            result_label = "matched_import"
            matched_id = duplicate_import.id

    logger.info(
        "[DuplicateCheck] questionId=%s importId=%s hash=%s result=%s matchedId=%s",
        None,
        import_id,
        question_hash or "",
        result_label,
        matched_id,
    )
    return duplicate_fields


def _apply_duplicate_fields(qi: QuestionImport, duplicate_fields: dict) -> None:
    qi.question_hash = duplicate_fields["question_hash"]
    qi.duplicate_status = duplicate_fields["duplicate_status"]
    qi.duplicate_of_question_id = duplicate_fields["duplicate_of_question_id"]
    qi.duplicate_of_import_id = duplicate_fields["duplicate_of_import_id"]


async def _refresh_import_duplicate_status(
    db: AsyncSession,
    qi: QuestionImport,
    question_hash: str | None,
) -> None:
    duplicate_fields = await _build_import_duplicate_fields(
        db,
        import_id=qi.id,
        subject=qi.subject,
        question_hash=question_hash,
    )
    _apply_duplicate_fields(qi, duplicate_fields)


async def _create_question_import(
    db: AsyncSession,
    *,
    batch_id: str,
    source_type: str,
    source_file: str | None,
    raw_data: dict,
    result: dict,
    extra_fields: dict | None = None,
    skip_existing: bool = False,
) -> QuestionImport | None:
    question_hash = result["normalized"].get("question_hash")
    subject = result["import_fields"].get("subject")

    if skip_existing and question_hash and subject:
        existing = await _find_duplicate_by_hash(db, subject, question_hash)
        if existing:
            logger.info(
                "[DuplicateFilter] 跳过已存在的题目 subject=%s hash=%s existing_id=%s",
                subject,
                question_hash,
                existing.id,
            )
            return None
        existing_import = await _find_import_duplicate_by_hash(db, subject, question_hash)
        if existing_import:
            logger.info(
                "[DuplicateFilter] 跳过审核池中已存在的题目 subject=%s hash=%s existing_import_id=%s",
                subject,
                question_hash,
                existing_import.id,
            )
            return None

    qi = QuestionImport(
        batch_id=batch_id,
        source_type=source_type,
        source_file=source_file,
        raw_data=raw_data,
        status="pending",
        question_hash=question_hash or None,
        **{k: v for k, v in result["import_fields"].items() if k in _QI_PARSED_FIELDS},
        **(extra_fields or {}),
    )
    db.add(qi)
    await db.flush()
    await _refresh_import_duplicate_status(
        db, qi, question_hash,
    )
    return qi


async def import_excel(
    db: AsyncSession, content: bytes, filename: str
) -> tuple[str, int]:
    raw_rows = _parse_excel(content, filename)
    if not raw_rows:
        raise ValueError("Excel 文件为空或格式不正确")

    batch_id = f"BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    imported = 0
    skipped_duplicates = 0
    for row in raw_rows:
        result = process_question_pipeline(
            row, "excel", {"file": filename, "page": 0}
        )
        if not result["is_valid"]:
            continue
        qi = await _create_question_import(
            db,
            batch_id=batch_id,
            source_type="excel",
            source_file=filename,
            raw_data=row,
            result=result,
            skip_existing=True,
        )
        if qi is None:
            skipped_duplicates += 1
            continue
        imported += 1
    await db.commit()
    if skipped_duplicates:
        logger.info("[DuplicateFilter] Excel导入跳过 %d 道重复题目", skipped_duplicates)
    return batch_id, imported


async def import_pdf(
    db: AsyncSession, content: bytes, filename: str, background_tasks=None
) -> tuple[str, int]:
    raw_rows = _parse_pdf(content, filename)
    batch_id = f"BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    imported = 0
    skipped_duplicates = 0
    for row in raw_rows:
        result = process_question_pipeline(
            row, "pdf", {"file": filename, "page": row.get("page", 0)}
        )
        if not result["is_valid"]:
            continue
        qi = await _create_question_import(
            db,
            batch_id=batch_id,
            source_type="pdf",
            source_file=filename,
            raw_data=row,
            result=result,
            skip_existing=True,
        )
        if qi is None:
            skipped_duplicates += 1
            continue
        imported += 1
    await db.commit()
    if skipped_duplicates:
        logger.info("[DuplicateFilter] PDF导入跳过 %d 道重复题目", skipped_duplicates)
    return batch_id, imported


async def approve_question(
    db: AsyncSession, import_id: int, data: dict
) -> dict:
    """审核通过单题并写入正式题库。返回 {qi, is_duplicate, question_id}。"""
    qi = await _get_qi(db, import_id)
    if qi.status != "pending":
        raise ValueError("该记录已审核")

    ai_meta = qi.ai_metadata or {}
    knowledge_points = data.get("knowledge_points")
    if knowledge_points is None:
        ai_kps = ai_meta.get("knowledge_points") if isinstance(ai_meta, dict) else None
        if isinstance(ai_kps, list) and ai_kps:
            knowledge_points = ai_kps
    difficulty = data.get("difficulty")
    if difficulty is None:
        ai_diff = ai_meta.get("difficulty") if isinstance(ai_meta, dict) else None
        if isinstance(ai_diff, int) and 1 <= ai_diff <= 5:
            difficulty = ai_diff

    raw = {
        "subject": data.get("subject", qi.subject),
        "question_type": data.get("question_type", qi.question_type),
        "parsed_content": data.get("parsed_content", qi.parsed_content),
        "parsed_options": data.get("parsed_options", qi.parsed_options),
        "parsed_answer": data.get("parsed_answer", qi.parsed_answer),
        "parsed_analysis": data.get("parsed_analysis", qi.parsed_analysis),
        "knowledge_points": knowledge_points,
        "difficulty": difficulty,
    }
    result = process_question_pipeline(
        raw, "manual", {"file": qi.source_file or "", "page": 0}
    )
    if not result["is_valid"]:
        raise ValueError(f"题目标准化失败：{', '.join(result['errors'])}")

    # 更新 qi 中可能被修改的字段（审核时用户可能修改了 subject/answer）
    if data.get("subject"):
        qi.subject = data["subject"]
    if data.get("parsed_answer"):
        qi.parsed_answer = data["parsed_answer"]

    # 直接写入 questions 正式题库（审核通过即发布）
    await _refresh_import_duplicate_status(
        db, qi, result["normalized"].get("question_hash")
    )
    duplicate = await _find_duplicate_by_hash(
        db, result["normalized"]["subject"], result["normalized"]["question_hash"]
    )
    is_duplicate = False
    if duplicate:
        logger.info(
            "[DuplicateCheck] questionId=%s importId=%s hash=%s result=matched_question matchedId=%s",
            duplicate.id,
            qi.id,
            result["normalized"]["question_hash"],
            duplicate.id,
        )
        qi.status = "published"
        qi.question_id = duplicate.id
        is_duplicate = True
    else:
        q = Question(
            **result["question_fields"],
            source=qi.source_file,
            source_type=qi.source_type,
            source_file=qi.source_file,
            import_batch_id=qi.batch_id,
            raw_content=str(qi.raw_data),
            review_status="approved",
            is_active=True,
        )
        db.add(q)
        await db.flush()
        await db.refresh(q)
        qi.status = "published"
        qi.question_id = q.id
        logger.info(
            "[Review Pass] import_id=%s → question_id=%s subject=%s",
            qi.id, q.id, q.subject,
        )

    qi.review_note = data.get("review_note")
    if qi.ai_generated:
        qi.ai_reviewed_at = datetime.utcnow()
    await db.commit()
    return {"qi": qi, "is_duplicate": is_duplicate, "question_id": qi.question_id}


async def reject_question(
    db: AsyncSession, import_id: int, note: str | None = None
) -> None:
    qi = await _get_qi(db, import_id)
    if qi.status != "pending":
        raise ValueError("该记录已审核")
    qi.status = "rejected"
    qi.review_note = note
    await db.commit()


async def batch_approve(db: AsyncSession, batch_id: str) -> tuple[int, dict[int, list[str]]]:
    res = await db.execute(
        select(QuestionImport).where(
            QuestionImport.batch_id == batch_id,
            QuestionImport.status == "pending",
        )
    )
    records = list(res.scalars().all())
    count = 0
    skipped: dict[int, list[str]] = {}
    for qi in records:
        ai_meta = qi.ai_metadata or {}
        kps = ai_meta.get("knowledge_points") if isinstance(ai_meta, dict) else None
        diff = ai_meta.get("difficulty") if isinstance(ai_meta, dict) else None
        result = process_question_pipeline(
            {
                "subject": qi.subject,
                "question_type": qi.question_type,
                "parsed_content": qi.parsed_content,
                "parsed_options": qi.parsed_options,
                "parsed_answer": qi.parsed_answer,
                "parsed_analysis": qi.parsed_analysis,
                "knowledge_points": kps,
                "difficulty": diff,
            },
            "manual",
            {"file": qi.source_file or "", "page": 0},
        )
        if not result["is_valid"]:
            skipped[qi.id] = result["errors"]
            continue

        # 写入 questions 正式题库
        await _refresh_import_duplicate_status(
            db, qi, result["normalized"].get("question_hash")
        )
        duplicate = await _find_duplicate_by_hash(
            db, result["normalized"]["subject"], result["normalized"]["question_hash"]
        )
        if duplicate:
            qi.status = "published"
            qi.question_id = duplicate.id
            logger.info(
                "[DuplicateCheck] questionId=%s importId=%s hash=%s result=matched_question matchedId=%s",
                duplicate.id,
                qi.id,
                result["normalized"]["question_hash"],
                duplicate.id,
            )
        else:
            q = Question(
                **result["question_fields"],
                source=qi.source_file,
                source_type=qi.source_type,
                source_file=qi.source_file,
                import_batch_id=qi.batch_id,
                raw_content=str(qi.raw_data),
                review_status="approved",
                is_active=True,
            )
            db.add(q)
            await db.flush()
            await db.refresh(q)
            qi.status = "published"
            qi.question_id = q.id
            logger.info(
                "[Batch Approve] import_id=%s → question_id=%s subject=%s",
                qi.id, q.id, q.subject,
            )
        if qi.ai_generated:
            qi.ai_reviewed_at = datetime.utcnow()
        count += 1

    await db.commit()
    logger.info(
        "[Batch Approve] batch_id=%s total=%d approved=%d skipped=%d",
        batch_id, len(records), count, len(skipped),
    )
    if skipped:
        details = "; ".join(
            f"#{qid} 缺{'、'.join(fields)}" for qid, fields in skipped.items()
        )
        logger.warning("[Batch Approve] skipped detail: %s", details)
    return count, skipped


async def list_batches(db: AsyncSession) -> list[dict]:
    stmt = (
        select(
            QuestionImport.batch_id,
            QuestionImport.source_type,
            QuestionImport.source_file,
            func.count(QuestionImport.id).label("total"),
            func.sum(case((QuestionImport.status == "pending", 1), else_=0)).label("pending"),
            func.sum(case((QuestionImport.status.in_(["approved", "published"]), 1), else_=0)).label("approved"),
            func.sum(case((QuestionImport.status == "rejected", 1), else_=0)).label("rejected"),
            func.max(QuestionImport.created_at).label("created_at"),
        )
        .group_by(
            QuestionImport.batch_id,
            QuestionImport.source_type,
            QuestionImport.source_file,
        )
        .order_by(func.max(QuestionImport.created_at).desc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "batch_id": r.batch_id,
            "source_type": r.source_type,
            "source_file": r.source_file,
            "total": r.total,
            "pending": r.pending,
            "approved": r.approved,
            "rejected": r.rejected,
            "created_at": r.created_at,
        }
        for r in rows
    ]


async def get_batch_detail(
    db: AsyncSession, batch_id: str
) -> list[QuestionImport]:
    res = await db.execute(
        select(QuestionImport)
        .where(QuestionImport.batch_id == batch_id)
        .order_by(QuestionImport.id)
    )
    return list(res.scalars().all())


def generate_template() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "导入模板"
    headers = [
        "subject", "question_type", "stem", "options",
        "answer", "explanation", "difficulty", "tags",
    ]
    ws.append(headers)
    ws.append([
        "math2", "single_choice", "设函数 $f(x)=x^2+1$，求 $f'(x)$。",
        "A:$2x$\\nB:$x^2$\\nC:$2x+1$\\nD:$x$",
        "A", "根据求导公式，$(x^2+1)'=2x$。", "2", "导数,求导公式",
    ])
    for i, w in enumerate([12, 14, 40, 50, 10, 40, 10, 25], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


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
    return {
        "subject": qi.subject,
        "question_type": qi.question_type,
        "parsed_content": qi.parsed_content,
        "parsed_options": qi.parsed_options,
        "parsed_answer": qi.parsed_answer,
        "parsed_analysis": qi.parsed_analysis,
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
    if not qi.subject:
        missing.append("subject")
    if not qi.question_type:
        missing.append("question_type")
    if not (qi.parsed_content and qi.parsed_content.get("text")):
        missing.append("stem")
    if not qi.parsed_answer:
        missing.append("answer")
    if not qi.parsed_analysis:
        missing.append("analysis")
    return missing


def _normalize_enrich(parsed: dict) -> dict:
    out: dict = {}
    subject = parsed.get("subject")
    if subject in SUBJECT_VALUES:
        out["subject"] = subject
    qtype = parsed.get("question_type")
    normalized_type = normalizer.normalize_type(qtype)
    if normalized_type:
        out["question_type"] = normalized_type
    diff = parsed.get("difficulty")
    if isinstance(diff, (int, float)):
        diff = int(diff)
        if 1 <= diff <= 5:
            out["difficulty"] = diff
    kps = parsed.get("knowledge_points")
    if isinstance(kps, list):
        out["knowledge_points"] = [str(k).strip() for k in kps if str(k).strip()]
    chapter = parsed.get("chapter")
    if isinstance(chapter, str) and chapter.strip():
        out["chapter"] = chapter.strip()
    cat = parsed.get("question_category")
    if isinstance(cat, str) and cat.strip():
        out["question_category"] = cat.strip()
    conf = parsed.get("confidence")
    if isinstance(conf, (int, float)):
        out["confidence"] = max(0.0, min(1.0, float(conf)))
    reason = parsed.get("reason")
    if isinstance(reason, str):
        out["reason"] = reason
    return out


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
    messages: list, fallback_value: dict, db: AsyncSession | None = None
) -> tuple[dict, str | None, dict | None]:
    creds = None
    if db is not None:
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
                "error": "DEEPSEEK_API_KEY 未配置",
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


async def enrich_import(
    db: AsyncSession, user_id: int, import_id: int
) -> dict:
    qi = await _get_qi(db, import_id)
    if qi.status != "pending":
        raise ValueError("仅支持对 pending 记录使用 AI 辅助")

    messages = build_enrich_question(_qi_to_dict(qi))
    prompt_text = json.dumps(messages, ensure_ascii=False)
    resp, raw, _ = await _call_or_fallback(messages, fallback.get_fallback_enrich(), db)

    if raw is None:
        parsed = resp["fallback_value"]
        db.add(_build_log(
            user_id=user_id, action="enrich", target_type="import",
            target_id=qi.id, batch_id=qi.batch_id, prompt_text=prompt_text,
            raw_response=None, parsed_result=parsed,
            confidence=parsed.get("confidence"),
            model=resp["model"], tokens_used=0, duration_ms=0,
            success=False, error_message=resp.get("error"),
        ))
        await db.commit()
        return {"from_fallback": True, "ai_metadata": parsed}

    normalized = _normalize_enrich(_extract_json(raw) or {})
    if normalized.get("subject") and not qi.subject:
        qi.subject = normalized["subject"]
    if normalized.get("question_type") and not qi.question_type:
        qi.question_type = normalized["question_type"]
    qi.ai_generated = True
    qi.ai_source = "enrich"
    qi.ai_confidence = normalized.get("confidence")
    qi.ai_metadata = normalized
    qi.ai_raw_response = raw

    db.add(_build_log(
        user_id=user_id, action="enrich", target_type="import",
        target_id=qi.id, batch_id=qi.batch_id, prompt_text=prompt_text,
        raw_response=raw, parsed_result=normalized,
        confidence=normalized.get("confidence"),
        model=resp["model"], tokens_used=resp["tokens_used"],
        duration_ms=resp["duration_ms"], success=True,
    ))
    await db.commit()
    return {
        "from_fallback": False,
        "ai_metadata": normalized,
        "tokens_used": resp["tokens_used"],
        "duration_ms": resp["duration_ms"],
    }


async def enrich_batch(
    db: AsyncSession, user_id: int, batch_id: str, limit: int = 50
) -> dict:
    res = await db.execute(
        select(QuestionImport)
        .where(
            QuestionImport.batch_id == batch_id,
            QuestionImport.status == "pending",
        )
        .limit(limit)
    )
    records = list(res.scalars().all())
    if not records:
        return {"processed": 0, "succeeded": 0, "fallback": 0}
    succeeded = 0
    fallback_count = 0
    for qi in records:
        try:
            r = await enrich_import(db, user_id, qi.id)
        except ValueError:
            continue
        if r.get("from_fallback"):
            fallback_count += 1
        else:
            succeeded += 1
    return {
        "processed": len(records),
        "succeeded": succeeded,
        "fallback": fallback_count,
    }


async def generate_drafts(
    db: AsyncSession,
    user_id: int,
    *,
    subject: str,
    knowledge_points: list[str],
    difficulty: int = 3,
    count: int = 3,
    question_type: str = "single_choice",
    extra_hint: str | None = None,
) -> dict:
    if subject not in SUBJECT_VALUES:
        raise ValueError("subject 仅支持 math2 / exam408 / english")
    question_type = normalizer.normalize_type(question_type)
    if question_type not in TYPE_VALUES:
        raise ValueError(
            "question_type 仅支持 single_choice / multiple_choice / "
            "true_false / fill_blank / subjective"
        )
    count = max(1, min(10, count))

    batch_id = f"AIGEN_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    messages = build_generate_questions(
        subject, knowledge_points, difficulty, count, question_type, extra_hint
    )
    prompt_text = json.dumps(messages, ensure_ascii=False)
    resp, raw, _ = await _call_or_fallback(
        messages, fallback.get_fallback_generation(count), db
    )

    if raw is None:
        db.add(_build_log(
            user_id=user_id, action="generate", target_type="batch",
            target_id=None, batch_id=batch_id, prompt_text=prompt_text,
            raw_response=None, parsed_result=resp["fallback_value"],
            confidence=0.0,
            model=resp["model"], tokens_used=0, duration_ms=0,
            success=False, error_message=resp.get("error"),
        ))
        await db.commit()
        return {"batch_id": batch_id, "generated": 0, "from_fallback": True}

    parsed_raw = _extract_json(raw) or {}
    questions = parsed_raw.get("questions") if isinstance(parsed_raw, dict) else None
    if not isinstance(questions, list):
        questions = []

    generated = 0
    skipped_duplicate = 0
    for q in questions:
        if not isinstance(q, dict):
            continue
        result = process_question_pipeline(q, "ai")
        if not result["is_valid"]:
            continue
        norm = result["normalized"]
        qi = await _create_question_import(
            db,
            batch_id=batch_id,
            source_type="ai_generated",
            source_file=None,
            raw_data=q,
            result=result,
            extra_fields={
                "ai_generated": True,
                "ai_source": "generate",
                "ai_metadata": {
                    "knowledge_points": norm["knowledge_points"],
                    "difficulty": norm["difficulty"],
                    "request": {
                        "subject": subject,
                        "knowledge_points": knowledge_points,
                        "difficulty": difficulty,
                        "question_type": question_type,
                    },
                },
                "ai_raw_response": raw,
                "ai_answer_flag": bool(result["import_fields"].get("parsed_answer")),
            },
            skip_existing=True,
        )
        if qi is None:
            skipped_duplicate += 1
            continue
        generated += 1

    db.add(_build_log(
        user_id=user_id, action="generate", target_type="batch",
        target_id=None, batch_id=batch_id, prompt_text=prompt_text,
        raw_response=raw, parsed_result={"count": generated, "skipped_duplicate": skipped_duplicate},
        confidence=None,
        model=resp["model"], tokens_used=resp["tokens_used"],
        duration_ms=resp["duration_ms"], success=True,
    ))
    await db.commit()
    return {
        "batch_id": batch_id,
        "generated": generated,
        "skipped_duplicate": skipped_duplicate,
        "from_fallback": False,
        "tokens_used": resp["tokens_used"],
        "duration_ms": resp["duration_ms"],
    }


async def complete_import(
    db: AsyncSession, user_id: int, import_id: int
) -> dict:
    qi = await _get_qi(db, import_id)
    if qi.status != "pending":
        raise ValueError("仅支持对 pending 记录使用 AI 补全")

    missing = _detect_missing(qi)
    if not missing:
        return {"missing": [], "from_fallback": False, "ai_metadata": {}}

    messages = build_complete_question(_qi_to_dict(qi), missing)
    prompt_text = json.dumps(messages, ensure_ascii=False)
    resp, raw, _ = await _call_or_fallback(
        messages, fallback.get_fallback_complete(missing), db
    )

    if raw is None:
        parsed = resp["fallback_value"]
        db.add(_build_log(
            user_id=user_id, action="complete", target_type="import",
            target_id=qi.id, batch_id=qi.batch_id, prompt_text=prompt_text,
            raw_response=None, parsed_result=parsed, confidence=0.0,
            model=resp["model"], tokens_used=0, duration_ms=0,
            success=False, error_message=resp.get("error"),
        ))
        await db.commit()
        return {"missing": missing, "from_fallback": True, "ai_metadata": parsed}

    parsed_raw = _extract_json(raw) or {}
    suggestion = _apply_complete_suggestion(qi, parsed_raw, missing)
    answer_uncertain = bool(parsed_raw.get("answer_uncertain"))
    confidence = _coerce_confidence(parsed_raw.get("confidence"))

    qi.ai_generated = True
    qi.ai_source = "complete"
    qi.ai_confidence = confidence
    qi.ai_metadata = {
        **(qi.ai_metadata or {}),
        "complete_suggestion": suggestion,
        "answer_uncertain": answer_uncertain,
        "reason": parsed_raw.get("reason"),
        "missing_fields": missing,
    }
    qi.ai_raw_response = raw

    db.add(_build_log(
        user_id=user_id, action="complete", target_type="import",
        target_id=qi.id, batch_id=qi.batch_id, prompt_text=prompt_text,
        raw_response=raw, parsed_result=qi.ai_metadata,
        confidence=confidence,
        model=resp["model"], tokens_used=resp["tokens_used"],
        duration_ms=resp["duration_ms"], success=True,
    ))
    await db.commit()
    return {
        "missing": missing,
        "from_fallback": False,
        "ai_metadata": qi.ai_metadata,
        "tokens_used": resp["tokens_used"],
        "duration_ms": resp["duration_ms"],
    }


def _coerce_confidence(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    return None


def _apply_complete_suggestion(
    qi: QuestionImport, parsed: dict, missing: list[str]
) -> dict:
    suggestion: dict = {}
    if "subject" in missing and parsed.get("subject") in SUBJECT_VALUES:
        qi.subject = parsed["subject"]
        suggestion["subject"] = parsed["subject"]
    if "question_type" in missing and parsed.get("question_type") in TYPE_VALUES:
        qi.question_type = parsed["question_type"]
        suggestion["question_type"] = parsed["question_type"]
    if "analysis" in missing:
        a = parsed.get("analysis")
        if isinstance(a, str) and a.strip():
            qi.parsed_analysis = a.strip()
            suggestion["analysis"] = a.strip()
    if "answer" in missing:
        ans = parsed.get("answer")
        if isinstance(ans, str) and ans.strip():
            suggestion["answer"] = ans.strip()
            qi.ai_answer_flag = True
    if isinstance(parsed.get("knowledge_points"), list):
        suggestion["knowledge_points"] = [
            str(k).strip() for k in parsed["knowledge_points"] if str(k).strip()
        ]
    if isinstance(parsed.get("difficulty"), (int, float)):
        suggestion["difficulty"] = max(1, min(5, int(parsed["difficulty"])))
    return suggestion


def _detect_fields_to_complete(
    qi: QuestionImport, target_fields: list[str], strategy: str
) -> list[str]:
    """根据策略确定需要 AI 处理的字段列表。"""
    if strategy == "force_overwrite":
        return list(target_fields)

    need: list[str] = []
    for field in target_fields:
        if field == "subject" and not qi.subject:
            need.append("subject")
        elif field == "question_type" and not qi.question_type:
            need.append("question_type")
        elif field == "stem" and not (qi.parsed_content and qi.parsed_content.get("text")):
            need.append("stem")
        elif field == "answer" and not qi.parsed_answer:
            need.append("answer")
        elif field == "analysis" and not qi.parsed_analysis:
            need.append("analysis")
        elif field == "options" and not qi.parsed_options:
            need.append("options")
        elif field == "knowledge_points":
            meta = qi.ai_metadata or {}
            if not meta.get("knowledge_points"):
                need.append("knowledge_points")
        elif field == "difficulty":
            meta = qi.ai_metadata or {}
            if not meta.get("difficulty"):
                need.append("difficulty")
        elif field in ("tips", "tags"):
            meta = qi.ai_metadata or {}
            if not meta.get(field):
                need.append(field)
    return need


def _apply_batch_complete_result(
    qi: QuestionImport, parsed: dict, fields: list[str], strategy: str
) -> list[str]:
    """将 AI 结果应用到 QuestionImport 记录，返回实际完成的字段列表。"""
    completed: list[str] = []

    def _should_apply(field: str) -> bool:
        return strategy == "force_overwrite" or field in fields

    if "subject" in fields and parsed.get("subject") in SUBJECT_VALUES:
        qi.subject = parsed["subject"]
        completed.append("subject")

    if "question_type" in fields and parsed.get("question_type") in TYPE_VALUES:
        qi.question_type = parsed["question_type"]
        completed.append("question_type")

    if _should_apply("analysis"):
        a = parsed.get("analysis")
        if isinstance(a, str) and a.strip():
            qi.parsed_analysis = a.strip()
            completed.append("analysis")

    if "answer" in fields:
        ans = parsed.get("answer")
        if isinstance(ans, str) and ans.strip():
            qi.parsed_answer = ans
            qi.ai_answer_flag = True
            completed.append("answer")

    if "stem" in fields:
        stem_val = parsed.get("stem") or (parsed.get("parsed_content") or {}).get("text")
        if isinstance(stem_val, str) and stem_val.strip():
            content = dict(qi.parsed_content or {})
            content["text"] = stem_val.strip()
            qi.parsed_content = content
            completed.append("stem")

    if "options" in fields:
        opts = parsed.get("options") or parsed.get("parsed_options")
        if isinstance(opts, dict) and opts:
            qi.parsed_options = opts
            completed.append("options")
        elif isinstance(opts, list) and opts:
            qi.parsed_options = {str(i): o for i, o in enumerate(opts) if o}
            completed.append("options")

    qi.ai_generated = True
    qi.ai_source = "batch_complete"
    ai_meta = dict(qi.ai_metadata or {})

    if "knowledge_points" in fields:
        kps = parsed.get("knowledge_points")
        if isinstance(kps, list) and kps:
            ai_meta["knowledge_points"] = [str(k).strip() for k in kps if str(k).strip()]
            completed.append("knowledge_points")

    if "difficulty" in fields:
        diff = parsed.get("difficulty")
        if isinstance(diff, (int, float)):
            ai_meta["difficulty"] = max(1, min(5, int(diff)))
            completed.append("difficulty")

    if "tips" in fields:
        tips = parsed.get("tips") or parsed.get("solving_tips")
        if isinstance(tips, str) and tips.strip():
            ai_meta["tips"] = tips.strip()
            completed.append("tips")

    if "tags" in fields:
        tags = parsed.get("tags")
        if isinstance(tags, list) and tags:
            ai_meta["tags"] = [str(t).strip() for t in tags if str(t).strip()]
            completed.append("tags")

    qi.ai_metadata = ai_meta
    return completed


async def complete_import_with_strategy(
    db: AsyncSession,
    user_id: int,
    import_id: int,
    target_fields: list[str],
    strategy: str,
) -> dict:
    """带字段选择和策略的 AI 补全。不提交事务，供 batch 调用。"""
    qi = await _get_qi(db, import_id)
    if qi.status != "pending":
        return {"completed": [], "from_fallback": False, "ai_metadata": {}, "error": f"非 pending 状态: {qi.status}"}

    to_complete = _detect_fields_to_complete(qi, target_fields, strategy)
    if not to_complete:
        return {"completed": [], "from_fallback": False, "ai_metadata": {}}

    messages = build_batch_complete_question(_qi_to_dict(qi), to_complete, strategy)
    prompt_text = json.dumps(messages, ensure_ascii=False)
    resp, raw, _ = await _call_or_fallback(
        messages, fallback.get_fallback_complete(to_complete), db
    )

    if raw is None:
        parsed = resp["fallback_value"]
        db.add(_build_log(
            user_id=user_id, action="batch_complete", target_type="import",
            target_id=qi.id, batch_id=qi.batch_id, prompt_text=prompt_text,
            raw_response=None, parsed_result=parsed, confidence=0.0,
            model=resp["model"], tokens_used=0, duration_ms=0,
            success=False, error_message=resp.get("error"),
        ))
        return {"completed": [], "from_fallback": True, "ai_metadata": parsed, "error": resp.get("error")}

    parsed_raw = _extract_json(raw) or {}
    completed = _apply_batch_complete_result(qi, parsed_raw, to_complete, strategy)
    confidence = _coerce_confidence(parsed_raw.get("confidence"))

    qi.ai_confidence = confidence
    qi.ai_raw_response = raw

    db.add(_build_log(
        user_id=user_id, action="batch_complete", target_type="import",
        target_id=qi.id, batch_id=qi.batch_id, prompt_text=prompt_text,
        raw_response=raw, parsed_result=qi.ai_metadata,
        confidence=confidence,
        model=resp["model"], tokens_used=resp["tokens_used"],
        duration_ms=resp["duration_ms"], success=True,
    ))
    return {
        "completed": completed,
        "from_fallback": False,
        "ai_metadata": qi.ai_metadata,
        "tokens_used": resp["tokens_used"],
        "duration_ms": resp["duration_ms"],
    }


async def batch_complete_questions(
    db: AsyncSession,
    user_id: int,
    import_ids: list[int],
    target_fields: list[str],
    strategy: str,
) -> dict:
    """批量 AI 补全。外部需自行 commit。"""
    succeeded = 0
    failed = 0
    skipped = 0
    results: list[dict] = []

    for import_id in import_ids:
        try:
            r = await complete_import_with_strategy(
                db, user_id, import_id, target_fields, strategy
            )
            if r.get("completed"):
                succeeded += 1
            elif r.get("error"):
                failed += 1
            else:
                skipped += 1
            results.append({
                "import_id": import_id,
                "status": "success" if r.get("completed") else ("skipped" if not r.get("error") else "failed"),
                "error": r.get("error"),
                "completed_fields": r.get("completed", []),
            })
        except ValueError as e:
            failed += 1
            results.append({
                "import_id": import_id,
                "status": "failed",
                "error": str(e),
                "completed_fields": [],
            })
        except Exception as e:
            failed += 1
            results.append({
                "import_id": import_id,
                "status": "failed",
                "error": str(e),
                "completed_fields": [],
            })

    return {
        "total": len(import_ids),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "items": results,
    }


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

"""Direct CSV import for published ``questions`` rows.

The CSV format is intentionally compatible with exports of the ``questions``
table from both SQLite and PostgreSQL. Source primary keys and
``current_version_id`` are never reused: target databases allocate their own
keys and a fresh immutable revision is created for every inserted question.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.question_type import CANONICAL_TYPES
from app.models.admin import QuestionVersion, Subject
from app.models.question import Question
from app.services.question_revision_service import compute_question_state_hash

MAX_QUESTIONS_CSV_BYTES = 100 * 1024 * 1024
MAX_QUESTIONS_CSV_ROWS = 100_000
_SQLITE_SAFE_IN_CHUNK = 500

_REQUIRED_COLUMNS = {"content", "answer", "subject_id"}

@dataclass(slots=True)
class ParsedQuestionRow:
    line_no: int
    values: dict[str, Any]


@dataclass(slots=True)
class QuestionCsvImportResult:
    total_rows: int
    inserted_count: int
    skipped_count: int
    first_question_id: int | None
    last_question_id: int | None


class QuestionCsvValidationError(ValueError):
    """Raised when the CSV cannot be imported safely as question rows."""


def _chunks(values: list[Any], size: int = _SQLITE_SAFE_IN_CHUNK) -> Iterable[list[Any]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _optional_text(value: str | None, *, max_length: int | None = None, field: str = "字段") -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if max_length is not None and len(text) > max_length:
        raise QuestionCsvValidationError(f"{field} 长度不能超过 {max_length}")
    return text


def _parse_int(
    value: str | None,
    *,
    field: str,
    required: bool = False,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    text = (value or "").strip()
    if not text:
        if required:
            raise QuestionCsvValidationError(f"{field} 不能为空")
        return None
    try:
        parsed = int(text)
    except ValueError as exc:
        raise QuestionCsvValidationError(f"{field} 必须是整数") from exc
    if minimum is not None and parsed < minimum:
        raise QuestionCsvValidationError(f"{field} 不能小于 {minimum}")
    if maximum is not None and parsed > maximum:
        raise QuestionCsvValidationError(f"{field} 不能大于 {maximum}")
    return parsed


def _parse_bool(value: str | None, *, default: bool = True) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return default
    if text in {"1", "true", "t", "yes", "y", "是"}:
        return True
    if text in {"0", "false", "f", "no", "n", "否"}:
        return False
    raise QuestionCsvValidationError("is_active 必须是 true/false、t/f、1/0 或 yes/no")


def _parse_json(
    value: str | None,
    *,
    field: str,
    required: bool = False,
    expected_type: type | tuple[type, ...] | None = None,
) -> Any:
    text = (value or "").strip()
    if not text:
        if required:
            raise QuestionCsvValidationError(f"{field} 不能为空")
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise QuestionCsvValidationError(f"{field} 不是合法 JSON") from exc
    if required and parsed is None:
        raise QuestionCsvValidationError(f"{field} 不能为 null")
    if parsed is not None and expected_type is not None and not isinstance(parsed, expected_type):
        type_name = "对象" if expected_type is dict else "数组"
        raise QuestionCsvValidationError(f"{field} 必须是 JSON {type_name}")
    return parsed


_ODD_EXPORT_SUFFIX_RE = re.compile(r"\.\-?1f$")


def _parse_datetime(value: str | None, *, field: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None

    # Some SQLite/GUI exports in the supplied dataset append ``.-1f`` to second
    # precision timestamps. It is formatting noise, not a fractional second.
    text = _ODD_EXPORT_SUFFIX_RE.sub("", text)
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    if parsed is None:
        for fmt in (
            "%d/%m/%Y %H:%M:%S.%f",
            "%d/%m/%Y %H:%M:%S",
            "%Y/%m/%d %H:%M:%S.%f",
            "%Y/%m/%d %H:%M:%S",
        ):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise QuestionCsvValidationError(f"{field} 时间格式无法识别")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _parse_row(row: dict[str, str | None], line_no: int, subject_override: int | None) -> ParsedQuestionRow:
    question_type = (row.get("question_type") or "single_choice").strip() or "single_choice"
    if question_type not in CANONICAL_TYPES:
        raise QuestionCsvValidationError(f"question_type 非法: {question_type}")

    subject_id = subject_override or _parse_int(
        row.get("subject_id"), field="subject_id", required=True, minimum=1
    )
    assert subject_id is not None

    content = _parse_json(row.get("content"), field="content", required=True, expected_type=dict)
    options = _parse_json(row.get("options"), field="options", expected_type=dict)
    image_url = _parse_json(row.get("image_url"), field="image_url", expected_type=list)

    difficulty = _parse_int(
        row.get("difficulty"), field="difficulty", minimum=1, maximum=5
    )
    year = _parse_int(
        row.get("year"), field="year", minimum=-32768, maximum=32767
    )
    sync_version = _parse_int(
        row.get("sync_version"), field="sync_version", minimum=0, maximum=2147483647
    )

    review_status = _optional_text(
        row.get("review_status"), max_length=16, field="review_status"
    ) or "approved"
    sync_uuid = _optional_text(row.get("sync_uuid"), max_length=36, field="sync_uuid")
    if sync_uuid is None:
        sync_uuid = str(uuid4())

    answer = row.get("answer")
    if answer is None:
        raise QuestionCsvValidationError("answer 列不能为空")

    values: dict[str, Any] = {
        "subject_id": subject_id,
        "question_type": question_type,
        "content": content,
        "options": options,
        "answer": answer,
        "question_hash": _optional_text(row.get("question_hash"), max_length=32, field="question_hash"),
        "analysis": _optional_text(row.get("analysis")),
        "difficulty": difficulty if difficulty is not None else 3,
        "source": _optional_text(row.get("source"), max_length=64, field="source"),
        "source_type": _optional_text(row.get("source_type"), max_length=16, field="source_type"),
        "source_file": _optional_text(row.get("source_file"), max_length=256, field="source_file"),
        "import_batch_id": _optional_text(row.get("import_batch_id"), max_length=64, field="import_batch_id"),
        "raw_content": _optional_text(row.get("raw_content")),
        "image_url": image_url,
        "year": year,
        "review_status": review_status,
        "is_active": _parse_bool(row.get("is_active"), default=True),
        "sync_uuid": sync_uuid,
        "sync_version": sync_version if sync_version is not None else 0,
    }
    created_at = _parse_datetime(row.get("created_at"), field="created_at")
    updated_at = _parse_datetime(row.get("updated_at"), field="updated_at")
    if created_at is not None:
        values["created_at"] = created_at
    if updated_at is not None:
        values["updated_at"] = updated_at
    elif created_at is not None:
        values["updated_at"] = created_at

    return ParsedQuestionRow(line_no=line_no, values=values)


def parse_questions_csv(path: str, *, subject_override: int | None = None) -> list[ParsedQuestionRow]:
    """Parse and validate a questions CSV without touching the database."""
    file_path = Path(path)
    try:
        handle = file_path.open("r", encoding="utf-8-sig", newline="")
    except UnicodeError as exc:
        raise QuestionCsvValidationError("CSV 必须使用 UTF-8 编码") from exc

    rows: list[ParsedQuestionRow] = []
    errors: list[str] = []
    data_row_count = 0
    try:
        with handle:
            reader = csv.DictReader(handle)
            headers = [str(item or "").strip() for item in (reader.fieldnames or [])]
            if not headers:
                raise QuestionCsvValidationError("CSV 缺少表头")
            missing = sorted(_REQUIRED_COLUMNS.difference(headers))
            if subject_override is not None:
                missing = [name for name in missing if name != "subject_id"]
            if missing:
                raise QuestionCsvValidationError(f"CSV 缺少必需列: {', '.join(missing)}")

            for line_no, row in enumerate(reader, start=2):
                if None in row:
                    if len(errors) < 20:
                        errors.append(f"第 {line_no} 行: 数据列数超过表头列数")
                    continue
                # Ignore completely empty physical rows.
                if not any(str(value or "").strip() for value in row.values()):
                    continue
                data_row_count += 1
                if data_row_count > MAX_QUESTIONS_CSV_ROWS:
                    raise QuestionCsvValidationError(
                        f"CSV 行数超过限制（最多 {MAX_QUESTIONS_CSV_ROWS} 行）"
                    )
                try:
                    rows.append(_parse_row(row, line_no, subject_override))
                except QuestionCsvValidationError as exc:
                    if len(errors) < 20:
                        errors.append(f"第 {line_no} 行: {exc}")
    except UnicodeDecodeError as exc:
        raise QuestionCsvValidationError("CSV 必须使用 UTF-8 编码") from exc
    except csv.Error as exc:
        raise QuestionCsvValidationError(f"CSV 格式错误: {exc}") from exc

    if errors:
        suffix = "" if len(errors) < 20 else "；仅显示前 20 个错误"
        raise QuestionCsvValidationError("；".join(errors) + suffix)
    if not rows:
        raise QuestionCsvValidationError("CSV 中没有可导入的数据行")
    return rows


async def _load_existing_sync_uuids(db: AsyncSession, sync_uuids: list[str]) -> set[str]:
    existing: set[str] = set()
    unique_values = list(dict.fromkeys(sync_uuids))
    for chunk in _chunks(unique_values):
        result = await db.execute(select(Question.sync_uuid).where(Question.sync_uuid.in_(chunk)))
        existing.update(str(value) for value in result.scalars().all() if value)
    return existing


async def import_questions_csv(
    db: AsyncSession,
    path: str,
    *,
    subject_override: int | None = None,
    admin_id: int | None = None,
) -> QuestionCsvImportResult:
    """Validate then import CSV rows atomically into ``questions``.

    Rows whose ``sync_uuid`` already exists are skipped, making re-import of the
    same export idempotent. Source ``id`` and ``current_version_id`` are ignored
    because they belong to another database's key space.
    """
    parsed_rows = parse_questions_csv(path, subject_override=subject_override)

    subject_ids = sorted({int(item.values["subject_id"]) for item in parsed_rows})
    existing_subjects: set[int] = set()
    for subject_chunk in _chunks(subject_ids):
        subject_result = await db.execute(
            select(Subject.id).where(Subject.id.in_(subject_chunk))
        )
        existing_subjects.update(int(value) for value in subject_result.scalars().all())
    missing_subjects = [value for value in subject_ids if value not in existing_subjects]
    if missing_subjects:
        raise QuestionCsvValidationError(
            "以下 subject_id 在目标数据库中不存在: " + ", ".join(map(str, missing_subjects))
        )

    incoming_sync_uuids = [str(item.values["sync_uuid"]) for item in parsed_rows]
    existing_sync_uuids = await _load_existing_sync_uuids(db, incoming_sync_uuids)

    seen_sync_uuids: set[str] = set()
    questions: list[Question] = []
    skipped_count = 0
    for item in parsed_rows:
        sync_uuid = str(item.values["sync_uuid"])
        if sync_uuid in existing_sync_uuids or sync_uuid in seen_sync_uuids:
            skipped_count += 1
            continue
        seen_sync_uuids.add(sync_uuid)
        questions.append(Question(**item.values))

    if not questions:
        return QuestionCsvImportResult(
            total_rows=len(parsed_rows),
            inserted_count=0,
            skipped_count=skipped_count,
            first_question_id=None,
            last_question_id=None,
        )

    db.add_all(questions)
    await db.flush()

    question_ids = [int(question.id) for question in questions]
    latest_versions: dict[int, int] = {}
    for question_id_chunk in _chunks(question_ids):
        version_result = await db.execute(
            select(QuestionVersion.question_id, func.max(QuestionVersion.version))
            .where(QuestionVersion.question_id.in_(question_id_chunk))
            .group_by(QuestionVersion.question_id)
        )
        latest_versions.update(
            {
                int(question_id): int(version or 0)
                for question_id, version in version_result.all()
            }
        )

    revisions: list[QuestionVersion] = []
    for question in questions:
        question_id = int(question.id)
        revisions.append(
            QuestionVersion(
                question_id=question_id,
                version=latest_versions.get(question_id, 0) + 1,
                subject_id=int(question.subject_id),
                question_type=str(question.question_type or ""),
                image_url=question.image_url,
                is_active=bool(question.is_active),
                source=question.source,
                source_type=question.source_type,
                source_file=question.source_file,
                raw_content=question.raw_content,
                year=question.year,
                content=question.content,
                options=question.options,
                answer=str(question.answer or ""),
                analysis=question.analysis,
                difficulty=int(question.difficulty or 3),
                edited_by=admin_id,
                change_source="csv_import",
                state_hash=compute_question_state_hash(question, []),
                edit_reason="questions CSV import",
            )
        )
    db.add_all(revisions)
    await db.flush()

    for question, revision in zip(questions, revisions, strict=True):
        question.current_version_id = int(revision.id)
    await db.flush()

    ids = [int(question.id) for question in questions]
    return QuestionCsvImportResult(
        total_rows=len(parsed_rows),
        inserted_count=len(questions),
        skipped_count=skipped_count,
        first_question_id=min(ids),
        last_question_id=max(ids),
    )

"""Stage 8 导入流水线编排 — 串联 Stage 1-7 模块。

Pipeline stages:
    extract → normalize_text → split → match → normalize_schema → [repair] → review

Features:
- Task state tracking per stage
- Error isolation (single question failure doesn't block others)
- AI repair toggle via config
- Background execution with in-memory state store
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any

from app.features.ai_repair import repair_questions
from app.features.ai_validation import validate_ai_results
from app.features.answer_matcher import match_answers
from app.features.ocr_correction import correct_ocr_blocks
from app.features.question_normalizer import normalize_questions
from app.features.question_splitter import split_questions
from app.features.similarity_matcher import match_similar_questions
from app.features.structure_analyzer import analyze_structure
from app.features.text_normalizer import ImportTextNormalizer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# in-memory pipeline state store
# ---------------------------------------------------------------------------

_pipeline_store: dict[str, dict] = {}

_MAX_STORE_SIZE = 500  # keep at most N pipelines in memory


def _prune_store() -> None:
    """Remove oldest entries when store exceeds max size."""
    if len(_pipeline_store) > _MAX_STORE_SIZE:
        sorted_ids = sorted(
            _pipeline_store.keys(),
            key=lambda k: _pipeline_store[k].get("started_at", ""),
        )
        for old_id in sorted_ids[: len(_pipeline_store) - _MAX_STORE_SIZE]:
            del _pipeline_store[old_id]


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------


def _extract_pdf_blocks(content: bytes) -> list[dict]:
    """Extract text blocks from PDF using PyMuPDF.

    Returns list of {page, block_index, text} for use as raw_blocks input
    to ImportTextNormalizer.
    """
    try:
        import fitz
    except ImportError:
        raise RuntimeError("PyMuPDF (fitz) 未安装，无法提取 PDF 文本")

    doc = fitz.open(stream=content, filetype="pdf")
    blocks: list[dict] = []
    try:
        for i, page in enumerate(doc):
            text = page.get_text()
            if text.strip():
                blocks.append({
                    "page": i + 1,
                    "block_index": i,
                    "text": text.strip(),
                })
    finally:
        doc.close()

    if not blocks:
        raise ValueError("PDF 中未提取到文本内容")

    return blocks


def _ocr_scanned_pdf(content: bytes) -> list[dict]:
    """用 PaddleOCR 识别扫描版 PDF 各页。

    同步调用，内部通过 ThreadPoolExecutor 并发处理多页。
    输出格式与 _extract_pdf_blocks() 一致：[{page, block_index, text}]
    """
    import fitz

    from app.services.ocr_service import clean_ocr_text, ocr_pages

    doc = fitz.open(stream=content, filetype="pdf")
    page_images: list[tuple[int, bytes]] = []
    try:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=200)
            page_images.append((i + 1, pix.tobytes("png")))
    finally:
        doc.close()

    if not page_images:
        return []

    ocr_results = ocr_pages(page_images)
    blocks: list[dict] = []
    for page_idx in sorted(ocr_results.keys()):
        text = clean_ocr_text(ocr_results[page_idx])
        if text.strip():
            blocks.append({
                "page": page_idx,
                "block_index": len(blocks),
                "text": text,
            })
    return blocks


def _extract_text_blocks(content: bytes) -> list[dict]:
    """Extract text blocks from plain text content."""
    text = content.decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError("文本内容为空")
    return [{"page": 1, "block_index": 0, "text": text}]


# ---------------------------------------------------------------------------
# PipelineStage
# ---------------------------------------------------------------------------


class PipelineStage:
    """单个阶段的执行单元，记录状态、耗时和警告。"""

    def __init__(self, name: str, fn):
        self.name = name
        self.fn = fn
        self.status = "pending"  # pending → running → completed | failed
        self.duration_ms = 0
        self.warnings: list[str] = []
        self.error: str | None = None

    def run(self, **kwargs):
        """同步执行阶段（阻塞）。"""
        self.status = "running"
        start = time.monotonic()
        try:
            result = self.fn(**kwargs)
            self.status = "completed"
            self.duration_ms = round((time.monotonic() - start) * 1000)
            return result
        except Exception as exc:
            self.status = "failed"
            self.error = str(exc)
            self.duration_ms = round((time.monotonic() - start) * 1000)
            raise

    async def run_async(self, **kwargs):
        """异步执行阶段。"""
        self.status = "running"
        start = time.monotonic()
        try:
            if asyncio.iscoroutinefunction(self.fn):
                result = await self.fn(**kwargs)
            else:
                result = self.fn(**kwargs)
            self.status = "completed"
            self.duration_ms = round((time.monotonic() - start) * 1000)
            return result
        except Exception as exc:
            self.status = "failed"
            self.error = str(exc)
            self.duration_ms = round((time.monotonic() - start) * 1000)
            raise

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "warnings": self.warnings,
        }
        if self.error:
            d["error"] = self.error
        return d


# ---------------------------------------------------------------------------
# ImportPipeline
# ---------------------------------------------------------------------------


class ImportPipeline:
    """导入流水线，编排 Stage 1-7。

    使用方式::

        pipeline = ImportPipeline(options={"enable_ai_repair": True})
        result = await pipeline.run(
            file_content=pdf_bytes,
            source_type="pdf",
            source_file="exam.pdf",
            subject="math2",
            db=db_session,
        )
    """

    def __init__(self, options: dict | None = None):
        self.options = options or {}
        self.pipeline_id = ""
        self.stages: dict[str, PipelineStage] = {}

    def _build_pipeline(self) -> None:
        """(Re)build the stage list from current options.

        Called during __init__ and whenever options change at runtime.
        """
        stage_specs: list[tuple[str, callable]] = [
            ("extract", self._run_extract),
            ("normalize_text", self._run_normalize_text),
        ]
        if self.options.get("enable_ocr_correction", True):
            stage_specs.append(("ocr_correction", self._run_ocr_correction))
        stage_specs.extend([
            ("analyze_structure", self._run_analyze_structure),
            ("split", self._run_split),
            ("match", self._run_match),
            ("normalize_schema", self._run_normalize_schema),
        ])
        if self.options.get("enable_ai_repair", True):
            stage_specs.append(("repair", self._run_repair))
            stage_specs.append(("ai_validation", self._run_ai_validation))
        if self.options.get("enable_similarity_match", True):
            stage_specs.append(("similarity_match", self._run_similarity_match))
        stage_specs.append(("review", self._run_review))

        self.stages.clear()
        for name, fn in stage_specs:
            self.stages[name] = PipelineStage(name, fn)

    # ------------------------------------------------------------------
    # stage implementations
    # ------------------------------------------------------------------

    def _run_extract(self, file_content: bytes, source_type: str, **_kw) -> dict:
        """Extract raw text blocks from file content.

        For PDFs with very little extractable text (< 100 chars), triggers OCR
        fallback automatically when OCR_ENABLED is True.
        """
        if source_type == "pdf":
            raw_blocks = _extract_pdf_blocks(file_content)

            # Scanned PDF detection: if PyMuPDF extracted very little text,
            # the PDF likely contains only images → trigger OCR fallback.
            total_text = sum(len(b.get("text", "")) for b in raw_blocks)
            if total_text < 100:
                from app.core.config import settings

                if settings.OCR_ENABLED:
                    logger.info(
                        "PDF text only %d chars, attempting PaddleOCR fallback", total_text,
                    )
                    try:
                        ocr_blocks = _ocr_scanned_pdf(file_content)
                        if ocr_blocks:
                            raw_blocks = ocr_blocks
                            logger.info(
                                "OCR fallback succeeded: %d blocks", len(ocr_blocks),
                            )
                    except RuntimeError as exc:
                        logger.warning("OCR fallback unavailable: %s", exc)
                    except Exception as exc:
                        logger.warning(
                            "OCR fallback failed, using original extraction: %s", exc,
                        )
        else:
            raw_blocks = _extract_text_blocks(file_content)

        return {"raw_blocks": raw_blocks, "extracted": len(raw_blocks)}

    def _run_normalize_text(self, raw_blocks: list[dict], **_kw) -> dict:
        """Stage 1: text cleaning via ImportTextNormalizer."""
        normalizer = ImportTextNormalizer()
        normalized_blocks = normalizer.normalize(raw_blocks)

        warnings: list[str] = []
        empty_count = sum(1 for b in normalized_blocks if not b.get("normalized_text"))
        if empty_count:
            warnings.append(f"{empty_count} blocks empty after normalization")

        return {"normalized_blocks": normalized_blocks, "warnings": warnings}

    async def _run_ocr_correction(self, normalized_blocks: list[dict], options: dict | None = None, **_kw) -> dict:
        """Stage 1.5: AI OCR text correction for noisy blocks."""
        opts = options or {}
        correction_config = {
            "enabled": opts.get("enable_ocr_correction", True),
            "mode": opts.get("ocr_correction_mode", "auto"),
            "noise_threshold": opts.get("ocr_noise_threshold", 0.3),
            "daily_token_limit": opts.get("ocr_correction_daily_token_limit", 50000),
            "monthly_token_limit": opts.get("ocr_correction_monthly_token_limit", 1000000),
        }

        result = await correct_ocr_blocks(normalized_blocks, correction_config)

        warnings: list[str] = []
        stats = result.get("stats", {})
        if stats.get("corrected_blocks", 0) > 0:
            warnings.append(
                f"AI corrected {stats['corrected_blocks']}/{stats['total_blocks']} blocks"
            )
        if result.get("skipped_reason"):
            warnings.append(f"OCR correction skipped: {result['skipped_reason']}")

        return {
            "normalized_blocks": result["corrected_blocks"],
            "ocr_correction_diagnostics": {
                "stats": stats,
                "corrections": result.get("corrections", []),
                "skipped_reason": result.get("skipped_reason"),
            },
            "warnings": warnings,
        }

    def _run_analyze_structure(self, normalized_blocks: list[dict], **_kw) -> dict:
        """Stage 2: detect question/answer document layout."""
        structure = analyze_structure(normalized_blocks)
        return {"structure": structure, "warnings": []}

    def _run_split(self, normalized_blocks: list[dict], structure: dict | None = None, **_kw) -> dict:
        """Stage 3: split text blocks into individual questions."""
        raw_questions = split_questions(normalized_blocks, structure=structure)

        text_blocks = [
            b for b in normalized_blocks
            if str(b.get("normalized_text") or "").strip()
        ]
        split_diagnostics = {
            "normalized_block_count": len(normalized_blocks),
            "text_block_count": len(text_blocks),
            "raw_question_count": len(raw_questions),
            "raw_questions_preview": raw_questions[:20],
            "failure_reason": None,
        }

        warnings: list[str] = []
        if not raw_questions:
            if text_blocks:
                raw_questions = [{
                    "number": 1,
                    "raw_question_text": "\n".join(
                        str(b.get("normalized_text") or "").strip() for b in text_blocks
                    ),
                    "page_start": text_blocks[0].get("page", 1),
                    "page_end": text_blocks[-1].get("page", text_blocks[0].get("page", 1)),
                    "has_options": False,
                    "option_lines": {},
                    "confidence": 0.2,
                }]
                warnings.append("no questions found in document; created low-confidence review item")
                split_diagnostics["fallback_created"] = True
                split_diagnostics["failure_reason"] = "text_present_but_no_question_boundary"
            else:
                warnings.append("no questions found in document")
                split_diagnostics["fallback_created"] = False
                split_diagnostics["failure_reason"] = "no_text_blocks"
        elif len(raw_questions) < len(normalized_blocks):
            warnings.append(f"{len(normalized_blocks) - len(raw_questions)} blocks produced no questions")
            split_diagnostics["fallback_created"] = False
            split_diagnostics["failure_reason"] = None
        else:
            split_diagnostics["fallback_created"] = False
            split_diagnostics["failure_reason"] = None

        return {
            "raw_questions": raw_questions,
            "split_count": len(raw_questions),
            "split_diagnostics": split_diagnostics,
            "warnings": warnings,
        }

    def _run_match(
        self,
        raw_questions: list[dict],
        normalized_blocks: list[dict],
        structure: dict | None = None,
        **_kw,
    ) -> dict:
        """Stage 4: match answers and explanations to questions."""
        result = match_answers(raw_questions, normalized_blocks, structure=structure)

        matched = result.get("matched", [])
        unmatched = result.get("unmatched", [])

        warnings: list[str] = []
        if unmatched:
            warnings.append(f"{len(unmatched)} questions have no matched answer")

        return {
            "matched": matched,
            "unmatched": unmatched,
            "matched_count": len(matched),
            "warnings": warnings,
        }

    def _run_normalize_schema(
        self,
        raw_questions: list[dict],
        matched: list[dict],
        source_file: str,
        source_type: str,
        subject: str | None = None,
        **_kw,
    ) -> dict:
        """Stage 5: normalize questions to standard schema."""
        source_info = {
            "file": source_file,
            "type": source_type,
            "subject": subject or "",
        }
        result = normalize_questions(raw_questions, matched, source_info)

        questions = result.get("questions", [])
        errors = result.get("errors", [])
        warnings = result.get("warnings", [])

        invalid_count = sum(1 for q in questions if not q.get("is_valid", True))
        stage_warnings = list(warnings)
        if invalid_count:
            stage_warnings.append(f"{invalid_count} questions marked invalid")

        return {
            "questions": questions,
            "normalized_count": len(questions),
            "errors": list(errors),
            "warnings": stage_warnings,
        }

    def _run_repair(self, questions: list[dict], options: dict, **_kw) -> dict:
        """Stage 6: AI repair for low-confidence questions."""
        repair_config = {
            "confidence_threshold": options.get("confidence_threshold", 0.6),
            "daily_token_limit": options.get("daily_token_limit", 100000),
            "monthly_token_limit": options.get("monthly_token_limit", 2000000),
            "enabled": options.get("enable_ai_repair", True),
        }
        result = repair_questions(questions, repair_config)

        repaired = result.get("repaired", [])
        unrepaired = result.get("unrepaired", [])
        skipped = result.get("skipped", [])
        stats = result.get("stats", {})

        # Build the combined question list for the review stage:
        #   repaired items use their "after" field
        #   unrepaired + skipped items use the original question by index
        combined: list[dict] = [None] * len(questions)  # type: ignore

        for r in repaired:
            idx = r["question_index"]
            combined[idx] = r["after"]

        for u in unrepaired:
            idx = u["question_index"]
            combined[idx] = questions[idx]

        for s in skipped:
            idx = s["question_index"]
            combined[idx] = questions[idx]

        combined = [q for q in combined if q is not None]

        warnings: list[str] = []
        if unrepaired:
            warnings.append(f"{len(unrepaired)} questions unrepaired by AI")
        if skipped:
            warnings.append(f"{len(skipped)} questions skipped (above threshold)")

        return {
            "questions": combined,
            "repaired_count": len(repaired),
            "unrepaired_count": len(unrepaired),
            "skipped_count": len(skipped),
            "total_tokens": stats.get("total_tokens", 0),
            "warnings": warnings,
        }

    def _run_ai_validation(self, questions: list[dict], **_kw) -> dict:
        """Stage 6.2: validate AI repair results for anomalies."""
        result = validate_ai_results(questions)

        stats = result["stats"]
        warnings: list[str] = []
        if stats["errors"] > 0:
            warnings.append(f"{stats['errors']} questions have AI validation errors")
        if stats["warnings"] > 0:
            warnings.append(f"{stats['warnings']} questions have AI validation warnings")

        return {
            "questions": result["questions"],
            "ai_validation_diagnostics": stats,
            "warnings": warnings,
        }

    async def _run_similarity_match(
        self,
        questions: list[dict],
        db=None,
        options: dict | None = None,
        **_kw,
    ) -> dict:
        """Stage 6.5: suggest corrections from existing question bank."""
        opts = options or {}
        match_config = {
            "enabled": opts.get("enable_similarity_match", True),
            "similarity_threshold": opts.get("similarity_threshold", 0.85),
        }

        result = await match_similar_questions(questions, db=db, config=match_config)

        warnings: list[str] = []
        stats = result.get("stats", {})
        if stats.get("matched_count", 0) > 0:
            warnings.append(
                f"Found {stats['matched_count']} similar questions in bank "
                f"(avg ratio {stats['avg_similarity']:.2f})"
            )
        if result.get("skipped_reason"):
            warnings.append(f"Similarity match skipped: {result['skipped_reason']}")

        return {
            "questions": result["questions"],
            "similarity_match_diagnostics": {
                "stats": stats,
                "matches": result.get("matches", []),
                "skipped_reason": result.get("skipped_reason"),
            },
            "warnings": warnings,
        }

    async def _run_review(
        self,
        questions: list[dict],
        source_file: str,
        source_type: str,
        subject: str | None = None,
        db=None,
        **_kw,
    ) -> dict:
        """Stage 7: submit questions to review queue."""
        if db is None:
            return {
                "batch_id": "",
                "written": 0,
                "skipped": 0,
                "total": len(questions),
                "warnings": ["no db session provided, review stage skipped"],
            }

        from app.features.review_service import submit_to_review

        batch_meta = {
            "source_type": source_type,
            "source_file": source_file,
            "subject": subject or "",
        }
        result = await submit_to_review(db, questions, batch_meta)

        warnings: list[str] = []
        if result["skipped"] > 0:
            warnings.append(f"{result['skipped']} questions skipped in review")

        return {
            "batch_id": result["batch_id"],
            "written": result["written"],
            "skipped": result["skipped"],
            "total": result["total"],
            "items": result.get("items", []),
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # pipeline runner
    # ------------------------------------------------------------------

    async def run(
        self,
        file_content: bytes,
        source_type: str,
        source_file: str,
        subject: str | None = None,
        options: dict | None = None,
        db=None,
    ) -> dict:
        """Execute all pipeline stages in sequence.

        Args:
            file_content: raw file bytes (PDF, txt, etc.)
            source_type: "pdf" | "txt"
            source_file: original filename
            subject: optional subject hint
            options: {"enable_ai_repair": bool, "confidence_threshold": float}
            db: optional AsyncSession for the review stage

        Returns:
            Pipeline result dict with status, stats, stages, and errors.
        """
        opts = options or {}
        if options is not None:
            self.options = opts
        self._build_pipeline()

        started_at = datetime.now().isoformat()

        # Accumulated data passed between stages
        data: dict[str, Any] = {
            "file_content": file_content,
            "source_type": source_type,
            "source_file": source_file,
            "subject": subject,
            "options": opts,
            "db": db,
            "raw_blocks": [],
            "normalized_blocks": [],
            "raw_questions": [],
            "matched": [],
            "unmatched": [],
            "questions": [],
        }

        pipeline_errors: list[str] = []
        overall_status = "completed"

        for name, stage in self.stages.items():
            try:
                result = await stage.run_async(**data)
                if isinstance(result, dict):
                    if result.get("warnings"):
                        stage.warnings.extend(result["warnings"])
                    data.update(result)
            except Exception:
                overall_status = "failed"
                pipeline_errors.append(f"stage '{name}' failed: {stage.error}")
                if name in ("extract", "normalize_text"):
                    break
                logger.warning("Stage '%s' failed, continuing with partial results", name)

        # Build stats from stage outputs
        stats = {
            "total": data.get("extracted", 0),
            "extracted": data.get("extracted", 0),
            "normalized": data.get("normalized_count", len(data.get("normalized_blocks", []))),
            "analyzed": data.get("split_count", len(data.get("raw_questions", []))),
            "split": data.get("split_count", 0),
            "matched": data.get("matched_count", 0),
            "schema_normalized": data.get("normalized_count", 0),
            "missing_options": sum(
                1
                for q in data.get("questions", [])
                if "missing_options" in q.get("errors", [])
            ),
            "repaired": data.get("repaired_count", 0),
            "to_review": data.get("written", 0),
            "failed": sum(1 for s in self.stages.values() if s.status == "failed"),
        }
        diagnostics = {
            "structure": data.get("structure", {}),
            "ocr_correction": data.get("ocr_correction_diagnostics", {}),
            "split": data.get("split_diagnostics", {}),
            "schema_errors": data.get("errors", []),
            "ai_validation": data.get("ai_validation_diagnostics", {}),
            "similarity_match": data.get("similarity_match_diagnostics", {}),
        }

        finished_at = datetime.now().isoformat()

        return {
            "pipeline_id": self.pipeline_id,
            "status": overall_status,
            "batch_id": data.get("batch_id", ""),
            "stats": stats,
            "diagnostics": diagnostics,
            "stages": {name: s.to_dict() for name, s in self.stages.items()},
            "errors": pipeline_errors,
            "started_at": started_at,
            "finished_at": finished_at,
        }


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


async def run_import_pipeline(
    file_content: bytes,
    source_type: str,
    source_file: str,
    subject: str | None = None,
    options: dict | None = None,
    db=None,
) -> dict:
    """完整的导入流水线入口。

    串联 Stage 1 (文本清洗) → Stage 3 (题目切分) → Stage 4 (答案匹配)
    → Stage 5 (题目标准化) → Stage 6 (AI 修复, 可选) → Stage 7 (审核入库).

    Args:
        file_content: 文件原始字节
        source_type: "pdf" | "txt"
        source_file: 原始文件名
        subject: 科目提示（可选）
        options: {"enable_ai_repair": bool, "confidence_threshold": float}
        db: 异步数据库会话（review 阶段需要）

    Returns:
        Pipeline result dict.
    """
    pipeline_id = f"pl_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    pipeline = ImportPipeline(options=options)
    pipeline.pipeline_id = pipeline_id

    result = await pipeline.run(
        file_content=file_content,
        source_type=source_type,
        source_file=source_file,
        subject=subject,
        options=options,
        db=db,
    )
    result["pipeline_id"] = pipeline_id
    return result


async def run_pipeline_background(
    pipeline_id: str,
    file_content: bytes,
    source_type: str,
    source_file: str,
    subject: str | None = None,
    options: dict | None = None,
    db=None,
) -> None:
    """后台运行流水线，结果写入 _pipeline_store。"""
    _pipeline_store[pipeline_id] = {
        "pipeline_id": pipeline_id,
        "status": "parsing",
        "source_type": source_type,
        "stages": {},
        "stats": {},
        "errors": [],
        "started_at": datetime.now().isoformat(),
    }
    _prune_store()

    try:
        result = await run_import_pipeline(
            file_content=file_content,
            source_type=source_type,
            source_file=source_file,
            subject=subject,
            options=options,
            db=db,
        )
        result["pipeline_id"] = pipeline_id
        _pipeline_store[pipeline_id] = result
    except Exception as exc:
        logger.exception("Pipeline %s failed", pipeline_id)
        _pipeline_store[pipeline_id] = {
            "pipeline_id": pipeline_id,
            "status": "failed",
            "source_type": source_type,
            "errors": [str(exc)],
            "started_at": _pipeline_store.get(pipeline_id, {}).get("started_at", ""),
            "finished_at": datetime.now().isoformat(),
        }


async def run_excel_pipeline_background(
    pipeline_id: str,
    file_content: bytes,
    source_file: str,
    import_excel_fn,
) -> None:
    """后台运行 Excel 导入，结果写入 _pipeline_store 以支持状态查询。"""
    from app.core.database import async_session

    _pipeline_store[pipeline_id] = {
        "pipeline_id": pipeline_id,
        "status": "parsing",
        "source_type": "excel",
        "stages": {"extract": {"status": "running"}},
        "stats": {},
        "errors": [],
        "started_at": datetime.now().isoformat(),
    }
    _prune_store()

    try:
        async with async_session() as db:
            batch_id, total = await import_excel_fn(db, file_content, source_file)
        _pipeline_store[pipeline_id] = {
            "pipeline_id": pipeline_id,
            "status": "completed",
            "source_type": "excel",
            "batch_id": batch_id,
            "stats": {"total": total, "to_review": total},
            "stages": {"extract": {"status": "completed"}},
            "errors": [],
            "started_at": _pipeline_store[pipeline_id]["started_at"],
            "finished_at": datetime.now().isoformat(),
        }
    except Exception as exc:
        logger.exception("Excel pipeline %s failed", pipeline_id)
        _pipeline_store[pipeline_id] = {
            "pipeline_id": pipeline_id,
            "status": "failed",
            "source_type": "excel",
            "errors": [str(exc)],
            "started_at": _pipeline_store.get(pipeline_id, {}).get("started_at", ""),
            "finished_at": datetime.now().isoformat(),
        }


def get_pipeline_status(pipeline_id: str) -> dict | None:
    """查询流水线状态。"""
    return _pipeline_store.get(pipeline_id)

"""Question import writer — Excel/PDF import, approve/reject, batch operations.

Extracted from ``question_pipeline.py`` (P5-3).
"""

from __future__ import annotations

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

from app.core.time_utils import utcnow
from app.core.config import settings
from app.features.question_pipeline import (
    _QI_PARSED_FIELDS,
    _find_duplicate_by_hash,
    _find_import_duplicate_by_hash,
    normalizer,
    process_question_pipeline,
)
from app.features.question_splitter import split_questions
from app.models.question import Question
from app.models.question_import import QuestionImport

logger = logging.getLogger(__name__)


# ============================================================
# Excel / PDF 解析
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
# 导入主流程
# ============================================================


async def _build_import_duplicate_fields(
    db: AsyncSession,
    *,
    import_id: int | None,
    subject: str | None = None,
    question_hash: str | None,
    subject_id: int | None = None,
) -> dict:
    duplicate_fields = {
        "question_hash": question_hash or None,
        "duplicate_status": "normal",
        "duplicate_of_question_id": None,
        "duplicate_of_import_id": None,
    }
    result_label = "normal"
    matched_id = None

    duplicate_question = await _find_duplicate_by_hash(db, subject, question_hash, subject_id=subject_id)
    if duplicate_question and not hasattr(duplicate_question, "id"):
        duplicate_question = None
    if duplicate_question:
        duplicate_fields["duplicate_status"] = "possible_duplicate"
        duplicate_fields["duplicate_of_question_id"] = duplicate_question.id
        result_label = "matched_question"
        matched_id = duplicate_question.id
    else:
        duplicate_import = await _find_import_duplicate_by_hash(db, subject, question_hash, subject_id=subject_id)
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
        subject_id=qi.subject_id,
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
    subject_id_val = result["import_fields"].get("subject_id")

    if skip_existing and question_hash and subject_id_val:
        existing = await _find_duplicate_by_hash(db, None, question_hash, subject_id=subject_id_val)
        if existing:
            logger.info(
                "[DuplicateFilter] 跳过已存在的题目 subject_id=%s hash=%s existing_id=%s",
                subject_id_val,
                question_hash,
                existing.id,
            )
            return None
        existing_import = await _find_import_duplicate_by_hash(db, None, question_hash, subject_id=subject_id_val)
        if existing_import:
            logger.info(
                "[DuplicateFilter] 跳过审核池中已存在的题目 subject_id=%s hash=%s existing_import_id=%s",
                subject_id_val,
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
    await _refresh_import_duplicate_status(db, qi, question_hash)
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


# ============================================================
# 审核操作
# ============================================================


async def _get_qi(db: AsyncSession, import_id: int) -> QuestionImport:
    res = await db.execute(
        select(QuestionImport).where(QuestionImport.id == import_id)
    )
    qi = res.scalar_one_or_none()
    if not qi:
        raise ValueError("导入记录不存在")
    return qi


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

    subject_code = qi.subject_ref.code if qi.subject_ref else str(qi.subject_id)
    raw = {
        "subject": data.get("subject", subject_code),
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

    if data.get("parsed_answer"):
        qi.parsed_answer = data["parsed_answer"]

    await _refresh_import_duplicate_status(
        db, qi, result["normalized"].get("question_hash")
    )
    duplicate = await _find_duplicate_by_hash(
        db, None, result["normalized"]["question_hash"], subject_id=qi.subject_id
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
            "[Review Pass] import_id=%s → question_id=%s subject_id=%s",
            qi.id, q.id, q.subject_id,
        )

    qi.review_note = data.get("review_note")
    if qi.ai_generated:
        qi.ai_reviewed_at = utcnow()
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
        subject_code = qi.subject_ref.code if qi.subject_ref else str(qi.subject_id)
        result = process_question_pipeline(
            {
                "subject": subject_code,
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

        await _refresh_import_duplicate_status(
            db, qi, result["normalized"].get("question_hash")
        )
        duplicate = await _find_duplicate_by_hash(
            db, None, result["normalized"]["question_hash"], subject_id=qi.subject_id
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
                "[Batch Approve] import_id=%s → question_id=%s subject_id=%s",
                qi.id, q.id, q.subject_id,
            )
        if qi.ai_generated:
            qi.ai_reviewed_at = utcnow()
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

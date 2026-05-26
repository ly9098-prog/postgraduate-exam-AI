import io
import logging
import os
import tempfile
import uuid
from dataclasses import asdict
from datetime import datetime

import re

from openpyxl import Workbook, load_workbook
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.question import Question
from app.models.question_import import QuestionImport

logger = logging.getLogger(__name__)


def _parse_excel_row(row: list, headers: list) -> dict | None:
    """将 Excel 一行转为 raw_data dict，跳过空行"""
    raw = {}
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
    """解析 Excel 文件，每行返回 raw_data"""
    wb = load_workbook(io.BytesIO(content), read_only=True)
    ws = wb.active
    if ws is None:
        return []

    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        return []

    headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(rows[0])]
    results = []
    for row in rows[1:]:
        raw = _parse_excel_row(list(row), headers)
        if raw:
            results.append(raw)
    return results


def _raw_to_parsed(raw: dict) -> dict:
    """将原始行数据转为结构化字段，尽量智能映射"""
    SUBJECT_MAP = {
        "数学二": "math2", "数学": "math2", "math2": "math2",
        "高等数学": "math2-calculus", "高数": "math2-calculus",
        "线性代数": "math2-linalg", "线代": "math2-linalg",
        "408": "exam408", "计算机": "exam408", "exam408": "exam408",
        "数据结构": "exam408-ds", "DS": "exam408-ds", "exam408-ds": "exam408-ds",
        "操作系统": "exam408-os", "OS": "exam408-os", "exam408-os": "exam408-os",
        "计算机组成": "exam408-co", "组成原理": "exam408-co", "CO": "exam408-co", "exam408-co": "exam408-co",
        "计算机网络": "exam408-cn", "网络": "exam408-cn", "CN": "exam408-cn", "exam408-cn": "exam408-cn",
        "英语": "english", "英语二": "english", "english": "english",
    }
    TYPE_MAP = {
        "选择": "choice", "选择题": "choice", "单选": "choice", "choice": "choice",
        "填空": "fill", "填空题": "fill", "fill": "fill",
        "主观": "subjective", "主观题": "subjective", "简答": "subjective",
        "subjective": "subjective",
    }

    subject = raw.get("subject", "")
    subject = SUBJECT_MAP.get(subject, subject)

    qtype = raw.get("question_type", raw.get("题型", "choice"))
    qtype = TYPE_MAP.get(str(qtype).strip(), str(qtype).strip())

    stem = raw.get("stem", raw.get("题目", raw.get("题干", "")))
    content = {"text": str(stem).strip()}

    options_text = raw.get("options", raw.get("选项", ""))
    options = None
    if options_text and str(options_text).strip():
        parts = str(options_text).split("\\n")
        opt_dict = {}
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if ":" in p:
                key, val = p.split(":", 1)
                opt_dict[key.strip()] = val.strip()
            elif "." in p:
                key, val = p.split(".", 1)
                opt_dict[key.strip()] = val.strip()
            else:
                opt_dict[chr(65 + len(opt_dict))] = p
        options = opt_dict if opt_dict else None

    answer = raw.get("answer", raw.get("答案", ""))
    analysis = raw.get("explanation", raw.get("解析", raw.get("analysis", "")))
    tags_raw = raw.get("tags", raw.get("知识", raw.get("knowledge_points", "")))
    knowledge_points = None
    if tags_raw and str(tags_raw).strip():
        knowledge_points = [t.strip() for t in str(tags_raw).split(",") if t.strip()]

    difficulty = raw.get("difficulty", raw.get("难度", 3))
    if isinstance(difficulty, str):
        try:
            difficulty = int(difficulty)
        except ValueError:
            difficulty = 3
    difficulty = max(1, min(5, difficulty))

    return {
        "subject": subject if subject in (
            "math2", "math2-calculus", "math2-linalg",
            "exam408", "exam408-ds", "exam408-os", "exam408-co", "exam408-cn",
            "english",
        ) else None,
        "question_type": qtype,
        "parsed_content": content,
        "parsed_options": options,
        "parsed_answer": str(answer).strip() if answer else None,
        "parsed_analysis": str(analysis).strip() if analysis else None,
        "knowledge_points": knowledge_points,
        "difficulty": difficulty,
    }


def _guess_subject(text: str) -> str | None:
    """根据 PDF 文本内容关键词猜测科目（含子科目）"""
    text_lower = text.lower()
    scores: dict[str, int] = {
        "exam408-ds": 0, "exam408-os": 0, "exam408-co": 0, "exam408-cn": 0,
        "math2-calculus": 0, "math2-linalg": 0,
        "english": 0,
    }
    keywords = {
        "exam408-ds": [
            "数据结构", "链表", "栈", "队列", "二叉树", "红黑树", "b树", "avl",
            "排序", "查找", "图论", "dfs", "bfs", "最短路", "最小生成树",
            "哈希表", "散列", "堆", "优先队列",
        ],
        "exam408-os": [
            "操作系统", "进程", "线程", "死锁", "调度", "内存管理", "虚拟内存",
            "分页", "分段", "文件系统", "i/o", "中断", "信号量", "互斥",
            "页面置换", "缺页",
        ],
        "exam408-co": [
            "计算机组成", "指令系统", "cpu", "alu", "cache", "存储器", "dma",
            "总线", "寻址", "流水线", "ieee 754", "浮点", "定点", "补码",
        ],
        "exam408-cn": [
            "计算机网络", "tcp", "ip", "http", "udp", "路由", "交换",
            "dns", "nat", "arp", "以太网", "局域网", "csma", "帧",
            "网络层", "传输层", "应用层", "拥塞控制",
        ],
        "math2-calculus": [
            "极限", "导数", "积分", "微分方程", "级数", "泰勒", "麦克劳林",
            "偏导", "多元函数", "曲线积分", "曲面积分", "不定积分", "定积分",
            "连续", "可导", "极值", "拐点", "渐近线",
        ],
        "math2-linalg": [
            "矩阵", "行列式", "向量", "线性方程组", "特征值", "特征向量",
            "二次型", "正定", "正交", "秩", "线性相关", "线性无关", "基",
            "子空间", "相似矩阵",
        ],
        "english": [
            "reading comprehension", "passage", "paragraph", "translate",
            "完形填空", "阅读理解", "写作", "according to the passage",
        ],
    }
    for subj, words in keywords.items():
        for w in words:
            if w in text_lower:
                scores[subj] += 1

    best = max(scores, key=lambda k: scores[k])
    if scores[best] < 2:
        return None

    # 子科目得分不足时，退化到父科目
    parent_map = {
        "exam408-ds": "exam408", "exam408-os": "exam408",
        "exam408-co": "exam408", "exam408-cn": "exam408",
        "math2-calculus": "math2", "math2-linalg": "math2",
    }
    return best if scores[best] >= 3 else parent_map.get(best, best)


def _extract_pdf_text(pdf_path: str) -> str:
    """双通道提取 PDF 全文：文本型直接提取，图片型页面走 OCR。"""
    from app.services.pdf_classifier import classify_pages, get_pixmap
    from app.services.ocr_service import ocr_pages, clean_ocr_text

    with open(pdf_path, "rb") as f:
        content = f.read()

    classified = classify_pages(content)
    page_texts: dict[int, str] = {}

    # 收集需要 OCR 的页面图片
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

    # 并发 OCR
    if ocr_targets:
        ocr_results = ocr_pages(ocr_targets)
        for idx, raw_text in ocr_results.items():
            page_texts[idx] = clean_ocr_text(raw_text)

    # 按页码顺序拼接全文
    full_text = "\n".join(page_texts.get(i, "") for i in range(len(classified)))
    return full_text


def _parse_pdf(pdf_path: str, filename: str) -> list[dict]:
    """解析 PDF（文本型 + 扫描版 OCR），按题号切分，返回 raw_data 列表"""
    text = _extract_pdf_text(pdf_path)

    if not text.strip():
        raise ValueError("PDF 中未提取到文本内容（文本型和 OCR 均无结果）")

    # 根据内容关键词猜测科目
    guessed_subject = _guess_subject(text)

    # 按题号切分：支持 "1." / "1、" / "1)" / "1 . " 等格式
    # OCR 或某些字体渲染会在数字与标点间插空格，所以允许 \s*
    blocks = re.split(r'\n\s*(?=\d+\s*[.、)）])', text)
    blocks = [b.strip() for b in blocks if len(b.strip()) > 20]

    # 答案区识别：冒号必须存在，行首严格匹配，不允许在解析区再次触发
    _ANSWER_RE = re.compile(r'^(?:【)?(?:参考|正确)?答案(?:】)?\s*[：:](.*)$')
    _ANALYSIS_RE = re.compile(r'^(?:【)?(?:解析|解答)(?:】)?\s*[：:](.*)')

    def _stem_key(line: str) -> str:
        k = re.sub(r'^\d+\s*[.、)）]\s*', '', line).strip()
        return re.sub(r'\s+', ' ', k)

    results = []
    for block in blocks:
        lines = block.split("\n")
        stem_lines = []
        options = {}
        answer = ""
        analysis = ""
        # 状态机：stem → options → answer → analysis
        # 进入 analysis 后禁止再次切换到 answer
        section = "stem"
        stem_seen: set[str] = set()

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 识别选项行：A. xxx / A: xxx（容忍空格）
            opt_match = re.match(r'^([A-D])\s*[.、:]\s*(.*)', line)
            if opt_match and section in ("stem", "options"):
                key = opt_match.group(1)
                if key not in options:
                    options[key] = opt_match.group(2)
                section = "options"
                continue

            # 识别解析行（优先于答案行，避免"解析：...答案A"误入答案）
            ana_match = _ANALYSIS_RE.match(line)
            if ana_match and section != "analysis":
                analysis = ana_match.group(1).strip()
                section = "analysis"
                continue

            # 识别答案行：仅在非解析区触发，且冒号必须存在
            if section not in ("analysis",):
                ans_match = _ANSWER_RE.match(line)
                if ans_match:
                    answer = ans_match.group(1).strip()
                    # 不切入 analysis，保持当前区域等待解析行
                    section = "answer"
                    continue

            if section == "analysis":
                if analysis:
                    analysis += "\n" + line
                else:
                    analysis = line
            elif section == "stem":
                key = _stem_key(line)
                if key not in stem_seen:
                    stem_seen.add(key)
                    stem_lines.append(line)

        stem = "\n".join(stem_lines)

        # 清理题干前缀：去掉 "1." "1、" "1)" "1 ." 等编号和 "(单选题)" 等题型标记
        stem = re.sub(r'^\d+\s*[.、)）]\s*', '', stem)
        stem = re.sub(r'^[（(]\s*(单选|多选|选择|填空|判断|简答|论述|计算)题?[）)]\s*', '', stem)
        stem = stem.strip()

        # 仅当有题干时才保留
        if len(stem) < 5:
            continue

        options_str = "\\n".join(f"{k}:{v}" for k, v in sorted(options.items())) if options else ""

        raw = {
            "subject": guessed_subject,
            "stem": stem,
            "options": options_str,
            "answer": answer,
            "explanation": analysis,
            "question_type": "choice" if options else "fill",
        }
        results.append(raw)

    if not results:
        raise ValueError("未能从 PDF 中解析出有效题目，请检查文件格式")

    return results


async def import_excel(
    db: AsyncSession,
    content: bytes,
    filename: str,
) -> tuple[str, int]:
    """上传并解析 Excel，写入 question_imports 暂存区"""
    raw_rows = _parse_excel(content, filename)
    if not raw_rows:
        raise ValueError("Excel 文件为空或格式不正确")

    batch_id = f"BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    for row in raw_rows:
        parsed = _raw_to_parsed(row)
        qi = QuestionImport(
            batch_id=batch_id,
            source_type="excel",
            source_file=filename,
            raw_data=row,
            status="pending",
            **{k: v for k, v in parsed.items() if k in (
                "subject", "question_type", "parsed_content",
                "parsed_options", "parsed_answer", "parsed_analysis",
            )},
        )
        db.add(qi)

    await db.commit()
    return batch_id, len(raw_rows)


async def import_pdf(
    db: AsyncSession,
    content: bytes,
    filename: str,
    background_tasks=None,
) -> tuple[str, int]:
    """上传并解析 PDF，写入 question_imports 暂存区。

    若 settings.MATH_IMAGE_RENDER_ENABLED 且 background_tasks 传入，
    则注册后台数学管线任务；否则立即清理临时文件。
    """
    # 写入临时文件（BackgroundTask 需持有路径）
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        raw_rows = _parse_pdf(tmp_path, filename)
    except Exception:
        os.unlink(tmp_path)
        raise

    batch_id = f"BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    for row in raw_rows:
        parsed = _raw_to_parsed(row)
        qi = QuestionImport(
            batch_id=batch_id,
            source_type="pdf",
            source_file=filename,
            raw_data=row,
            status="pending",
            **{k: v for k, v in parsed.items() if k in (
                "subject", "question_type", "parsed_content",
                "parsed_options", "parsed_answer", "parsed_analysis",
            )},
        )
        db.add(qi)

    await db.commit()

    if settings.MATH_IMAGE_RENDER_ENABLED and background_tasks is not None:
        background_tasks.add_task(_run_math_pipeline, batch_id, tmp_path, db)
    else:
        os.unlink(tmp_path)

    return batch_id, len(raw_rows)


async def _run_math_pipeline(batch_id: str, tmp_pdf_path: str, db: AsyncSession) -> None:
    """后台任务：对批次中每道题运行数学区域检测 + 截图上传 + 混合内容构建。"""
    import fitz
    from sqlalchemy import select as sa_select
    from app.services.math_region_detector import detect_page
    from app.services.formula_image_cropper import crop_and_upload
    from app.services.hybrid_content_builder import build as build_content
    from app.services.storage_backend import get_storage

    doc = None
    try:
        doc = fitz.open(tmp_pdf_path)
        result = await db.execute(
            sa_select(QuestionImport).where(QuestionImport.batch_id == batch_id)
        )
        imports = list(result.scalars().all())
        storage = get_storage()

        for qi in imports:
            page_num = (qi.raw_data or {}).get("page_num")
            if page_num is None or page_num < 0 or page_num >= len(doc):
                continue

            try:
                page = doc[page_num]
                regions = detect_page(page)
                if not regions:
                    continue

                regions = await crop_and_upload(doc, regions, storage, import_id=qi.id)
                content = build_content(
                    text=(qi.parsed_content or {}).get("text", ""),
                    regions=regions,
                )
                await db.execute(
                    sa_select(QuestionImport).where(QuestionImport.id == qi.id)
                )
                qi.math_regions = [asdict(r) for r in regions]
                qi.parsed_content = content
            except Exception as e:
                logger.warning("math pipeline 单题失败 import_id=%s: %s", qi.id, e)

        await db.commit()
    except Exception as e:
        logger.warning("math pipeline 失败 batch=%s: %s", batch_id, e)
        try:
            await db.rollback()
        except Exception:
            pass
    finally:
        if doc is not None:
            doc.close()
        try:
            os.unlink(tmp_pdf_path)
        except OSError:
            pass


async def approve_question(db: AsyncSession, import_id: int, data: dict) -> Question:
    """审核通过一条导入题目，写入 questions 表"""
    result = await db.execute(
        select(QuestionImport).where(QuestionImport.id == import_id)
    )
    qi: QuestionImport | None = result.scalar_one_or_none()
    if not qi:
        raise ValueError("导入记录不存在")
    if qi.status != "pending":
        raise ValueError("该记录已审核")

    subject = data.get("subject", qi.subject)
    question_type = data.get("question_type", qi.question_type)
    content = data.get("parsed_content", qi.parsed_content)
    options = data.get("parsed_options", qi.parsed_options)
    answer = data.get("parsed_answer", qi.parsed_answer)
    analysis = data.get("parsed_analysis", qi.parsed_analysis)

    if not subject or not question_type or not content or not answer:
        raise ValueError("科目、题型、题目内容、答案为必填")

    # 从 AI 元数据中提取 knowledge_points / difficulty 作为兜底
    ai_meta = qi.ai_metadata or {}
    ai_kps = ai_meta.get("knowledge_points") if isinstance(ai_meta, dict) else None
    ai_diff = ai_meta.get("difficulty") if isinstance(ai_meta, dict) else None

    knowledge_points = data.get("knowledge_points")
    if knowledge_points is None and isinstance(ai_kps, list) and ai_kps:
        knowledge_points = ai_kps

    difficulty = data.get("difficulty")
    if difficulty is None and isinstance(ai_diff, int) and 1 <= ai_diff <= 5:
        difficulty = ai_diff

    q = Question(
        subject=subject,
        question_type=question_type,
        content=content or {},
        options=options,
        answer=answer,
        analysis=analysis,
        source=qi.source_file,
        source_type=qi.source_type,
        source_file=qi.source_file,
        import_batch_id=qi.batch_id,
        raw_content=str(qi.raw_data),
        review_status="approved",
        is_active=True,
    )
    if knowledge_points:
        q.knowledge_points = knowledge_points
    if difficulty:
        q.difficulty = difficulty

    db.add(q)
    await db.flush()
    await db.refresh(q)

    qi.status = "approved"
    qi.question_id = q.id
    qi.review_note = data.get("review_note")
    if qi.ai_generated:
        qi.ai_reviewed_at = datetime.utcnow()

    await db.commit()
    return q


async def reject_question(db: AsyncSession, import_id: int, note: str | None = None):
    """拒绝一条导入记录"""
    result = await db.execute(
        select(QuestionImport).where(QuestionImport.id == import_id)
    )
    qi: QuestionImport | None = result.scalar_one_or_none()
    if not qi:
        raise ValueError("导入记录不存在")
    if qi.status != "pending":
        raise ValueError("该记录已审核")

    qi.status = "rejected"
    qi.review_note = note
    await db.commit()


async def batch_approve(db: AsyncSession, batch_id: str) -> tuple[int, int]:
    """批量通过一个批次的所有待审核记录"""
    result = await db.execute(
        select(QuestionImport).where(
            QuestionImport.batch_id == batch_id,
            QuestionImport.status == "pending",
        )
    )
    records = list(result.scalars().all())
    count = 0
    skipped = {}  # {id: [缺失字段]}
    for qi in records:
        missing = []
        if not qi.subject:
            missing.append("科目")
        if not qi.question_type:
            missing.append("题型")
        if not qi.parsed_content:
            missing.append("题目内容")
        if not qi.parsed_answer:
            missing.append("答案")
        if missing:
            skipped[qi.id] = missing
            continue
        q = Question(
            subject=qi.subject,
            question_type=qi.question_type,
            content=qi.parsed_content or {},
            options=qi.parsed_options,
            answer=qi.parsed_answer or "",
            analysis=qi.parsed_analysis,
            source=qi.source_file,
            source_type=qi.source_type,
            source_file=qi.source_file,
            import_batch_id=qi.batch_id,
            raw_content=str(qi.raw_data),
            review_status="approved",
            is_active=True,
        )
        ai_meta = qi.ai_metadata or {}
        if isinstance(ai_meta, dict):
            kps = ai_meta.get("knowledge_points")
            if isinstance(kps, list) and kps:
                q.knowledge_points = kps
            diff = ai_meta.get("difficulty")
            if isinstance(diff, int) and 1 <= diff <= 5:
                q.difficulty = diff
        db.add(q)
        await db.flush()
        await db.refresh(q)

        qi.status = "approved"
        qi.question_id = q.id
        if qi.ai_generated:
            qi.ai_reviewed_at = datetime.utcnow()
        count += 1

    await db.commit()
    if count == 0 and records:
        details = "; ".join(
            f"#{qid} 缺{'、'.join(fields)}" for qid, fields in skipped.items()
        )
        raise ValueError(
            f"批量审批未通过任何题目（{len(skipped)} 道缺少必填字段）。"
            f"详情：{details}"
        )
    return count, len(skipped)


async def batch_reject(db: AsyncSession, batch_id: str) -> int:
    """批量拒绝一个批次的所有待审核记录"""
    result = await db.execute(
        select(QuestionImport).where(
            QuestionImport.batch_id == batch_id,
            QuestionImport.status == "pending",
        )
    )
    records = list(result.scalars().all())
    if not records:
        raise ValueError("该批次没有待审核的题目")

    count = 0
    for qi in records:
        qi.status = "rejected"
        count += 1

    await db.commit()
    return count


async def list_batches(db: AsyncSession) -> list[dict]:
    """按 batch_id 聚合，返回批次列表"""
    subq = (
        select(
            QuestionImport.batch_id,
            QuestionImport.source_type,
            QuestionImport.source_file,
            func.count(QuestionImport.id).label("total"),
            func.sum(
                case((QuestionImport.status == "pending", 1), else_=0)
            ).label("pending"),
            func.sum(
                case((QuestionImport.status == "approved", 1), else_=0)
            ).label("approved"),
            func.sum(
                case((QuestionImport.status == "rejected", 1), else_=0)
            ).label("rejected"),
            func.max(QuestionImport.created_at).label("created_at"),
        )
        .group_by(
            QuestionImport.batch_id,
            QuestionImport.source_type,
            QuestionImport.source_file,
        )
        .order_by(func.max(QuestionImport.created_at).desc())
    )
    result = await db.execute(subq)
    rows = result.all()
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


def generate_template() -> bytes:
    """生成标准 Excel 导入模板"""
    wb = Workbook()
    ws = wb.active
    ws.title = "导入模板"

    headers = [
        "subject", "question_type", "stem", "options",
        "answer", "explanation", "difficulty", "tags",
    ]
    ws.append(headers)

    # 示例数据
    ws.append([
        "math2", "choice", "设函数 $f(x)=x^2+1$，求 $f'(x)$。",
        "A:$2x$\\nB:$x^2$\\nC:$2x+1$\\nD:$x$",
        "A", "根据求导公式，$(x^2+1)'=2x$。", "2", "导数,求导公式",
    ])

    # 设置列宽
    col_widths = [12, 14, 40, 50, 10, 40, 10, 25]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[chr(64 + i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


async def get_batch_detail(
    db: AsyncSession, batch_id: str
) -> list[QuestionImport]:
    result = await db.execute(
        select(QuestionImport)
        .where(QuestionImport.batch_id == batch_id)
        .order_by(QuestionImport.id)
    )
    return list(result.scalars().all())

"""王道408 PDF 端到端评测脚本。

测试完整 pipeline：extract → wangdao_preprocess → normalize → structure_analyze → split

运行方式:
    # 结构评测（不需要OCR，用预存文本）
    cd backend && PYTHONPATH=. python -m tests.ocr_eval.eval_wangdao

    # Live OCR 评测（需要 PaddleOCR + PDF fixture）
    cd backend && PYTHONPATH=. python -m tests.ocr_eval.eval_wangdao --live-ocr

    # 指定页码范围
    cd backend && PYTHONPATH=. python -m tests.ocr_eval.eval_wangdao --live-ocr --pages 30-35

    # 作为 pytest
    cd backend && PYTHONPATH=. pytest tests/ocr_eval/eval_wangdao.py -v
"""
import argparse
import json
import sys
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
WANGDAO_PDF = FIXTURE_DIR / "wangdao_408.pdf"
SAMPLES_DIR = Path(__file__).parent / "samples" / "wangdao"


# ---------------------------------------------------------------------------
# Ground truth samples for structure-only testing
# ---------------------------------------------------------------------------

SAMPLE_BLOCKS_CH1 = [
    {"page": 1, "block_index": 0, "text": "第1章 计算机网络体系结构",
     "boxes": [{"bbox": [100, 30, 800, 70], "conf": 0.95}],
     "page_width": 1128, "page_height": 1571},
    {"page": 1, "block_index": 1, "text": "1.1 计算机网络概述",
     "boxes": [{"bbox": [100, 150, 500, 185], "conf": 0.95}],
     "page_width": 1128, "page_height": 1571},
    {"page": 1, "block_index": 2, "text": "1.广域网（WAN）\n2.城域网（MAN）\n3.局域网（LAN）\n4.个人区域网（PAN）",
     "boxes": [{"bbox": [100, 200, 900, 400], "conf": 0.93}],
     "page_width": 1128, "page_height": 1571},
    {"page": 1, "block_index": 3, "text": "王道",
     "boxes": [{"bbox": [950, 1450, 1050, 1480], "conf": 0.6}],
     "page_width": 1128, "page_height": 1571},
    {"page": 2, "block_index": 4, "text": "本章小结\n计算机网络是通过通信设备和线路将地理位置不同的计算机互联",
     "boxes": [{"bbox": [100, 100, 900, 300], "conf": 0.94}],
     "page_width": 1128, "page_height": 1571},
    {"page": 3, "block_index": 5, "text": "习题精选",
     "boxes": [{"bbox": [400, 100, 700, 140], "conf": 0.96}],
     "page_width": 1128, "page_height": 1571},
    {"page": 3, "block_index": 6, "text": "单项选择题",
     "boxes": [{"bbox": [450, 180, 680, 210], "conf": 0.95}],
     "page_width": 1128, "page_height": 1571},
    {"page": 3, "block_index": 7, "text": "01．在下列选项中，不属于网络体系结构所描述的内容是（  ）。\nA．网络的层次\nB．每一层使用的协议\nC．协议的内部实现细节\nD．每一层必须完成的功能",
     "boxes": [{"bbox": [100, 250, 900, 420], "conf": 0.94}],
     "page_width": 1128, "page_height": 1571},
    {"page": 3, "block_index": 8, "text": "02．下列选项中，不属于网络协议组成要素的是（  ）。\nA．语法\nB．语义\nC．同步\nD．编码",
     "boxes": [{"bbox": [100, 440, 900, 580], "conf": 0.93}],
     "page_width": 1128, "page_height": 1571},
    {"page": 4, "block_index": 9, "text": "03．在OSI参考模型中，提供端到端服务的最低层是（  ）。\nA．数据链路层\nB．网络层\nC．传输层\nD．会话层",
     "boxes": [{"bbox": [100, 100, 900, 250], "conf": 0.94}],
     "page_width": 1128, "page_height": 1571},
    {"page": 4, "block_index": 10, "text": "04．在TCP/IP体系结构中，与OSI的网络层对应的是（  ）。\nA．网络接口层\nB．网际层\nC．传输层\nD．应用层",
     "boxes": [{"bbox": [100, 270, 900, 410], "conf": 0.93}],
     "page_width": 1128, "page_height": 1571},
    {"page": 5, "block_index": 11, "text": "答案与解析\n01．C 协议的内部实现细节不属于体系结构描述内容。\n02．D 网络协议组成要素是语法、语义和同步。\n03．C 传输层是提供端到端服务的最低层。\n04．B 网际层对应OSI的网络层。",
     "boxes": [{"bbox": [100, 100, 900, 400], "conf": 0.94}],
     "page_width": 1128, "page_height": 1571},
]

EXPECTED_QUESTIONS_CH1 = [
    {"number": 1, "page": 3, "has_options": True, "option_count": 4},
    {"number": 2, "page": 3, "has_options": True, "option_count": 4},
    {"number": 3, "page": 4, "has_options": True, "option_count": 4},
    {"number": 4, "page": 4, "has_options": True, "option_count": 4},
]


def _ocr_block(page: int, block_index: int, lines: list[str], coords: list[list[int]]) -> dict:
    return {
        "page": page,
        "block_index": block_index,
        "text": "\n".join(lines),
        "boxes": [{"bbox": bbox, "conf": 0.94} for bbox in coords],
        "page_width": 1128,
        "page_height": 1571,
    }


SAMPLE_KNOWLEDGE_ONLY_NUMBERED = [
    _ocr_block(
        1,
        0,
        [
            "1. 数据结构的定义",
            "数据结构是相互之间存在一种或多种特定关系的数据元素的集合。",
            "2. 线性表的性质",
            "线性表中的元素具有相同的数据类型，除第一个元素外每个元素有且仅有一个直接前驱。",
            "证明：由定义可知，顺序存储结构可以支持随机访问。",
        ],
        [
            [100, 120, 480, 150],
            [100, 165, 980, 195],
            [100, 235, 480, 265],
            [100, 280, 980, 310],
            [100, 350, 900, 380],
        ],
    ),
]

SAMPLE_MIXED_PROSE_AND_EXERCISE = [
    _ocr_block(
        1,
        0,
        [
            "1. 栈的定义",
            "栈是只允许在一端进行插入和删除的线性表。",
            "例题解析：如下过程说明栈的先进后出性质。",
            "习题精选",
            "01．下列关于栈的说法中，正确的是（  ）。",
            "A．先进先出",
            "B．后进先出",
            "C．随机访问",
            "D．链式存储",
        ],
        [
            [100, 120, 430, 150],
            [100, 165, 920, 195],
            [100, 210, 900, 240],
            [460, 500, 650, 535],
            [100, 570, 980, 605],
            [120, 625, 420, 655],
            [120, 665, 420, 695],
            [120, 705, 420, 735],
            [120, 745, 420, 775],
        ],
    ),
]

SAMPLE_TWO_COLUMN_PROSE_AND_QUESTIONS = [
    _ocr_block(
        1,
        0,
        [
            "定义：二叉树是每个结点至多有两棵子树的树形结构。",
            "性质：第 i 层上至多有 2 的 i-1 次方个结点。",
            "证明：可用数学归纳法得到上述结论。",
            "01．下列关于二叉树的说法，正确的是（  ）。",
            "A．每个结点都有两个孩子",
            "B．可以为空树",
            "C．只能顺序存储",
            "D．高度一定等于结点数",
        ],
        [
            [80, 120, 510, 150],
            [80, 170, 510, 200],
            [80, 220, 510, 250],
            [600, 120, 1060, 150],
            [620, 170, 1040, 200],
            [620, 220, 1040, 250],
            [620, 270, 1040, 300],
            [620, 320, 1040, 350],
        ],
    ),
]

SAMPLE_ANSWER_ONLY = [
    _ocr_block(
        1,
        0,
        [
            "答案与解析",
            "01．B 栈的特点是后进先出。",
            "02．C 队列的特点是先进先出。",
            "解析：本题考查线性结构的基本概念。",
        ],
        [
            [430, 100, 700, 135],
            [100, 180, 940, 210],
            [100, 240, 940, 270],
            [100, 310, 940, 340],
        ],
    ),
]


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

def run_pipeline_stages(raw_blocks: list[dict], import_mode: str | None = None) -> dict:
    """Run the full pipeline stages and return intermediate results."""
    from app.features.question_splitter import split_questions
    from app.features.structure_analyzer import analyze_structure
    from app.features.text_normalizer import ImportTextNormalizer
    from app.features.wangdao_preprocessor import preprocess_wangdao_blocks

    # Stage 1: Wangdao preprocess (coordinate-based filtering)
    preprocessed = preprocess_wangdao_blocks(raw_blocks)

    # Stage 2: Text normalization
    normalizer = ImportTextNormalizer()
    normalized = normalizer.normalize(preprocessed)

    # Stage 3: Structure analysis
    structure = analyze_structure(normalized)

    # Stage 4: Question splitting
    questions = split_questions(normalized, structure, import_mode=import_mode)

    return {
        "preprocessed_count": len(preprocessed),
        "normalized_count": len(normalized),
        "structure": structure,
        "questions": questions,
        "removed_by_preprocess": len(raw_blocks) - len(preprocessed),
    }


def compute_metrics(questions: list[dict], expected: list[dict]) -> dict:
    """Compute precision/recall for question extraction."""
    expected_nums = {e["number"] for e in expected}
    found_nums = {q["number"] for q in questions}

    true_positives = expected_nums & found_nums
    false_positives = found_nums - expected_nums
    false_negatives = expected_nums - found_nums

    precision = len(true_positives) / max(len(found_nums), 1)
    recall = len(true_positives) / max(len(expected_nums), 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)

    option_correct = 0
    option_total = 0
    for exp in expected:
        if exp["number"] in found_nums:
            option_total += 1
            matched_q = next(q for q in questions if q["number"] == exp["number"])
            if len(matched_q.get("option_lines", {})) >= exp.get("option_count", 0):
                option_correct += 1

    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "true_positives": sorted(true_positives),
        "false_positives": sorted(false_positives),
        "false_negatives": sorted(false_negatives),
        "option_completeness": round(option_correct / max(option_total, 1), 3),
    }


# ---------------------------------------------------------------------------
# Structure-only tests (no OCR needed)
# ---------------------------------------------------------------------------

class TestWangdaoStructureOnly:
    """Test pipeline stages with pre-built sample blocks (no OCR dependency)."""

    def test_watermark_filtered(self):
        from app.features.wangdao_preprocessor import preprocess_wangdao_blocks
        result = preprocess_wangdao_blocks(SAMPLE_BLOCKS_CH1)
        texts = [b["text"] for b in result]
        assert not any("王道" == t.strip() for t in texts), "Watermark block should be removed"

    def test_header_filtered(self):
        from app.features.wangdao_preprocessor import preprocess_wangdao_blocks
        blocks = [
            {"text": "2026年计算机网络考研复习指导",
             "boxes": [{"bbox": [200, 20, 900, 55], "conf": 0.9}],
             "page_width": 1128, "page_height": 1571, "page": 1, "block_index": 0},
            {"text": "正文内容",
             "boxes": [{"bbox": [100, 200, 900, 400], "conf": 0.95}],
             "page_width": 1128, "page_height": 1571, "page": 1, "block_index": 1},
        ]
        result = preprocess_wangdao_blocks(blocks)
        assert len(result) == 1
        assert result[0]["text"] == "正文内容"

    def test_section_markers_detected(self):
        from app.features.structure_analyzer import analyze_structure
        from app.features.text_normalizer import ImportTextNormalizer

        normalizer = ImportTextNormalizer()
        from app.features.wangdao_preprocessor import preprocess_wangdao_blocks
        preprocessed = preprocess_wangdao_blocks(SAMPLE_BLOCKS_CH1)
        normalized = normalizer.normalize(preprocessed)
        structure = analyze_structure(normalized)

        marker_types = [m["marker_type"] for m in structure["section_markers"]]
        assert "exercise_start" in marker_types
        assert "answer_start" in marker_types
        assert "summary" in marker_types

    def test_structure_mode_separated(self):
        result = run_pipeline_stages(SAMPLE_BLOCKS_CH1)
        assert result["structure"]["mode"] == "SEPARATED"
        assert result["structure"]["confidence"] >= 0.8

    def test_content_pages_identified(self):
        result = run_pipeline_stages(SAMPLE_BLOCKS_CH1)
        content_pages = result["structure"]["content_pages"]
        assert 1 in content_pages or 2 in content_pages

    def test_question_extraction_count(self):
        result = run_pipeline_stages(SAMPLE_BLOCKS_CH1)
        assert len(result["questions"]) == 4, (
            f"Expected 4 questions, got {len(result['questions'])}: "
            f"{[q['number'] for q in result['questions']]}"
        )

    def test_question_extraction_metrics(self):
        result = run_pipeline_stages(SAMPLE_BLOCKS_CH1)
        metrics = compute_metrics(result["questions"], EXPECTED_QUESTIONS_CH1)
        assert metrics["precision"] >= 0.95, f"Precision too low: {metrics}"
        assert metrics["recall"] >= 0.95, f"Recall too low: {metrics}"
        assert not metrics["false_positives"], f"False positives: {metrics['false_positives']}"

    def test_options_extracted(self):
        result = run_pipeline_stages(SAMPLE_BLOCKS_CH1)
        for q in result["questions"]:
            assert q["has_options"], f"Question {q['number']} missing options"
            assert len(q["option_lines"]) >= 4, (
                f"Question {q['number']} has {len(q['option_lines'])} options, expected 4"
            )

    def test_content_not_detected_as_questions(self):
        result = run_pipeline_stages(SAMPLE_BLOCKS_CH1)
        for q in result["questions"]:
            text = q["raw_question_text"]
            assert "广域网" not in text, "Content '广域网' detected as question"
            assert "城域网" not in text, "Content '城域网' detected as question"
            assert "局域网" not in text, "Content '局域网' detected as question"

    def test_no_watermark_in_output(self):
        result = run_pipeline_stages(SAMPLE_BLOCKS_CH1)
        assert result["removed_by_preprocess"] >= 1

    def test_knowledge_only_numbered_text_not_extracted(self):
        result = run_pipeline_stages(SAMPLE_KNOWLEDGE_ONLY_NUMBERED, import_mode="book")
        assert result["questions"] == [], (
            "Knowledge-only numbered prose should not be extracted as questions: "
            f"{[q['raw_question_text'] for q in result['questions']]}"
        )

    def test_answer_only_page_not_extracted_as_stems(self):
        result = run_pipeline_stages(SAMPLE_ANSWER_ONLY, import_mode="book")
        assert result["questions"] == [], (
            "Answer-only pages should not create new question stems: "
            f"{[q['raw_question_text'] for q in result['questions']]}"
        )

    def test_mixed_prose_and_exercise_keeps_exercise_only(self):
        result = run_pipeline_stages(SAMPLE_MIXED_PROSE_AND_EXERCISE, import_mode="book")
        questions = result["questions"]
        assert len(questions) == 1, f"Expected one real exercise, got {len(questions)}"
        q = questions[0]
        assert q["number"] == 1
        assert q["has_options"]
        assert len(q["option_lines"]) >= 4
        text = q["raw_question_text"]
        assert "下列关于栈" in text
        assert "栈的定义" not in text
        assert "例题解析" not in text

    def test_two_column_prose_and_question_keeps_question_only(self):
        result = run_pipeline_stages(SAMPLE_TWO_COLUMN_PROSE_AND_QUESTIONS, import_mode="book")
        questions = result["questions"]
        assert len(questions) == 1, f"Expected one two-column exercise, got {len(questions)}"
        q = questions[0]
        assert q["number"] == 1
        assert q["has_options"]
        assert len(q["option_lines"]) >= 4
        text = q["raw_question_text"]
        assert "下列关于二叉树" in text
        assert "定义：二叉树" not in text
        assert "证明：" not in text


# ---------------------------------------------------------------------------
# Live OCR tests (requires PaddleOCR + PDF)
# ---------------------------------------------------------------------------

def run_live_ocr_pipeline(pages: range | None = None) -> dict:
    """Run OCR on actual PDF and evaluate pipeline."""
    if not WANGDAO_PDF.exists():
        pytest.skip(f"PDF fixture not found: {WANGDAO_PDF}")

    from app.services.ocr_service import ocr_pages_with_boxes

    pdf_content = WANGDAO_PDF.read_bytes()

    # Render pages
    import fitz
    doc = fitz.open(stream=pdf_content, filetype="pdf")
    total_pages = doc.page_count

    if pages is None:
        # Default: test pages 28-35 (typical Chapter 1 exercise section)
        pages = range(28, min(36, total_pages))

    raw_blocks: list[dict] = []
    page_sizes: dict[int, tuple[int, int]] = {}

    for page_idx in pages:
        if page_idx >= total_pages:
            break
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        page_sizes[page_idx] = (pix.width, pix.height)

        results = ocr_pages_with_boxes([(page_idx, img_bytes)])
        if page_idx in results:
            result = results[page_idx]
            pw, ph = page_sizes[page_idx]
            raw_blocks.append({
                "page": page_idx + 1,
                "block_index": len(raw_blocks),
                "text": result.text,
                "boxes": result.boxes or [],
                "page_width": pw,
                "page_height": ph,
            })

    doc.close()

    if not raw_blocks:
        return {"error": "No blocks extracted"}

    return run_pipeline_stages(raw_blocks)


@pytest.mark.skipif(
    not WANGDAO_PDF.exists(),
    reason="wangdao_408.pdf fixture not available"
)
class TestWangdaoLiveOCR:
    """Live OCR tests — require PaddleOCR and the PDF fixture.

    These tests may fail in environments where PaddleOCR cannot run
    (e.g., CPU-only WSL2 with ABI mismatches). Use --live-ocr CLI mode
    for manual verification in a properly configured environment.
    """

    @pytest.fixture(autouse=True)
    def _skip_if_ocr_unavailable(self):
        try:
            import fitz  # noqa: F401

            from app.services.ocr_service import ocr_pages_with_boxes
        except ImportError as e:
            pytest.skip(f"OCR dependencies unavailable: {e}")

    def _run(self, pages=None):
        try:
            return run_live_ocr_pipeline(pages)
        except RuntimeError as e:
            if "could not execute" in str(e) or "primitive" in str(e):
                pytest.skip(f"PaddleOCR runtime error (environment issue): {e}")
            raise

    def test_live_extracts_questions(self):
        result = self._run()
        assert len(result["questions"]) > 0, "Should extract at least one question"

    def test_live_watermark_removal(self):
        result = self._run()
        assert result["removed_by_preprocess"] >= 0
        for q in result["questions"]:
            assert "王道" not in q["raw_question_text"]
            assert "kaoya" not in q["raw_question_text"].lower()

    def test_live_structure_detection(self):
        result = self._run()
        mode = result["structure"]["mode"]
        assert mode in ("SEPARATED", "INLINE"), f"Unexpected mode: {mode}"


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

def _print_report(result: dict, expected: list[dict] | None = None):
    """Print human-readable evaluation report."""
    print("=" * 60)
    print("王道408 Pipeline 评测报告")
    print("=" * 60)

    print("\n[Pipeline 统计]")
    print(f"  预处理过滤块数: {result['removed_by_preprocess']}")
    print(f"  标准化后块数: {result['normalized_count']}")
    print(f"  结构模式: {result['structure']['mode']} (置信度: {result['structure']['confidence']})")
    print(f"  Section markers: {len(result['structure']['section_markers'])}")

    markers = result["structure"]["section_markers"]
    for m in markers:
        print(f"    - page {m['page']}: {m['marker_type']} ({m['text'][:30]})")

    print("\n[页面分类]")
    print(f"  题目页: {result['structure']['question_pages']}")
    print(f"  答案页: {result['structure']['answer_pages']}")
    print(f"  正文页: {result['structure']['content_pages']}")

    print(f"\n[题目提取] 共 {len(result['questions'])} 题")
    for q in result["questions"]:
        opts = ",".join(sorted(q["option_lines"].keys())) if q["option_lines"] else "无"
        print(f"  #{q['number']:02d} page={q['page_start']} opts=[{opts}] conf={q['confidence']}")
        print(f"       {q['raw_question_text'][:70]}...")

    if expected:
        metrics = compute_metrics(result["questions"], expected)
        print("\n[评测指标]")
        print(f"  Precision: {metrics['precision']}")
        print(f"  Recall: {metrics['recall']}")
        print(f"  F1: {metrics['f1']}")
        print(f"  选项完整率: {metrics['option_completeness']}")
        if metrics["false_positives"]:
            print(f"  误检题号: {metrics['false_positives']}")
        if metrics["false_negatives"]:
            print(f"  漏检题号: {metrics['false_negatives']}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="王道408 PDF pipeline评测")
    parser.add_argument("--live-ocr", action="store_true", help="使用实际OCR处理PDF")
    parser.add_argument("--pages", type=str, default=None, help="页码范围，如 28-35")
    parser.add_argument("--save", type=str, default=None, help="保存结果到JSON文件")
    args = parser.parse_args()

    if args.live_ocr:
        pages = None
        if args.pages:
            parts = args.pages.split("-")
            start = int(parts[0])
            end = int(parts[1]) if len(parts) > 1 else start + 1
            pages = range(start, end + 1)

        print("Running live OCR pipeline...")
        result = run_live_ocr_pipeline(pages)
        if "error" in result:
            print(f"Error: {result['error']}")
            sys.exit(1)
        _print_report(result)
    else:
        print("Running structure-only evaluation (no OCR)...")
        result = run_pipeline_stages(SAMPLE_BLOCKS_CH1)
        _print_report(result, EXPECTED_QUESTIONS_CH1)

    if args.save:
        save_data = {
            "questions": result["questions"],
            "structure": {
                k: v for k, v in result["structure"].items()
                if k != "section_markers"
            },
            "removed_by_preprocess": result["removed_by_preprocess"],
        }
        Path(args.save).write_text(json.dumps(save_data, ensure_ascii=False, indent=2))
        print(f"\nResults saved to {args.save}")


if __name__ == "__main__":
    main()

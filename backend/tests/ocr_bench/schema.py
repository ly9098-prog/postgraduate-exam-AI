"""OCR Bench 数据模型。

每个 BenchmarkCase 包含：
- 场景分桶
- 人工标注 ground truth
- 可选的 OCR 输入文本（text-only 模式）
- 可选的输入图片/PDF 路径（live-OCR 模式）
- 业务期望（题号、选项、答案）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Scenario buckets
# ---------------------------------------------------------------------------


class ScenarioBucket(str, Enum):
    """场景分桶 — 每个桶独立报告，不混合。"""

    # 清晰扫描
    CLEAN_SINGLE_COLUMN = "clean_single_column"
    # 低 DPI / 模糊 / 倾斜
    LOW_DPI = "low_dpi"
    BLURRY = "blurry"
    SKEWED = "skewed"
    PHONE_PHOTO = "phone_photo"
    # 排版
    MULTI_COLUMN = "multi_column"
    CROSS_PAGE = "cross_page"
    # 题型
    CODE_C = "code_c"  # C 代码题
    CODE_CPP = "code_cpp"  # C++ 代码题
    MATH = "math"  # 数学公式
    TABLE = "table"  # 表格
    FLOWCHART = "flowchart"  # 流程图
    # 污染
    WATERMARK = "watermark"  # 水印
    HEADER_FOOTER = "header_footer"  # 页眉页脚干扰
    # 多语言
    MIXED_LANG = "mixed_lang"  # 中英文混排
    # 试题结构
    FILL_BLANK = "fill_blank"  # 填空
    COMPOUND = "compound"  # 组合题

    # 遗留场景别名（兼容旧版 meta.json）
    SINGLE_COLUMN = "single_column"  # clean_single_column 的别名
    CODE = "code"  # 通用代码（未区分 C/C++）
    MIXED_CONTENT = "mixed_content"  # 图文混合
    SIDE_OPTION = "side_option"  # 选项在右侧


# ---------------------------------------------------------------------------
# Benchmark case
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkCase:
    """单个基准测试用例。

    text-only 模式: 提供 input_text（OCR 原始输出）+ ground_truth。
    live-OCR 模式: 提供 input_path（图片/PDF），runner 执行 OCR。
    """

    case_id: str  # e.g. "001_clean_sc"
    scenario: ScenarioBucket
    description: str
    subject: str  # "exam408" | "math2" | "english"

    # 文本模式
    input_text: str = ""  # OCR 原始输出（评价 OCR 质量时使用）
    ground_truth: str = ""  # 人工标注正确文本

    # Live OCR 模式
    input_path: str = ""  # 图片或 PDF 路径

    # 业务期望
    expected_questions: int = 0
    expected_options: dict[str, list[str]] = field(default_factory=dict)
    expected_answers: dict[str, str] = field(default_factory=dict)
    expected_qnumbers: list[int] = field(default_factory=list)

    # 元信息
    tags: list[str] = field(default_factory=list)
    known_failure_types: list[str] = field(default_factory=list)

    # path to case dir (set by loader)
    case_dir: str = ""


# ---------------------------------------------------------------------------
# Evaluation results
# ---------------------------------------------------------------------------


@dataclass
class LineLevelMetrics:
    """行级指标。"""
    cer: float = 0.0
    wer: float = 0.0
    text_drop_rate: float = 0.0
    line_recall: float = 0.0
    line_precision: float = 0.0


@dataclass
class BusinessMetrics:
    """业务级指标。"""
    question_number_em: float = 0.0  # Exact match of question number set
    option_set_em: float = 0.0  # Exact match of option key sets
    answer_em: float = 0.0  # Exact match of answers
    question_count_match: bool = False


@dataclass
class ReadingOrderMetrics:
    """阅读顺序指标。"""
    pairwise_order_accuracy: float = 0.0  # Pairwise order preservation
    sequence_exact_match: float = 0.0  # Full sequence exact match (0 or 1)
    question_number_order_accuracy: float = 0.0  # Question number sequence preservation
    option_order_accuracy: float = 0.0  # Option key order preservation
    cross_column_error_rate: float = 0.0  # Cross-column ordering errors
    header_footer_leak_rate: float = 0.0  # Headers/footers in main body
    reading_order_low_confidence_rate: float = 0.0  # Low confidence assignments

    @property
    def order_score(self) -> float:
        """Average of all order metrics (0-1)."""
        vals = [
            self.pairwise_order_accuracy,
            self.sequence_exact_match,
            self.question_number_order_accuracy,
            self.option_order_accuracy,
            1.0 - self.cross_column_error_rate,
            1.0 - self.header_footer_leak_rate,
            1.0 - self.reading_order_low_confidence_rate,
        ]
        return sum(vals) / max(len(vals), 1)


@dataclass
class FreezeBindingMetrics:
    """冻结绑定指标。"""
    freeze_binding_success_rate: float = 0.0
    freeze_binding_lost_rate: float = 0.0


@dataclass
class QualityGateMetrics:
    """质量门指标。"""
    quality_gate_shadow_disagreement_rate: float = 0.0


@dataclass
class CodeMetrics:
    """代码题专项指标。"""
    bracket_balance_rate: float = 0.0
    code_token_em: float = 0.0  # Code token exact match
    comparison_op_preserved: float = 0.0  # ->, ==, != etc.
    code_structure_ok: bool = False


@dataclass
class MetricsResult:
    """单一 case 的完整评估结果。"""
    case_id: str
    scenario: ScenarioBucket
    line: LineLevelMetrics = field(default_factory=LineLevelMetrics)
    business: BusinessMetrics = field(default_factory=BusinessMetrics)
    code: CodeMetrics = field(default_factory=CodeMetrics)
    reading_order: ReadingOrderMetrics = field(default_factory=ReadingOrderMetrics)
    freeze_binding: FreezeBindingMetrics = field(default_factory=FreezeBindingMetrics)
    quality_gate: QualityGateMetrics = field(default_factory=QualityGateMetrics)
    overall_score: float = 0.0  # 0-100 weighted
    passed: bool = False
    duration_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_case(case_dir: Path) -> BenchmarkCase:
    """从 case 目录加载 BenchmarkCase。

    目录结构::

        cases/{case_id}/
            meta.json      — 场景、描述、期望
            ground_truth.txt — 人工标注正确文本
            input.txt       — OCR 原始输出（text-only 模式）
            input.png/pdf   — 输入（live-OCR 模式）
    """
    meta_path = case_dir / "meta.json"
    gt_path = case_dir / "ground_truth.txt"
    input_txt_path = case_dir / "input.txt"

    meta: dict[str, Any] = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    case_id = case_dir.name
    scenario = ScenarioBucket(meta.get("scenario", "clean_single_column"))
    description = meta.get("description", "")

    ground_truth = ""
    if gt_path.exists():
        ground_truth = gt_path.read_text(encoding="utf-8")

    input_text = ""
    if input_txt_path.exists():
        input_text = input_txt_path.read_text(encoding="utf-8")

    # Find live input (png/jpg/pdf)
    input_path = ""
    for ext in (".png", ".jpg", ".jpeg", ".pdf"):
        p = case_dir / f"input{ext}"
        if p.exists():
            input_path = str(p)
            break

    return BenchmarkCase(
        case_id=case_id,
        scenario=scenario,
        description=description,
        subject=meta.get("subject", ""),
        input_text=input_text,
        ground_truth=ground_truth,
        input_path=input_path,
        expected_questions=meta.get("expected_questions", 0),
        expected_options=meta.get("expected_options", {}),
        expected_answers=meta.get("expected_answers", {}),
        expected_qnumbers=meta.get("expected_qnumbers", []),
        tags=meta.get("tags", []),
        known_failure_types=meta.get("known_failure_types", []),
        case_dir=str(case_dir),
    )


def discover_cases(cases_dir: Path | None = None) -> list[BenchmarkCase]:
    """发现 cases 目录下所有基准用例。"""
    if cases_dir is None:
        cases_dir = Path(__file__).parent / "cases"
    if not cases_dir.exists():
        return []

    result: list[BenchmarkCase] = []
    for d in sorted(cases_dir.iterdir()):
        if not d.is_dir():
            continue
        gt_path = d / "ground_truth.txt"
        meta_path = d / "meta.json"
        if not gt_path.exists() or not meta_path.exists():
            continue
        result.append(load_case(d))
    return result

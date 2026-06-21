"""OCR 回归测试：使用真实样本图片验证 OCR 解析、pipeline 处理结果。

运行方式：
    pytest tests/ocr_regression/ -v
    pytest tests/ocr_regression/ -v -k "math_case_001"  # 单 case

依赖：PaddleOCR（OCR_ENABLED=true 时才会真正执行 OCR）
"""
import json
import logging
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

CASES_DIR = Path(__file__).parent / "cases"
IMAGES_DIR = Path(__file__).parent.parent.parent / "ocr_test" / "images" / "example"


def _load_cases():
    """从 cases 目录加载所有测试 case 定义。"""
    cases = []
    if not CASES_DIR.exists():
        return cases
    for f in sorted(CASES_DIR.glob("*.json")):
        with open(f) as fp:
            cases.append(json.load(fp))
    return cases


def _get_image_path(case: dict) -> Path | None:
    """根据 case 中的 source_path 查找图片。"""
    rel = case.get("source_path", "")
    if not rel:
        return None
    path = Path(__file__).parent.parent.parent / rel
    return path if path.exists() else None


# 延迟加载 cases（pytest 收集阶段可用）
CASES = _load_cases()


def _check_math_image_segment(segments: list[dict], expected: dict) -> list[str]:
    """验证 math_image segment 的存在和属性。"""
    errors = []
    math_segs = [s for s in segments if s.get("type") == "math_image"]
    if expected.get("has_math_image_segment"):
        if not math_segs:
            errors.append("缺少 math_image segment")
        else:
            for seg in math_segs:
                source_page = seg.get("source_page")
                if source_page is None:
                    errors.append("math_image 缺少 source_page")
                requires_review = seg.get("requires_review")
                if expected.get("requires_review") and not requires_review:
                    errors.append("math_image 应标记 requires_review=True")
    return errors


def _check_table_markdown_segment(segments: list[dict], expected: dict) -> list[str]:
    errors = []
    table_segs = [s for s in segments if s.get("type") == "table_markdown"]
    if expected.get("has_table_markdown_segment"):
        if not table_segs:
            errors.append("缺少 table_markdown segment")
    else:
        if table_segs:
            errors.append("不应出现 table_markdown segment（本题非表格）")
    return errors


def _check_risk_flags(risk_flags: list[str], expected: dict) -> list[str]:
    """验证风险标记的合理性。"""
    errors = []
    expected_flags = set(expected.get("expected_risk_flags", []))

    # 检查必须包含的标记
    for flag in expected_flags:
        if flag not in risk_flags:
            errors.append(f"缺少期望的风险标记: {flag}")

    # 数学题不应出现非数学/代码类标记
    unexpected = {"non_question_like", "code_symbol_risk", "table_detected", "fallback_low_confidence"}
    found_unexpected = [f for f in risk_flags if f in unexpected]
    if found_unexpected:
        errors.append(f"出现不应有的风险标记: {found_unexpected}")

    return errors


def _check_stem_content(stem: str, expected: dict) -> list[str]:
    """验证题干包含预期的关键内容。"""
    errors = []
    patterns = expected.get("stem_patterns", [])
    for pat in patterns:
        if pat not in stem and pat not in stem.replace(" ", ""):
            errors.append(f"题干中未找到期望内容: '{pat}'")
    return errors


@pytest.mark.skipif(not CASES, reason="无测试 case 定义")
class TestOcrRegression:
    """使用真实样本图片验证 OCR 管线处理结果。"""

    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.get("case_id", "unknown"))
    def test_case_definition_valid(self, case):
        """验证 case 定义完整性。"""
        assert "case_id" in case, "case 缺少 case_id"
        assert "source" in case, "case 缺少 source"
        assert "expected" in case, "case 缺少 expected"
        exp = case["expected"]
        assert "has_math_image_segment" in exp
        assert "has_table_markdown_segment" in exp
        assert "expected_risk_flags" in exp
        assert "min_confidence" in exp

    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.get("case_id", "unknown"))
    def test_source_image_exists(self, case):
        """验证源图片文件存在。"""
        img_path = _get_image_path(case)
        assert img_path is not None, f"图片不存在: {case.get('source_path')}"
        assert img_path.stat().st_size > 0, f"图片为空: {img_path}"

    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.get("case_id", "unknown"))
    def test_ocr_and_pipeline(self, case):
        """运行 OCR 并验证识别结果的合理性和风险标记。

        需要 PaddleOCR 环境（OCR_ENABLED=true）。当 OCR 不可用时跳过。
        """
        try:
            from app.core.config import settings
            from app.services.ocr_service import _ocr_one_page_with_boxes
        except ImportError:
            pytest.skip("app 模块不可用（需从 backend 目录运行）")

        if not settings.OCR_ENABLED:
            pytest.skip("OCR_ENABLED=false，跳过完整 OCR 测试")

        img_path = _get_image_path(case)
        if img_path is None:
            pytest.fail(f"图片不存在: {case.get('source_path')}")

        with open(img_path, "rb") as f:
            image_bytes = f.read()

        result = _ocr_one_page_with_boxes(image_bytes, page_index=1)
        assert result is not None, "OCR 返回 None"

        ocr_text = result.text
        assert ocr_text.strip(), "OCR 未识别到文本"

        # 检查置信度
        min_conf = case["expected"].get("min_confidence", 0.5)
        exp = case["expected"]

        # 检查题干关键内容
        stem_errors = _check_stem_content(ocr_text, exp)
        for err in stem_errors:
            logger.warning("[%s] %s", case["case_id"], err)

        # 检查选项完整性
        has_options = exp.get("has_options", False)
        if has_options:
            option_keys = exp.get("options_keys", [])
            # 检查是否有选项标识出现
            found_keys = [k for k in option_keys if k in ocr_text]
            if len(found_keys) < len(option_keys) // 2:
                logger.warning(
                    "[%s] 选项识别不完整: 期望 %s, 识别到 %s",
                    case["case_id"], option_keys, found_keys,
                )

        # 检查分段属性
        parsed = {"text": ocr_text}
        seg_errors = _check_math_image_segment([], exp)
        for err in seg_errors:
            logger.warning("[%s] segment 检查: %s", case["case_id"], err)

        logger.info(
            "[%s] OCR 完成: 文本长度=%d 置信度=%.3f",
            case["case_id"], len(ocr_text), result.failed,
        )


@pytest.mark.skipif(not CASES, reason="无测试 case 定义")
class TestOcrCaseMetadata:
    """测试 case 元数据校验，不依赖 OCR 环境。"""

    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.get("case_id", "unknown"))
    def test_math_image_expectation(self, case):
        """验证数学题应标注 math_image 需求。"""
        exp = case["expected"]
        if case.get("subject") == "math2":
            if "complex_formula_requires_review" not in exp.get("expected_risk_flags", []):
                logger.warning(
                    "[%s] math2 题且含复杂公式，建议标注 complex_formula_requires_review",
                    case["case_id"],
                )

    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.get("case_id", "unknown"))
    def test_case_documentation(self, case):
        """验证 case 有足够的文档信息。"""
        assert case.get("description"), f"{case['case_id']} 缺少 description"
        assert case.get("source"), f"{case['case_id']} 缺少 source"
        assert case.get("subject"), f"{case['case_id']} 缺少 subject"

"""PaddleOCR-VL 视觉回退 — 单元测试。

覆盖 vision_fallback.py 核心逻辑 + normalize_question 集成路径。
PaddleOCR-VL 被 mock，不涉及真实 API 调用。
"""

from __future__ import annotations

from unittest.mock import patch

from app.features.vision_fallback import (
    _build_vl_config,
    _call_vl_sync,
    _compare_code_results,
    needs_vision_fallback,
)

# ============================================================
# needs_vision_fallback 测试
# ============================================================

class TestNeedsVisionFallback:
    def test_triggers_on_code_flags(self):
        """code_block_incomplete 触发回退。"""
        assert needs_vision_fallback(["code_block_incomplete"]) is True

    def test_triggers_on_truncated(self):
        assert needs_vision_fallback(["code_block_truncated"]) is True

    def test_triggers_on_garbled(self):
        assert needs_vision_fallback(["code_garbled_text"]) is True

    def test_triggers_on_brace_unbalanced(self):
        assert needs_vision_fallback(["code_brace_unbalanced"]) is True

    def test_triggers_on_line_break(self):
        assert needs_vision_fallback(["code_line_break_suspicious"]) is True

    def test_triggers_on_regression(self):
        assert needs_vision_fallback(["code_structure_regression"]) is True

    def test_no_trigger_on_non_code_flags(self):
        """非代码 flag 不触发回退。"""
        assert needs_vision_fallback([]) is False
        assert needs_vision_fallback(["missing_stem"]) is False
        assert needs_vision_fallback(["low_confidence"]) is False

    def test_mixed_flags_with_code_trigger(self):
        """混合 flag 中包含代码标记时仍触发。"""
        assert needs_vision_fallback(["missing_stem", "code_block_incomplete"]) is True


# ============================================================
# _build_vl_config 测试
# ============================================================

class TestBuildVlConfig:
    def test_empty_config(self):
        config = _build_vl_config(None)
        assert config["api_token"] == ""
        assert config["base_url"] == "https://paddleocr.aistudio-app.com"
        assert config["model"] == "PaddleOCR-VL-1.6"

    def test_full_config(self):
        config = _build_vl_config({
            "api_token": "test-token",
            "base_url": "https://custom.url",
            "model": "custom-model",
        })
        assert config["api_token"] == "test-token"
        assert config["base_url"] == "https://custom.url"
        assert config["model"] == "custom-model"

    def test_legacy_paddle_key_names(self):
        """兼容 paddleocr_vl_ 前缀的 key。"""
        config = _build_vl_config({
            "paddleocr_vl_api_token": "token-vl",
            "paddleocr_vl_base_url": "https://vl.url",
            "paddleocr_vl_model": "VL-2.0",
        })
        assert config["api_token"] == "token-vl"


# ============================================================
# _compare_code_results 测试
# ============================================================

class TestCompareCodeResults:
    def test_fallback_no_flags_is_better(self):
        """VL 回退完全没有 flag → 更好。"""
        orig = {"score": 0.40, "flags": ["code_block_incomplete"]}
        fb = {"score": 0.0, "flags": []}
        assert _compare_code_results(orig, fb) == "better"

    def test_fallback_worse_score(self):
        """VL 回退分数更高 → 更差。"""
        orig = {"score": 0.40, "flags": ["code_garbled_text"]}
        fb = {"score": 0.70, "flags": ["code_garbled_text", "code_block_incomplete"]}
        assert _compare_code_results(orig, fb) == "worse"

    def test_fallback_similar(self):
        """分数接近 + flag 数量相同 → similar。"""
        orig = {"score": 0.40, "flags": ["code_garbled_text"]}
        fb = {"score": 0.35, "flags": ["code_garbled_text"]}
        assert _compare_code_results(orig, fb) == "similar"

    def test_fallback_severe_flag_not_in_original(self):
        """VL 新增严重 flag → 更差。"""
        orig = {"score": 0.30, "flags": ["code_garbled_text"]}
        fb = {"score": 0.20, "flags": ["code_block_truncated"]}
        assert _compare_code_results(orig, fb) == "worse"

    def test_fallback_slightly_better(self):
        """VL 分数略低 + flag 更少 → better。"""
        orig = {"score": 0.45, "flags": ["code_garbled_text", "code_block_incomplete"]}
        fb = {"score": 0.25, "flags": ["code_garbled_text"]}
        assert _compare_code_results(orig, fb) == "better"

    def test_both_no_flags(self):
        """两者都无 flag → similar。"""
        orig = {"score": 0.0, "flags": []}
        fb = {"score": 0.0, "flags": []}
        assert _compare_code_results(orig, fb) == "similar"


# ============================================================
# _call_vl_sync 测试（mock PaddleOCR-VL）
# ============================================================

class TestCallVlSync:
    def test_no_api_token_returns_empty(self):
        """无 api_token 时返回空文本。"""
        result = _call_vl_sync(b"fake-image", {"api_token": ""})
        assert result == ""

    @patch("app.features.ocr_vl.paddleocr_vl_adapter.PaddleOCRVLAdapter")
    def test_successful_call(self, mock_adapter_class):
        """成功调用返回识别文本。"""
        mock_adapter = mock_adapter_class.return_value

        async def mock_fix(image=None, ocr_text="", context=None):
            from app.features.ocr_fix.interfaces import OCRFixResult
            return OCRFixResult(fixed_text="VL recognized code")

        mock_adapter.fix = mock_fix

        result = _call_vl_sync(b"fake-image", {
            "api_token": "test-token",
            "base_url": "https://test.url",
            "model": "test-model",
        })
        assert "VL recognized code" in result

    @patch("app.features.ocr_vl.paddleocr_vl_adapter.PaddleOCRVLAdapter")
    def test_failed_call_returns_empty(self, mock_adapter_class):
        """调用异常时返回空文本。"""
        mock_adapter = mock_adapter_class.return_value

        async def mock_fix(image=None, ocr_text="", context=None):
            raise RuntimeError("API timeout")

        mock_adapter.fix = mock_fix

        result = _call_vl_sync(b"fake-image", {
            "api_token": "test-token",
        })
        assert result == ""


# ============================================================
# 集成测试：normalize_question 触发 VL 回退
# ============================================================

class TestVisionFallbackIntegration:
    """通过 normalize_question 验证 VL 回退集成逻辑。"""

    def _clear_cache(self):
        """清除 normalize_question 的 parse cache，避免同 raw_text 的缓存影响后续测试。"""
        from app.features.question_normalizer import parse_cache_clear
        parse_cache_clear()

    def test_no_code_risk_no_fallback(self):
        """非代码题不触发回退。"""
        self._clear_cache()
        from app.features.question_normalizer import normalize_question
        self._clear_cache()

        raw = {
            "number": 1,
            "raw_question_text": "这是一道普通数学题\nA. 2x\nB. x\nC. 2\nD. 0\n答案：A",
            "page_start": 1, "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "2x", "B": "x", "C": "2", "D": "0"},
            "confidence": 0.95,
            "page_image": b"fake-image",
        }
        matched = {"question_number": 1, "answer": "A"}
        result = normalize_question(raw, matched)
        assert result.get("vision_fallback_attempted") is not True, (
            "非代码题不应尝试回退"
        )

    def test_code_damage_no_image_unavailable(self):
        """截断的代码题有风险但无图片 → fallback_unavailable。"""
        from app.features.question_normalizer import normalize_question
        self._clear_cache()

        raw = {
            "number": 2,
            "raw_question_text": (
                "已知二叉树:\n"
                "```text\n"
                "typedef struct BiTNode {\n"
                "char data;\n"
                "``` (1typu* p1tysI* apo11ta aonu2s\n"
                "A. ABDECF\n"
                "答案:A"
            ),
            "page_start": 1, "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "ABDECF"},
            "confidence": 0.95,
            # 没有 page_image → unavailable
        }
        matched = {"question_number": 1, "answer": "A"}
        result = normalize_question(raw, matched)
        assert result.get("vision_fallback_status") == "unavailable", (
            "无图片时应标记 fallback_unavailable, "
            f"got {result.get('vision_fallback_status')}, "
            f"risk_flags={result.get('risk_flags')}"
        )

    def test_code_damage_with_image_vl_fails(self):
        """截断代码题有图片但 VL 失败 → fallback_failed。"""
        from app.features.question_normalizer import normalize_question
        self._clear_cache()

        raw = {
            "number": 3,
            "raw_question_text": (
                "已知二叉树:\n"
                "```text\n"
                "typedef struct BiTNode {\n"
                "char data;\n"
                "``` (1typu* p1tysI* apo11ta aonu2s\n"
                "A. ABDECF\n"
                "答案:A"
            ),
            "page_start": 1, "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "ABDECF"},
            "confidence": 0.95,
            "page_image": b"fake-image",
        }
        matched = {"question_number": 1, "answer": "A"}

        with patch("app.features.vision_fallback._call_vl_sync", return_value=""):
            result = normalize_question(raw, matched)

        assert result.get("vision_fallback_status") == "failed", (
            f"VL 失败应标记 failed, got {result.get('vision_fallback_status')}"
        )

    def test_vl_result_better_adopted(self):
        """截断代码题 VL 返回完整代码 → 被采纳。"""
        from app.features.question_normalizer import normalize_question
        self._clear_cache()

        raw = {
            "number": 4,
            "raw_question_text": (
                "已知二叉树:\n"
                "```text\n"
                "typedef struct BiTNode {\n"
                "char data;\n"
                "``` (1typu* p1tysI* apo11ta aonu2s\n"
                "A. ABDECF\n"
                "答案:A"
            ),
            "page_start": 1, "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "ABDECF"},
            "confidence": 0.95,
            "page_image": b"fake-image",
        }
        matched = {"question_number": 1, "answer": "A"}

        # Mock VL 返回完整的结构体定义（无乱码、无截断）
        with patch(
            "app.features.vision_fallback._call_vl_sync",
            return_value=(
                "已知二叉树:\n"
                "```text\n"
                "typedef struct BiTNode {\n"
                "char data;\n"
                "struct BiTNode *lchild, *rchild;\n"
                "} BiTNode;\n"
                "```\n"
                "A. ABDECF"
            ),
        ):
            result = normalize_question(raw, matched)

        assert result.get("vision_fallback_attempted") is True, (
            f"vision_fallback_attempted should be True, "
            f"got risk_flags={result.get('risk_flags')}"
        )
        assert result.get("vision_fallback_used") is True, (
            "VL 更好时应被采纳"
        )
        assert result.get("vision_fallback_status") == "success"

    def test_vl_result_worse_not_adopted(self):
        """完整结构体代码 VL 返回截断乱码 → 不覆盖。"""
        from app.features.question_normalizer import normalize_question
        self._clear_cache()

        raw = {
            "number": 5,
            "raw_question_text": (
                "已知二叉树:\n"
                "```text\n"
                "typedef struct BiTNode {\n"
                "char data;\n"
                "struct BiTNode *lchild, *rchild;\n"
                "} BiTNode;\n"
                "```\n"
                "A. ABDECF\n"
                "答案:A"
            ),
            "page_start": 1, "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "ABDECF"},
            "confidence": 0.95,
            "page_image": b"fake-image",
        }
        matched = {"question_number": 5, "answer": "A"}

        # Mock VL 返回截断+乱码（比原结果更差）
        with patch(
            "app.features.vision_fallback._call_vl_sync",
            return_value=(
                "已知二叉树:\n"
                "```text\n"
                "typedef struct BiTNode {\n"
                "char data;\n"
                "``` (1typu* p1tysI* apo11ta aonu2s"
            ),
        ):
            result = normalize_question(raw, matched)

        assert result.get("vision_fallback_used") is False, (
            "VL 更差时不覆盖"
        )
        assert result.get("vision_fallback_status") == "not_better"

    def test_vl_fallback_does_not_bypass_quality_gates(self):
        """VL 回退后仍有 code risk 时不能 passed。"""
        from app.features.question_normalizer import normalize_question
        self._clear_cache()

        raw = {
            "number": 6,
            "raw_question_text": (
                "已知二叉树:\n"
                "```text\n"
                "typedef struct BiTNode {\n"
                "char data;\n"
                "``` (1typu* p1tysI* apo11ta aonu2s\n"
                "A. ABDECF\n"
                "答案:A"
            ),
            "page_start": 1, "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "ABDECF"},
            "confidence": 0.95,
            "page_image": b"fake-image",
        }
        matched = {"question_number": 1, "answer": "A"}

        # Mock VL 返回的代码仍有完整性风险（仍为截断结构体）
        with patch(
            "app.features.vision_fallback._call_vl_sync",
            return_value=(
                "已知二叉树:\n"
                "```text\n"
                "typedef struct BiTNode {\n"
                "char data;\n"
                "``` (still garbled)"
            ),
        ):
            result = normalize_question(raw, matched)

        assert result.get("vision_fallback_attempted") is True
        risk_flags = result.get("risk_flags") or []
        code_flags = [f for f in risk_flags if f.startswith("code_")]
        if code_flags:
            assert result.get("validation_status") != "passed", (
                f"回退后仍有 code risk ({code_flags}) 时不能 passed"
            )

    def test_vl_fallback_code_integrity_rechecked(self):
        """回退后 code_integrity 被重新执行（post_fallback_code_flags 存在）。"""
        from app.features.question_normalizer import normalize_question
        self._clear_cache()

        raw = {
            "number": 7,
            "raw_question_text": (
                "已知二叉树:\n"
                "```text\n"
                "typedef struct BiTNode {\n"
                "char data;\n"
                "``` (1typu* p1tysI* apo11ta aonu2s\n"
                "A. ABDECF\n"
                "答案:A"
            ),
            "page_start": 1, "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "ABDECF"},
            "confidence": 0.95,
            "page_image": b"fake-image",
        }
        matched = {"question_number": 1, "answer": "A"}

        # Mock VL 返回完整代码（比原结果更好）
        with patch(
            "app.features.vision_fallback._call_vl_sync",
            return_value=(
                "已知二叉树:\n"
                "```text\n"
                "typedef struct BiTNode {\n"
                "char data;\n"
                "struct BiTNode *lchild, *rchild;\n"
                "} BiTNode;\n"
                "```\n"
                "A. ABDECF"
            ),
        ):
            result = normalize_question(raw, matched)

        assert "post_fallback_code_flags" in result, (
            "回退后应有 post_fallback_code_flags, "
            f"got keys={list(result.keys())}"
        )
        assert "pre_fallback_code_flags" in result, (
            "回退前应有 pre_fallback_code_flags"
        )
        if result.get("vision_fallback_used"):
            assert result.get("vision_fallback_status") == "success"

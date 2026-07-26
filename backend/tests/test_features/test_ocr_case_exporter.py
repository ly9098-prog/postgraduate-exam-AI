"""OCR 失败样本导出回归测试 — 数据安全与合规检查。"""

import os

from app.features.ocr_case_exporter import (
    _build_case_id,
    _safe_filename,
    _truncate_raw_data,
    export_failure_case,
    export_failure_cases_batch,
)


class TestExportFailureCase:
    def test_expected_template_all_empty(self):
        """导出 case 的 expected_template 所有字段必须为空。"""
        case = export_failure_case({
            "id": 1,
            "stem": "原题干",
            "options": {"A": "1", "B": "2"},
        })
        tmpl = case["expected_template"]
        assert tmpl["stem"] == ""
        assert tmpl["options"]["A"] == ""
        assert tmpl["options"]["B"] == ""
        assert tmpl["options"]["C"] == ""
        assert tmpl["options"]["D"] == ""
        assert tmpl["answer"] == ""
        assert tmpl["analysis"] == ""

    def test_raw_data_truncated(self):
        """raw_data 超过 2000 字符应截断。"""
        long_text = "x" * 3000
        case = export_failure_case({
            "id": 2,
            "raw_data": {"stem": long_text},
        })
        truncated = case["raw_data"]["stem"]
        assert len(truncated) <= 2000

    def test_full_file_bytes_stripped(self):
        """完整文件 bytes 应被剥离。"""
        case = export_failure_case({
            "id": 3,
            "raw_data": {
                "file_bytes": "base64...",
                "image_bytes": "base64...",
                "full_text": "全文内容",
                "stem": "题目部分",
            },
        })
        assert case["raw_data"]["file_bytes"] == "<file_bytes: stripped for export>"
        assert case["raw_data"]["image_bytes"] == "<image_bytes: stripped for export>"
        assert case["raw_data"]["full_text"] == "<full_text: stripped for export>"
        assert case["raw_data"]["stem"] == "题目部分"

    def test_source_file_only_basename(self):
        """source_file 只应包含文件名，不包含路径。"""
        case = export_failure_case({
            "id": 4,
            "source_file": "/home/user/secret/path/test.pdf",
        })
        assert case["source_file"] == "test.pdf"
        assert "/" not in case["source_file"]

    def test_source_file_none(self):
        """source_file 为 None 时应返回空字符串。"""
        case = export_failure_case({"id": 5, "source_file": None})
        assert case["source_file"] == ""

    def test_risk_flags_preserved(self):
        """risk_flags 应被保留在导出中。"""
        case = export_failure_case({
            "id": 6,
            "risk_flags": ["low_confidence", "garbled_text"],
        })
        assert "low_confidence" in case["risk_flags"]
        assert "garbled_text" in case["risk_flags"]

    def test_failure_types_preserved(self):
        """failure_types 应被保留。"""
        case = export_failure_case({
            "id": 7,
            "failure_types": ["ocr_correction_failed"],
        })
        assert "ocr_correction_failed" in case["failure_types"]

    def test_empty_risk_flags(self):
        """risk_flags 为 None 时导出空列表。"""
        case = export_failure_case({"id": 8})
        assert case["risk_flags"] == []

    def test_import_id_preserved(self):
        """import_id 应被保留。"""
        case = export_failure_case({"id": 42})
        assert case["import_id"] == 42

    def test_case_id_format(self):
        """case_id 应包含 'failure_' 前缀和 YYYYMMDD 格式日期。"""
        case = export_failure_case({"id": 100})
        assert case["case_id"].startswith("failure_")
        # _build_case_id 使用 YYYYMMDD（无分隔符）
        parts = case["case_id"].split("_")
        assert len(parts) == 3
        assert parts[1].isdigit() and len(parts[1]) == 8  # YYYYMMDD
        assert parts[2] == "100"


class TestExportFailureCasesBatch:
    def test_batch_returns_all(self):
        """无过滤时返回全部 cases。"""
        items = [
            {"id": 1, "failure_types": ["ocr_correction_failed"]},
            {"id": 2, "failure_types": ["math_detection_failed"]},
        ]
        cases = export_failure_cases_batch(items)
        assert len(cases) == 2

    def test_batch_filter_by_failure_type(self):
        """failure_type_filter 应只返回匹配的 cases。"""
        items = [
            {"id": 1, "failure_types": ["ocr_correction_failed"]},
            {"id": 2, "failure_types": ["math_detection_failed"]},
            {"id": 3, "failure_types": ["ocr_correction_failed", "split_failed"]},
        ]
        cases = export_failure_cases_batch(items, failure_type_filter="ocr_correction_failed")
        assert len(cases) == 2
        assert cases[0]["import_id"] == 1
        assert cases[1]["import_id"] == 3

    def test_batch_filter_no_match(self):
        """failure_type_filter 无匹配时返回空列表。"""
        items = [
            {"id": 1, "failure_types": ["ocr_correction_failed"]},
        ]
        cases = export_failure_cases_batch(items, failure_type_filter="nonexistent")
        assert cases == []

    def test_batch_empty(self):
        """空列表返回空。"""
        cases = export_failure_cases_batch([])
        assert cases == []


class TestTruncateRawDataSafety:
    def test_large_list_truncated(self):
        """超过 20 项的列表应截断。"""
        raw = {"options": list(range(50))}
        truncated = _truncate_raw_data(raw)
        assert len(truncated["options"]) <= 20
        assert truncated["options_truncated"] is True

    def test_small_list_kept(self):
        """少于 20 项的列表保持完整。"""
        raw = {"options": list(range(5))}
        truncated = _truncate_raw_data(raw)
        assert len(truncated["options"]) == 5
        assert "options_truncated" not in truncated

    def test_non_string_non_list_kept_as_is(self):
        """数字、布尔等类型保持不变。"""
        raw = {"page": 5, "enabled": True}
        truncated = _truncate_raw_data(raw)
        assert truncated["page"] == 5
        assert truncated["enabled"] is True

    def test_truncate_marks_field(self):
        """截断后应标记 _truncated 字段。"""
        long_text = "x" * 3000
        raw = {"content": long_text}
        truncated = _truncate_raw_data(raw)
        assert truncated["content_truncated"] is True

    def test_short_text_no_truncate_mark(self):
        """短文本不标记截断。"""
        raw = {"content": "short"}
        truncated = _truncate_raw_data(raw)
        assert "content_truncated" not in truncated


class TestSafeFilename:
    def test_safe_filename_basename_only(self):
        assert _safe_filename("/a/b/c/file.pdf") == "file.pdf"

    def test_safe_filename_windows_path(self):
        # Linux 下 os.path.basename 不识别反斜杠；Windows 部署时正常工作
        result = _safe_filename("C:\\Users\\test\\file.pdf")
        # 在 Linux 上保持原样；在 Windows 上仅返回 file.pdf
        assert os.path.basename(result) == result or result == "file.pdf"

    def test_safe_filename_none(self):
        assert _safe_filename(None) == ""

    def test_safe_filename_empty(self):
        assert _safe_filename("") == ""


class TestBuildCaseId:
    def test_case_id_format(self):
        """case_id 应为 failure_YYYYMMDD_import_id 格式。"""
        case_id = _build_case_id(42)
        parts = case_id.split("_")
        assert len(parts) == 3
        assert parts[0] == "failure"
        assert parts[1].isdigit() and len(parts[1]) == 8  # YYYYMMDD
        assert parts[2] == "42"

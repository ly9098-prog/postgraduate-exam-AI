"""公式科目范围纯函数兼容基线。

覆盖 formula_subject_scope 中可独立测试的纯规则：
- expand_formula_subject_code：逻辑科目代码扩展
- collapse_formula_catalog_subjects：数学目录聚合
"""

from __future__ import annotations

from app.services.formula_subject_scope import (
    FORMULA_MATH_SOURCE_CODES,
    collapse_formula_catalog_subjects,
    expand_formula_subject_code,
)


class TestExpandFormulaSubjectCode:
    """expand_formula_subject_code 将逻辑科目代码扩展为存储科目代码。"""

    def test_none_returns_none(self) -> None:
        assert expand_formula_subject_code(None) is None

    def test_empty_returns_none(self) -> None:
        assert expand_formula_subject_code("") is None

    def test_whitespace_returns_none(self) -> None:
        assert expand_formula_subject_code("   ") is None

    def test_math_expands_to_sources(self) -> None:
        result = expand_formula_subject_code("math")
        assert result == FORMULA_MATH_SOURCE_CODES

    def test_unknown_code_exact_match(self) -> None:
        assert expand_formula_subject_code("data_structure") == ("data_structure",)

    def test_existing_canonical_code_exact_match(self) -> None:
        assert expand_formula_subject_code("os") == ("os",)

    def test_whitespace_trimmed(self) -> None:
        result = expand_formula_subject_code("  math  ")
        assert result == FORMULA_MATH_SOURCE_CODES


class TestCollapseFormulaCatalogSubjects:
    """collapse_formula_catalog_subjects 将数学源科目聚合为一个合成节点。"""

    def test_non_math_passthrough(self) -> None:
        tree = [{"code": "os", "name": "操作系统"}]
        assert collapse_formula_catalog_subjects(tree, "os") == tree

    def test_none_subject_passthrough(self) -> None:
        tree = [{"code": "os", "name": "操作系统"}]
        assert collapse_formula_catalog_subjects(tree, None) == tree

    def test_math_no_sources_returns_empty(self) -> None:
        tree = [{"code": "os", "name": "操作系统"}]
        assert collapse_formula_catalog_subjects(tree, "math") == []

    def test_math_collapses_sources(self) -> None:
        tree = [
            {
                "code": "elementary_math",
                "name": "初等数学",
                "sort_order": 1,
                "id": 1,
                "exam_scope": "math1",
                "available_count": 10,
                "children": [
                    {"id": 11, "parent_id": 1, "sort_order": 2, "name": "代数"}
                ],
            },
            {
                "code": "math2_high_math",
                "name": "高等数学",
                "sort_order": 2,
                "id": 2,
                "exam_scope": "math1",
                "available_count": 20,
                "children": [
                    {"id": 21, "parent_id": 2, "sort_order": 1, "name": "微积分"}
                ],
            },
        ]
        result = collapse_formula_catalog_subjects(tree, "math")
        assert len(result) == 1
        node = result[0]
        assert node["code"] == "math"
        assert node["name"] == "数学"
        assert node["id"] == 0
        assert node["node_type"] == "subject"
        assert node["available_count"] == 30
        assert len(node["children"]) == 2
        # Children sorted by sort_order: 微积分(1) before 代数(2)
        assert node["children"][0]["name"] == "微积分"
        assert node["children"][1]["name"] == "代数"

    def test_math_different_exam_scopes_sets_none(self) -> None:
        tree = [
            {
                "code": "elementary_math",
                "name": "初等数学",
                "sort_order": 1,
                "id": 1,
                "exam_scope": "math1",
                "available_count": 5,
                "children": [],
            },
            {
                "code": "math2_high_math",
                "name": "高等数学",
                "sort_order": 2,
                "id": 2,
                "exam_scope": "math2",
                "available_count": 5,
                "children": [],
            },
        ]
        result = collapse_formula_catalog_subjects(tree, "math")
        assert result[0]["exam_scope"] is None

"""测试运行时变异防护。"""

import pytest

from app.core.immutable_regions import Region, TextRegions
from app.core.mutation_guard import (
    MutationError,
    allow_code_mutation,
    assert_no_mutation,
    guard,
    verify_all_code_regions,
)


class TestAssertNoMutation:
    def test_pass_when_unchanged(self):
        r1 = Region.create("c", "code", "int x;")
        r2 = Region.create("c", "code", "int x;")
        assert_no_mutation(r1, r2)  # should not raise

    def test_raise_on_code_change(self):
        r1 = Region.create("c", "code", "int x;")
        r2 = Region.create("c", "code", "int y;")  # different content
        with pytest.raises(MutationError, match="Code region mutation"):
            assert_no_mutation(r1, r2)

    def test_skip_text(self):
        r1 = Region.create("t", "text", "hello")
        r2 = Region.create("t", "text", "world")
        assert_no_mutation(r1, r2)  # text mutations are allowed


class TestVerifyAllCodeRegions:
    def test_all_clean(self):
        tr = TextRegions.from_fenced_text("```text\nint a;\n```")
        assert verify_all_code_regions(tr) == []

    def test_empty(self):
        assert verify_all_code_regions([]) == []

    def test_no_code_regions(self):
        tr = TextRegions([Region.create("t", "text", "hello")])
        assert verify_all_code_regions(tr) == []


class TestGuard:
    def test_str_input_passthrough(self):
        def identity(t):
            return t

        result = guard(identity, "int a = 1;\nint b = 2;", trace_id="test", stage_name="test")
        assert isinstance(result, str) or isinstance(result, TextRegions)

    def test_text_regions_input(self):
        tr = TextRegions.from_text("int a = 1;", trace_id="test")

        def identity(t):
            return t

        result = guard(identity, tr, stage_name="test")
        assert isinstance(result, TextRegions)
        # code regions should be intact
        for r in result:
            assert r.verify_integrity()

    def test_guard_detects_mutation(self):
        tr = TextRegions.from_text("int a = 1;\nint b = 2;", trace_id="test")

        def mutate_code(t: TextRegions) -> TextRegions:
            # 尝试修改 code 区域
            regions = list(t.regions)
            for i, r in enumerate(regions):
                if r.is_code:
                    regions[i] = Region.create(r.id, r.type, "MODIFIED")
            return TextRegions(regions)

        with pytest.raises(MutationError, match="Code region mutation"):
            guard(mutate_code, tr, stage_name="test_mutator")


class TestAllowCodeMutation:
    def test_context_manager(self):
        # 确保上下文管理器本身可用
        with allow_code_mutation():
            pass  # 不抛出即可

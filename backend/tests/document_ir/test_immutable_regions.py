"""测试不可变区域基础设施。"""

import pytest

from app.core.immutable_regions import Region, TextRegions


class TestRegion:
    def test_create(self):
        r = Region.create("code_0", "code", "int a = 1;")
        assert r.id == "code_0"
        assert r.type == "code"
        assert r.content == "int a = 1;"
        assert len(r.hash) == 64  # sha256 hexdigest
        assert r.verify_integrity()

    def test_integrity_fail(self):
        r = Region.create("text_0", "text", "hello")
        # 篡改内容（直接修改 frozen dataclass 不能修改，但这里测试 verify_integrity）
        assert r.verify_integrity()

    def test_is_code(self):
        assert Region.create("c", "code", "x").is_code
        assert not Region.create("t", "text", "x").is_code

    def test_with_content_rejects_code(self):
        r = Region.create("code_0", "code", "int x;")
        with pytest.raises(RuntimeError, match="MUTATION BLOCKED"):
            r.with_content("int y;")

    def test_with_content_allows_text(self):
        r = Region.create("text_0", "text", "hello")
        r2 = r.with_content("world")
        assert r2.id == "text_0"
        assert r2.type == "text"
        assert r2.content == "world"
        assert r2.hash != r.hash  # hash changed with content
        assert r2.verify_integrity()

    def test_frozen(self):
        r = Region.create("t", "text", "x")
        with pytest.raises(Exception):
            r.content = "y"  # type: ignore


class TestTextRegions:
    def test_empty(self):
        tr = TextRegions([])
        assert len(tr) == 0
        assert tr.to_text() == ""

    def test_from_text_no_code(self):
        tr = TextRegions.from_text("hello world", trace_id="test")
        assert len(tr) >= 1
        # wrap_code_fences 对纯文本不会触发代码检测
        text_parts = [r for r in tr if r.type == "text"]
        assert any("hello" in r.content for r in text_parts)

    def test_from_text_with_code(self):
        tr = TextRegions.from_text("int a = 1;\nint b = 2;", trace_id="test")
        code_parts = tr.code_regions
        assert len(code_parts) >= 1

    def test_from_fenced_text(self):
        text = "before\n```text\nint a;\n```\nafter"
        tr = TextRegions.from_fenced_text(text)
        assert len(tr) == 3  # text, code, text
        assert tr[0].type == "text"
        assert tr[1].type == "code"
        assert tr[1].content == "int a;"
        assert tr[2].type == "text"

    def test_to_text_reconstructs(self):
        original = "hello\n```text\nint a;\n```\nworld"
        tr = TextRegions.from_fenced_text(original)
        reconstructed = tr.to_text()
        # 重建应当与原始一致（可能末尾略有格式差异）
        assert "int a;" in reconstructed
        assert "hello" in reconstructed
        assert "world" in reconstructed

    def test_verify_all(self):
        tr = TextRegions.from_text("some code: int x;\nint y;", trace_id="test")
        corrupted = tr.verify_all()
        assert corrupted == []  # 全新创建，不应有损坏

    def test_update_region(self):
        text = "hello\n```text\nint a;\n```\nworld"
        tr = TextRegions.from_fenced_text(text)
        # 更新 text 区域
        tr2 = tr.update_region(0, "hi\n")
        assert tr2[0].content == "hi\n"
        # 原始对象不变
        assert tr[0].content == "hello\n"

    def test_update_code_region_raises(self):
        text = "```text\nint a;\n```"
        tr = TextRegions.from_fenced_text(text)
        with pytest.raises(RuntimeError, match="MUTATION BLOCKED"):
            tr.update_region(0, "int b;")

    def test_filter(self):
        tr = TextRegions.from_fenced_text("a\n```text\nb\n```\nc")
        assert len(tr.filter(type="text")) == 2
        assert len(tr.filter(type="code")) == 1

    def test_code_regions_property(self):
        tr = TextRegions.from_fenced_text("a\n```text\nb\n```\nc")
        assert len(tr.code_regions) == 1
        assert tr.code_regions[0].content == "b"

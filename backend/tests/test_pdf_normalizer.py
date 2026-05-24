"""pdf_text_normalizer 单元测试"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.pdf_text_normalizer import merge_broken_lines, normalize_pdf_text  # noqa: E402

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def ok(name: str) -> None:
    PASSED.append(name)
    print(f"  ✓ {name}")


def fail(name: str, msg: str) -> None:
    FAILED.append((name, msg))
    print(f"  ✗ {name}: {msg}")


def check(name: str, cond: bool, msg: str = "") -> None:
    if cond:
        ok(name)
    else:
        fail(name, msg)


# ── 测试用例 ──────────────────────────────────────────────────────────────────

def test_basic_chinese_merge() -> None:
    print("\n[1] 基本中文断行合并")
    inp = "覆盖10+128=138个盘块，已覆盖256个盘块（文件超过138，\n但最后1 KB数据对应第256个盘块。"
    out = merge_broken_lines(inp)
    check("逗号后断行合并",
          "覆盖10+128=138个盘块，已覆盖256个盘块（文件超过138，但最后1 KB数据对应第256个盘块。" in out,
          repr(out))
    check("结果不含多余换行", "\n" not in out.strip(), repr(out))


def test_sentence_end_no_merge() -> None:
    print("\n[2] 句号/问号后不合并")
    inp = "这是第一句。\n这是第二句。"
    out = merge_broken_lines(inp)
    check("句号后保留换行", "\n" in out, repr(out))

    inp2 = "这是第一句？\n这是第二句。"
    out2 = merge_broken_lines(inp2)
    check("问号后保留换行", "\n" in out2, repr(out2))


def test_structure_lines_not_merged() -> None:
    print("\n[3] 结构行（题号/选项/答案/解析）不被合并")
    inp = "这是题干，\nA. 选项一\nB. 选项二\n答案：A\n解析：原因如下。"
    out = merge_broken_lines(inp)
    check("选项行保留独立", "A. 选项一" in out and "\n" in out, repr(out))
    check("答案行保留独立", "答案：A" in out, repr(out))
    check("解析行保留独立", "解析：原因如下。" in out, repr(out))


def test_question_number_not_merged() -> None:
    print("\n[4] 题号行不被合并")
    inp = "1. 第一题题干，很长，\n2. 第二题题干"
    out = merge_broken_lines(inp)
    check("第二题独立成行", "2. 第二题题干" in out, repr(out))
    # 题干末尾是逗号，但下一行是题号，不合并
    check("题号前有换行", out.index("1.") < out.index("2."), repr(out))


def test_math_address_merge() -> None:
    print("\n[5] 技术文本（地址/公式/数字）合并")
    inp = "255≥10+128=138? 255>138，\n所以需要二级间接？"
    out = merge_broken_lines(inp)
    check("数字逗号后合并",
          "255>138，所以需要二级间接" in out,
          repr(out))


def test_ocr_style_fragments() -> None:
    print("\n[6] OCR风格碎片合并")
    inp = "共138，\n不够。\n所以需要，\n三级索引。"
    out = merge_broken_lines(inp)
    check("逗号碎片合并", "共138，不够。" in out, repr(out))
    # "不够。" 以句号结尾，下一行应另起
    check("句号后不合并", "所以需要，三级索引。" in out, repr(out))


def test_mixed_chinese_english() -> None:
    print("\n[7] 中英混合技术文本")
    inp = "偏移量为0x1000，意味着目标地址=0x2000，\n1004H+0x1000*4不可行。"
    out = merge_broken_lines(inp)
    check("中英混合逗号后合并",
          "0x2000，1004H+0x1000" in out,
          repr(out))


def test_empty_line_paragraph_break() -> None:
    print("\n[8] 空行作为段落分隔符保留")
    inp = "第一段内容，\n继续第一段。\n\n第二段内容，\n继续第二段。"
    out = merge_broken_lines(inp)
    check("段落间保留空行", "\n\n" in out, repr(out))
    check("段落内合并", "继续第一段。" in out and "继续第二段。" in out, repr(out))


def test_normalize_full_pipeline() -> None:
    print("\n[9] normalize_pdf_text 完整流程")
    inp = "  盘块大小为1KB，   索引表如下：  \n直接块10个，\n一级间接128个，\n共138个。\n\n答案：B\n解析：计算过程，\n总共138≥256？"
    out = normalize_pdf_text(inp)
    # 行首尾空格已清除
    check("行首尾空格清除", "  盘块" not in out, repr(out[:60]))
    # 连续中文短句合并
    check("短句合并",
          "直接块10个，一级间接128个，共138个。" in out,
          repr(out))
    # 结构行保留
    check("答案行保留独立", "答案：B" in out, repr(out))
    check("解析行保留独立", "解析：" in out, repr(out))


def test_consecutive_blank_lines_compressed() -> None:
    print("\n[10] 连续空行压缩为最多一个")
    inp = "第一行\n\n\n\n\n第二行"
    out = normalize_pdf_text(inp)
    check("多空行压缩", "\n\n\n" not in out, repr(out))
    check("保留段落分隔", "\n\n" in out or "第一行" in out, repr(out))


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 60)
    print("pdf_text_normalizer 单元测试")
    print("=" * 60)

    test_basic_chinese_merge()
    test_sentence_end_no_merge()
    test_structure_lines_not_merged()
    test_question_number_not_merged()
    test_math_address_merge()
    test_ocr_style_fragments()
    test_mixed_chinese_english()
    test_empty_line_paragraph_break()
    test_normalize_full_pipeline()
    test_consecutive_blank_lines_compressed()

    print("\n" + "=" * 60)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("\n失败明细：")
        for name, msg in FAILED:
            print(f"  ✗ {name}\n    {msg}")
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())

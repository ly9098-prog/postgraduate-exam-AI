import { describe, expect, it } from "vitest";
import { buildQuestionCopyText } from "@/lib/question-copy";

describe("buildQuestionCopyText", () => {
  it("formats the stem and sorted options without copying answers or analysis", () => {
    const result = buildQuestionCopyText({
      content: { stem: "下列哪些操作会产生移动？\n    I. 表头插入\n    II. 表头删除" },
      options: { B: "I、III", A: "I、II" },
      answer: "A",
      analysis: "不应复制解析",
    });
    expect(result).toBe(
      "题目：\n下列哪些操作会产生移动？\n    I. 表头插入\n    II. 表头删除\n\n选项：\nA.I、II\nB.I、III",
    );
  });

  it("preserves inline/display LaTeX, matrix row separators and commands verbatim", () => {
    const stem = String.raw`求 $\frac{1}{2}$、\(x^2\) 与 \[\begin{matrix}a&b\\c&d\end{matrix}\]`;
    const option = String.raw`$$\sum_{i=1}^n i$$`;
    expect(buildQuestionCopyText({ content: { stem }, options: [option] }))
      .toBe(`题目：\n${stem}\n\n选项：\nA.${option}`);
  });

  it("decodes common and numeric HTML entities while preserving indentation", () => {
    expect(buildQuestionCopyText({
      content: { text: "问题\r\n&#x20;   I. x &lt; y &amp; z" },
      options: { A: "&#x49;、II", B: "&#73;I&nbsp;、IV", C: "&#x110000;" },
    })).toBe(
      "题目：\n问题\n    I. x < y & z\n\n选项：\nA.I、II\nB.II 、IV\nC.&#x110000;",
    );
  });

  it("uses visible text/newline segments instead of an outdated canonical stem", () => {
    expect(buildQuestionCopyText({
      content: {
        stem: "旧题干",
        segments: [
          null,
          { type: "text", text: "当前" },
          { type: "text", text: "题干" },
          { type: "newline" },
          { type: "text", text: String.raw`求 \(x\)` },
          { type: "text", option_key: "A", text: "不得重复复制选项" },
          { type: "image", url: "/private-image.png", alt: "OCR 元数据" },
          { type: "unknown", alt: "隐藏元数据" },
        ],
      },
      options: { A: "一个选项" },
    })).toBe("题目：\n当前题干\n求 \\(x\\)\n\n选项：\nA.一个选项");
  });

  it("keeps canonical programming source when OCR segments have a different reading order", () => {
    const stem = "int f(int x) {\n  return x + 1;\n}";
    expect(buildQuestionCopyText({
      content: { stem, segments: [{ type: "text", text: "return x + 1; int f(int x) {" }] },
    })).toBe(`题目：\n${stem}`);
  });

  it("copies code segments once and excludes accessibility metadata", () => {
    const code = String.raw`printf("\\n");`;
    expect(buildQuestionCopyText({
      content: {
        stem: code,
        segments: [{ type: "code", code, alt: "不要复制" }],
      },
    })).toBe(`题目：\n${code}`);
  });

  it("keeps code captions and structured tables in reading order", () => {
    expect(buildQuestionCopyText({
      content: {
        segments: [
          { type: "text", text: "阅读以下内容：" },
          { type: "code", caption: "程序", code: "return x;" },
          { type: "table", caption: "数据", rows: [[String.raw`$x^2$`, "2"]] },
        ],
      },
    })).toContain("阅读以下内容：\n程序\nreturn x;\n数据\n");
    expect(buildQuestionCopyText({
      content: { segments: [{ type: "table", rows: [[String.raw`$x^2$`, "2"]] }] },
    })).toContain("$x^2$");
  });

  it.each([
    { options: { A: "顶层选项" } },
    { content: { options: { A: "内容选项" } } },
    { content: { parsed_options: ["旧格式选项"] } },
    { content: { option_list: "A. 字符串选项" } },
  ])("uses existing option resolution for %j", (question) => {
    expect(buildQuestionCopyText(question)).toMatch(/选项：\nA\..+选项/);
  });

  it.each(["multi_blank_choice", "multi_blank_multiple_choice"])(
    "retains separate option groups for %s", (questionType) => {
      expect(buildQuestionCopyText({
        question_type: questionType,
        content: {
          stem: "填入①②",
          blank_option_groups: [
            { id: "①", options: { A: "甲", B: "乙" } },
            { id: "②", options: { A: "丙", B: "丁" } },
          ],
        },
        options: { A: "不使用普通选项" },
      })).toBe("题目：\n填入①②\n\n选项：\n①：\nA.甲\nB.乙\n\n②：\nA.丙\nB.丁");
    },
  );

  it("labels image-only options without copying URLs", () => {
    expect(buildQuestionCopyText({
      content: { question: "看图" },
      options: { A: { url: "/a.png" }, B: { text: "文字", url: "/b.png" } },
    })).toBe("题目：\n看图\n\n选项：\nA.（图片选项）\nB.文字");
  });

  it.each([{}, { content: "只有题干" }, { content: { title: "标题题干" } }])(
    "omits empty option sections and raw metadata for %j", (question) => {
      expect(buildQuestionCopyText(question)).not.toMatch(/选项：|undefined|\{|\}/);
    },
  );
});

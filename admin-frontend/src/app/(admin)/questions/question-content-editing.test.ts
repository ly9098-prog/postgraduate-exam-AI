import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import {
  canonicalStemAfterSegmentUpdate,
  codeSegmentText,
  comparableText,
  contentRecord,
  contentSegments,
  isCodeSegment,
  isPlainImageSegment,
  isStemTextSegment,
  nonStemContentSegments,
  normalizeStemForEditing,
  segmentType,
  textForStemEditor,
  textFromContent,
  updateStemInContent,
} from "./question-content-editing";

const path = fileURLToPath(new URL("./question-content-editing.ts", import.meta.url));
const source = readFileSync(path, "utf8");

function dependencyViolations(code: string): string[] {
  const file = ts.createSourceFile(path, code, ts.ScriptTarget.Latest, true);
  const violations: string[] = [];
  const walk = (node: ts.Node) => {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      if (node.moduleSpecifier.text !== "@/lib/math-text") violations.push(node.moduleSpecifier.text);
    }
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      violations.push("import()");
    }
    if (ts.isCallExpression(node) &&
      ["fetch", "require", "window.fetch", "globalThis.fetch"].includes(node.expression.getText(file))) {
      violations.push(node.expression.getText(file));
    }
    ts.forEachChild(node, walk);
  };
  walk(file);
  return violations;
}

describe("question content editing rules", () => {
  it("normalizes records and keeps valid segment object identity", () => {
    const image = { type: "IMAGE", url: "/a.png" };
    const invalid = null;
    const content = { segments: [image, invalid, ["bad"], { type: " text " }] };

    expect(contentRecord(content)).toBe(content);
    expect(contentSegments(content)).toEqual([image, { type: " text " }]);
    expect(contentSegments(content)[0]).toBe(image);
    expect(segmentType(image)).toBe("image");
    expect(isPlainImageSegment(image)).toBe(true);
    expect(isCodeSegment({ type: "Code" })).toBe(true);
    expect(isStemTextSegment({ type: "text" })).toBe(true);
    expect(isStemTextSegment({ type: "text", option_key: "A" })).toBe(false);
  });

  it("uses legacy field priority and derives only literal stem segments", () => {
    expect(textFromContent("literal")).toBe("literal");
    expect(textFromContent({ stem: "", text: "text", question: "question" })).toBe("text");
    expect(textFromContent({
      segments: [
        { type: "text", text: "A" },
        { type: "newline" },
        { type: "code", code: "return 1;" },
        { type: "text", text: "ignored option", option_key: "A" },
      ],
    })).toBe("A\n");
    expect(textFromContent({ segments: [{ type: "code", code: "return 1;" }] })).toBe("");
    expect(textFromContent({ title: "  whitespace counts  " })).toBe("  whitespace counts  ");
  });

  it("prefers structured visible stem text except for programming-code canonical text", () => {
    expect(textForStemEditor({
      stem: "legacy\nlayout",
      segments: [{ type: "text", text: "structured" }],
    })).toBe("structured");
    expect(textForStemEditor({
      stem: "int main() {\nreturn 0;\n}",
      segments: [
        { type: "text", text: "return 0;" },
        { type: "newline" },
        { type: "text", text: "int main() {" },
        { type: "newline" },
        { type: "text", text: "}" },
      ],
    })).toBe("int main() {\nreturn 0;\n}");
    expect(textForStemEditor({
      stem: "canonical",
      segments: [{ type: "image", url: "/x.png" }],
    })).toBe("canonical");
  });

  it("normalizes OCR math wraps without changing prose paragraphs or code", () => {
    expect(normalizeStemForEditing("x = \n  y")).toBe("x =y");
    expect(normalizeStemForEditing("第一行\n第二行")).toBe("第一行\n第二行");
    expect(normalizeStemForEditing("第一段\n\n第二段")).toBe("第一段\n\n第二段");
    expect(normalizeStemForEditing("int x = 1;\nreturn x;")).toBe("int x = 1;\nreturn x;");
    expect(comparableText(" \r\n code \r ")).toBe("code");
  });

  it("updates stem text segments while preserving non-stem references and options", () => {
    const image = { type: "image", url: "/x.png" };
    const option = { type: "text", text: "A", option_key: "A" };
    const code = { type: "code", code: "return 1;" };
    const original = { stem: "old", segments: [image, { type: "text", text: "old" }, option, code] };
    const next = updateStemInContent(original, "new\nline");

    expect(next).not.toBe(original);
    expect(original.segments).toEqual([image, { type: "text", text: "old" }, option, code]);
    expect(next.stem).toBe("new\nline");
    expect(next.text).toBe("new\nline");
    const segments = contentSegments(next);
    expect(segments).toHaveLength(6);
    expect(segments[0]).toBe(image);
    expect(segments.slice(1, 4)).toEqual([
      { type: "text", text: "new" }, { type: "newline" }, { type: "text", text: "line" },
    ]);
    expect(segments[4]).toBe(option);
    expect(segments[5]).toBe(code);
    expect(nonStemContentSegments(next)).toEqual([image, option, code]);
    expect(codeSegmentText(code)).toBe("return 1;");
  });

  it("updates code-only legacy fallback by object identity and same-index replacement", () => {
    const code = { type: "code", code: "old", caption: "示例" };
    const image = { type: "image", url: "/x.png" };
    const content = { stem: "示例\nold", segments: [image, code] };
    const updated = { type: "code", code: "new", caption: "示例" };

    expect(canonicalStemAfterSegmentUpdate(content, [image, updated])).toBe("示例\nnew");
    expect(canonicalStemAfterSegmentUpdate(content, [code, image])).toBe("示例\nold");
    expect(canonicalStemAfterSegmentUpdate(content, [updated, image])).toBe("");
    expect(canonicalStemAfterSegmentUpdate(content, [updated, image, code])).toBe("示例\nold");
    expect(canonicalStemAfterSegmentUpdate(content, [image])).toBe("");
    expect(canonicalStemAfterSegmentUpdate({ stem: "prose", segments: [code] }, [updated]))
      .toBe("prose");
  });

  it("keeps empty content and non-stem segment filtering explicit", () => {
    expect(contentRecord(null)).toEqual({});
    expect(contentSegments({ segments: "invalid" })).toEqual([]);
    expect(updateStemInContent({ stem: "old" }, "")).toEqual({ stem: "", text: "" });
    expect(nonStemContentSegments({ segments: [
      { type: "newline" },
      { type: "text", text: "stem" },
      { type: "table", rows: [] },
    ] })).toEqual([{ type: "table", rows: [] }]);
  });

  it.each([null, undefined, [], "legacy", 42])("rejects non-record content %j", (value) => {
    expect(contentRecord(value)).toEqual({});
    expect(contentSegments(value)).toEqual([]);
  });

  it.each(["math_image", "table_image", "code_image"])("keeps %s outside the image editor", (type) => {
    expect(isPlainImageSegment({ type })).toBe(false);
  });

  it("retains an explicit empty structured stem and option segments", () => {
    expect(textForStemEditor({ stem: "old", segments: [{ type: "text", text: "" }] })).toBe("");
    const option = { type: "text", text: "option", option_key: "A" };
    expect(updateStemInContent({ segments: [option] }, "\n")).toEqual({
      stem: "\n", text: "\n", segments: [{ type: "newline" }, option],
    });
    expect(updateStemInContent({ segments: [{ type: "text", text: "old" }, option] }, ""))
      .toEqual({ stem: "", text: "", segments: [option] });
  });

  it("uses structured prose when a code canonical stem also has non-text content", () => {
    expect(textForStemEditor({
      stem: "return 1;",
      segments: [{ type: "text", text: "visible" }, { type: "code", code: "return 1;" }],
    })).toBe("visible");
    expect(codeSegmentText({ code: "", text: "legacy" })).toBe("");
    expect(codeSegmentText({ text: "legacy" })).toBe("legacy");
  });
});

describe("question content editing boundary", () => {
  it("depends only on the shared programming-code detector", () => {
    expect(dependencyViolations(source)).toEqual([]);
  });

  it("detects page dependencies and network or dynamic import bypasses", () => {
    expect(dependencyViolations('import Page from "./page"; fetch("/questions"); import("./page");'))
      .toEqual(["./page", "fetch", "import()"]);
  });

  it("keeps the pure module and its top-level functions within budget", () => {
    expect(source.trimEnd().split("\n").length).toBeLessThanOrEqual(300);
    const file = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true);
    for (const node of file.statements) {
      if (!ts.isFunctionDeclaration(node)) continue;
      const start = file.getLineAndCharacterOfPosition(node.getStart(file)).line;
      const end = file.getLineAndCharacterOfPosition(node.end).line;
      expect(end - start + 1, node.name?.text).toBeLessThanOrEqual(50);
    }
  });
});

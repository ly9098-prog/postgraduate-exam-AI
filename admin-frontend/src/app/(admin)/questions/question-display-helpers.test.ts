import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import {
  comparableAssetUrl,
  contentRenderedImageKeys,
  fallbackQuestionImageUrls,
  imageUrlFromUnknown,
  isMultiBlankChoice,
  isMultiBlankMultipleChoice,
  isMultiChoice,
  normalizedChoiceAnswerKeys,
} from "./question-display-helpers";

const path = fileURLToPath(new URL("./question-display-helpers.ts", import.meta.url));
const source = readFileSync(path, "utf8");

function dependencyViolations(code: string): string[] {
  const file = ts.createSourceFile(path, code, ts.ScriptTarget.Latest, true);
  const violations: string[] = [];
  const walk = (node: ts.Node) => {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      const dep = node.moduleSpecifier.text;
      // Only pure, stateless lib deps allowed; no React/Next/TanStack/DOM.
      const allowed = ["@/lib/asset-url", "@/lib/question-types", "./question-content-editing"];
      if (!allowed.includes(dep)) violations.push(dep);
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

describe("question-display-helpers dependencies", () => {
  it("imports only pure lib modules and performs no I/O", () => {
    expect(dependencyViolations(source)).toEqual([]);
  });
});

describe("imageUrlFromUnknown", () => {
  it("returns trimmed string values directly", () => {
    expect(imageUrlFromUnknown("  /a.png  ")).toBe("/a.png");
    expect(imageUrlFromUnknown("https://x/y.png")).toBe("https://x/y.png");
  });

  it("extracts url from record using legacy key priority", () => {
    expect(imageUrlFromUnknown({ url: "/u.png" })).toBe("/u.png");
    expect(imageUrlFromUnknown({ src: "/s.png" })).toBe("/s.png");
    expect(imageUrlFromUnknown({ image_url: "/iu.png" })).toBe("/iu.png");
    expect(imageUrlFromUnknown({ imageUrl: "/iu2.png" })).toBe("/iu2.png");
    expect(imageUrlFromUnknown({ url: "", src: "/s.png" })).toBe("/s.png");
  });

  it("returns empty for invalid inputs", () => {
    expect(imageUrlFromUnknown(null)).toBe("");
    expect(imageUrlFromUnknown(undefined)).toBe("");
    expect(imageUrlFromUnknown(42)).toBe("");
    expect(imageUrlFromUnknown([])).toBe("");
    expect(imageUrlFromUnknown({})).toBe("");
    expect(imageUrlFromUnknown({ url: 123 })).toBe("");
    expect(imageUrlFromUnknown({ url: "  " })).toBe("");
  });
});

describe("comparableAssetUrl", () => {
  it("returns empty for empty input", () => {
    expect(comparableAssetUrl(null)).toBe("");
    expect(comparableAssetUrl("")).toBe("");
  });

  it("strips trailing slashes for stable comparison", () => {
    expect(comparableAssetUrl("/a/b/")).toBe("/a/b");
    expect(comparableAssetUrl("/a/b///")).toBe("/a/b");
  });

  it("resolves protocol-relative to https", () => {
    expect(comparableAssetUrl("//cdn/x.png")).toBe("https://cdn/x.png");
  });

  it("handles record input via imageUrlFromUnknown", () => {
    expect(comparableAssetUrl({ url: "/img.png" })).toBe("/img.png");
  });
});

describe("contentRenderedImageKeys", () => {
  it("collects keys from all image-like segment types", () => {
    const content = { segments: [
      { type: "image", url: "/a.png" },
      { type: "math_image", url: "/b.png" },
      { type: "table_image", url: "/c.png" },
      { type: "code_image", url: "/d.png" },
      { type: "text", text: "ignored" },
      { type: "image", url: "/a.png" }, // duplicate
    ] };
    const keys = contentRenderedImageKeys(content);
    expect(keys.size).toBe(4);
    expect(keys.has("/a.png")).toBe(true);
    expect(keys.has("/b.png")).toBe(true);
    expect(keys.has("/c.png")).toBe(true);
    expect(keys.has("/d.png")).toBe(true);
  });

  it("returns empty set for content without segments", () => {
    expect(contentRenderedImageKeys(null).size).toBe(0);
    expect(contentRenderedImageKeys({}).size).toBe(0);
    expect(contentRenderedImageKeys("literal").size).toBe(0);
  });
});

describe("fallbackQuestionImageUrls", () => {
  it("returns empty when field is not an array", () => {
    expect(fallbackQuestionImageUrls({}, null)).toEqual([]);
    expect(fallbackQuestionImageUrls({}, "string")).toEqual([]);
    expect(fallbackQuestionImageUrls({}, undefined)).toEqual([]);
  });

  it("returns only non-duplicate images not in rendered content", () => {
    const content = { segments: [{ type: "image", url: "/rendered.png" }] };
    const field = ["/rendered.png", "/extra1.png", "/extra2.png", "/extra1.png"];
    expect(fallbackQuestionImageUrls(content, field)).toEqual(["/extra1.png", "/extra2.png"]);
  });

  it("deduplicates by comparable key preserving first occurrence order", () => {
    const field = [{ url: "/x.png" }, { src: "/x.png" }, "/y.png"];
    expect(fallbackQuestionImageUrls({}, field)).toEqual(["/x.png", "/y.png"]);
  });

  it("skips empty and invalid entries", () => {
    expect(fallbackQuestionImageUrls({}, ["", null, 42, {}])).toEqual([]);
  });
});

describe("question type predicates", () => {
  it("isMultiChoice matches only multiple_choice", () => {
    expect(isMultiChoice("multiple_choice")).toBe(true);
    expect(isMultiChoice("MULTIPLE-CHOICE")).toBe(true); // canonicalizes via normalize
    expect(isMultiChoice("single_choice")).toBe(false);
    expect(isMultiChoice("")).toBe(false);
  });

  it("isMultiBlankChoice matches both multi_blank variants", () => {
    expect(isMultiBlankChoice("multi_blank_choice")).toBe(true);
    expect(isMultiBlankChoice("multi_blank_multiple_choice")).toBe(true);
    expect(isMultiBlankChoice("multiple_choice")).toBe(false);
    expect(isMultiBlankChoice("single_choice")).toBe(false);
  });

  it("isMultiBlankMultipleChoice matches only the multi-select variant", () => {
    expect(isMultiBlankMultipleChoice("multi_blank_multiple_choice")).toBe(true);
    expect(isMultiBlankMultipleChoice("multi_blank_choice")).toBe(false);
  });
});

describe("normalizedChoiceAnswerKeys", () => {
  it("splits, trims, uppercases, deduplicates", () => {
    expect(normalizedChoiceAnswerKeys("a, b，c a")).toEqual(["A", "B", "C"]);
    expect(normalizedChoiceAnswerKeys("A B C")).toEqual(["A", "B", "C"]);
    expect(normalizedChoiceAnswerKeys("a，b，a")).toEqual(["A", "B"]);
  });

  it("handles null/undefined/empty", () => {
    expect(normalizedChoiceAnswerKeys(null)).toEqual([]);
    expect(normalizedChoiceAnswerKeys(undefined)).toEqual([]);
    expect(normalizedChoiceAnswerKeys("")).toEqual([]);
    expect(normalizedChoiceAnswerKeys("   ")).toEqual([]);
  });

  it("filters blank-only fragments", () => {
    expect(normalizedChoiceAnswerKeys("a,, ,b")).toEqual(["A", "B"]);
  });
});

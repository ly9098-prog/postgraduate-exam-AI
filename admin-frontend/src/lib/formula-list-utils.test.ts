import { describe, it, expect } from "vitest";
import { positiveInt, buildFormulaListHref, findCategoryNode } from "./formula-list-utils";

describe("positiveInt", () => {
  it("parses positive integer", () => {
    expect(positiveInt("5")).toBe(5);
  });
  it("returns fallback for zero", () => {
    expect(positiveInt("0", 10)).toBe(10);
  });
  it("returns fallback for negative", () => {
    expect(positiveInt("-3", 10)).toBe(10);
  });
  it("returns fallback for non-integer", () => {
    expect(positiveInt("3.5", 10)).toBe(10);
  });
  it("returns fallback for null", () => {
    expect(positiveInt(null, 10)).toBe(10);
  });
  it("returns null when no fallback", () => {
    expect(positiveInt("abc")).toBeNull();
  });
});

describe("buildFormulaListHref", () => {
  it("returns base path when no filters", () => {
    expect(buildFormulaListHref({}, 1, null)).toBe("/formulas");
  });
  it("includes filters", () => {
    const href = buildFormulaListHref({ status: "draft", keyword: "test" }, 1, null);
    expect(href).toContain("status=draft");
    expect(href).toContain("keyword=test");
  });
  it("includes page when > 1", () => {
    const href = buildFormulaListHref({}, 2, null);
    expect(href).toContain("page=2");
  });
  it("includes selected_id when provided", () => {
    const href = buildFormulaListHref({}, 1, 42);
    expect(href).toContain("selected_id=42");
  });
  it("omits page when 1", () => {
    const href = buildFormulaListHref({}, 1, null);
    expect(href).not.toContain("page=");
  });
});

describe("findCategoryNode", () => {
  const tree = [
    { id: 1, children: [
      { id: 3, children: [] },
      { id: 4, children: [] },
    ]},
    { id: 2, children: [] },
  ];
  it("finds root node", () => {
    expect(findCategoryNode(tree, 1)?.id).toBe(1);
  });
  it("finds nested child", () => {
    expect(findCategoryNode(tree, 4)?.id).toBe(4);
  });
  it("returns null for missing id", () => {
    expect(findCategoryNode(tree, 99)).toBeNull();
  });
  it("returns null for null id", () => {
    expect(findCategoryNode(tree, null)).toBeNull();
  });
  it("handles empty tree", () => {
    expect(findCategoryNode([], 1)).toBeNull();
  });
});

import { describe, it, expect } from "vitest";
import {
  positiveInt,
  buildFormulaListHref,
  findCategoryNode,
  pruneCategoryTree,
  sumCategoryFormulaCount,
  hasActiveFormulaFilters,
  computeSafeSelectedIds,
  computeBatchSelectionState,
  isBatchableStatus,
  computePageWindow,
} from "./formula-list-utils";

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

describe("pruneCategoryTree", () => {
  const tree = [
    { id: 1, name: "网络", code: "NET", children: [
      { id: 3, name: "传输层", code: "TCP", children: [] },
      { id: 4, name: "应用层", code: "APP", children: [] },
    ]},
    { id: 2, name: "数据结构", code: "DS", children: [] },
  ];
  it("returns roots unchanged when query is empty", () => {
    expect(pruneCategoryTree(tree, "")).toBe(tree);
  });
  it("returns roots unchanged when query is whitespace only", () => {
    expect(pruneCategoryTree(tree, "   ")).toBe(tree);
  });
  it("keeps a node matching by name", () => {
    const out = pruneCategoryTree(tree, "数据");
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe(2);
  });
  it("keeps a node matching by code", () => {
    const out = pruneCategoryTree(tree, "NET");
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe(1);
  });
  it("keeps a parent when a child matches", () => {
    const out = pruneCategoryTree(tree, "传输");
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe(1);
    expect(out[0].children).toHaveLength(1);
    expect(out[0].children[0].id).toBe(3);
  });
  it("matches case-insensitively", () => {
    expect(pruneCategoryTree(tree, "app")).toHaveLength(1);
  });
  it("returns empty when no match", () => {
    expect(pruneCategoryTree(tree, "不存在")).toEqual([]);
  });
  it("does not mutate input nodes", () => {
    const snapshot = JSON.stringify(tree);
    pruneCategoryTree(tree, "传输");
    expect(JSON.stringify(tree)).toBe(snapshot);
  });
});

describe("sumCategoryFormulaCount", () => {
  it("sums subtree_formula_count when present", () => {
    expect(sumCategoryFormulaCount([
      { subtree_formula_count: 10, formula_count: 3 },
      { subtree_formula_count: 5, formula_count: 1 },
    ])).toBe(15);
  });
  it("falls back to formula_count", () => {
    expect(sumCategoryFormulaCount([
      { formula_count: 7 },
      { formula_count: 2 },
    ])).toBe(9);
  });
  it("treats missing counts as zero", () => {
    expect(sumCategoryFormulaCount([{}, { formula_count: 4 }])).toBe(4);
  });
  it("returns zero for empty list", () => {
    expect(sumCategoryFormulaCount([])).toBe(0);
  });
});

describe("hasActiveFormulaFilters", () => {
  it("false when all empty", () => {
    expect(hasActiveFormulaFilters({})).toBe(false);
  });
  it("true when status set", () => {
    expect(hasActiveFormulaFilters({ status: "draft" })).toBe(true);
  });
  it("true when category_id set", () => {
    expect(hasActiveFormulaFilters({ category_id: "5" })).toBe(true);
  });
  it("true when q set", () => {
    expect(hasActiveFormulaFilters({ q: "tcp" })).toBe(true);
  });
  it("true when graph_status set", () => {
    expect(hasActiveFormulaFilters({ graph_status: "ready" })).toBe(true);
  });
  it("false for extra keys only without passing them", () => {
    expect(hasActiveFormulaFilters({ custom: "x" } as Record<string, string>)).toBe(false);
  });
  it("true when an extra key is provided and set", () => {
    expect(hasActiveFormulaFilters({ custom: "x" } as Record<string, string>, "custom")).toBe(true);
  });
});

describe("computeSafeSelectedIds", () => {
  const items = [{ id: 1 }, { id: 2 }, { id: 3 }];
  it("returns the input set when items is empty", () => {
    const sel = new Set([1, 2]);
    expect(computeSafeSelectedIds([], sel)).toBe(sel);
  });
  it("keeps ids present in items", () => {
    const sel = new Set([1, 2]);
    const out = computeSafeSelectedIds(items, sel);
    expect([...out]).toEqual([1, 2]);
  });
  it("drops stale ids not in items", () => {
    const sel = new Set([1, 99]);
    const out = computeSafeSelectedIds(items, sel);
    expect([...out]).toEqual([1]);
  });
  it("returns empty when nothing matches", () => {
    const out = computeSafeSelectedIds(items, new Set([99]));
    expect(out.size).toBe(0);
  });
});

describe("computeBatchSelectionState", () => {
  const items = [{ id: 1 }, { id: 2 }, { id: 3 }];
  it("allSelected when all items selected", () => {
    const s = computeBatchSelectionState(items, new Set([1, 2, 3]));
    expect(s.allSelected).toBe(true);
    expect(s.indeterminate).toBe(false);
    expect(s.selectedCount).toBe(3);
  });
  it("indeterminate when some selected", () => {
    const s = computeBatchSelectionState(items, new Set([1, 2]));
    expect(s.allSelected).toBe(false);
    expect(s.indeterminate).toBe(true);
    expect(s.selectedCount).toBe(2);
  });
  it("not all selected when empty set", () => {
    const s = computeBatchSelectionState(items, new Set());
    expect(s.allSelected).toBe(false);
    expect(s.indeterminate).toBe(false);
    expect(s.selectedCount).toBe(0);
  });
  it("all false when items empty", () => {
    const s = computeBatchSelectionState([], new Set([1, 2]));
    expect(s.allSelected).toBe(false);
    expect(s.indeterminate).toBe(true);
    expect(s.selectedCount).toBe(2);
  });
  it("ignores stale selected ids", () => {
    const s = computeBatchSelectionState(items, new Set([1, 2, 99]));
    expect(s.allSelected).toBe(false);
    expect(s.indeterminate).toBe(true);
    expect(s.selectedCount).toBe(2);
  });
});

describe("isBatchableStatus", () => {
  it("true for pending_review", () => {
    expect(isBatchableStatus("pending_review")).toBe(true);
  });
  it("true for draft", () => {
    expect(isBatchableStatus("draft")).toBe(true);
  });
  it("false for published", () => {
    expect(isBatchableStatus("published")).toBe(false);
  });
  it("false for undefined", () => {
    expect(isBatchableStatus(undefined)).toBe(false);
  });
  it("false for empty string", () => {
    expect(isBatchableStatus("")).toBe(false);
  });
});

describe("computePageWindow", () => {
  it("returns empty when totalPages <= 1", () => {
    expect(computePageWindow(1, 1)).toEqual([]);
    expect(computePageWindow(1, 0)).toEqual([]);
  });
  it("returns all pages when total <= window", () => {
    expect(computePageWindow(1, 3)).toEqual([1, 2, 3]);
    expect(computePageWindow(2, 3)).toEqual([1, 2, 3]);
    expect(computePageWindow(3, 3)).toEqual([1, 2, 3]);
  });
  it("clamps window to 5 pages for large totals", () => {
    expect(computePageWindow(5, 20)).toHaveLength(5);
    expect(computePageWindow(5, 20)).toEqual([3, 4, 5, 6, 7]);
  });
  it("starts at 1 for early pages", () => {
    expect(computePageWindow(1, 20)).toEqual([1, 2, 3, 4, 5]);
    expect(computePageWindow(2, 20)).toEqual([1, 2, 3, 4, 5]);
    expect(computePageWindow(3, 20)).toEqual([1, 2, 3, 4, 5]);
  });
  it("slides to end for late pages", () => {
    expect(computePageWindow(19, 20)).toEqual([16, 17, 18, 19, 20]);
    expect(computePageWindow(20, 20)).toEqual([16, 17, 18, 19, 20]);
  });
  it("respects custom windowSize", () => {
    expect(computePageWindow(5, 20, 3)).toEqual([4, 5, 6]);
    expect(computePageWindow(1, 20, 3)).toEqual([1, 2, 3]);
    expect(computePageWindow(20, 20, 3)).toEqual([18, 19, 20]);
  });
  it("windowSize 1 returns single page", () => {
    expect(computePageWindow(5, 20, 1)).toEqual([5]);
  });
  it("does not exceed totalPages near boundary", () => {
    expect(computePageWindow(4, 4)).toEqual([1, 2, 3, 4]);
    expect(computePageWindow(4, 6, 5)).toEqual([2, 3, 4, 5, 6]);
  });
});

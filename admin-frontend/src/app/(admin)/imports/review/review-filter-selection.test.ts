import { describe, expect, it } from "vitest";
import {
  reduceReviewFilterSelection,
  shouldClearReviewSelection,
  toggleAllSelection,
  toggleSingleSelection,
  type ReviewFilterUpdateSource,
} from "./review-filter-selection";

describe("review filter selection side effects", () => {
  it.each([
    ["facet", true],
    ["keyword", false],
    ["reset", false],
  ] as const)("preserves the existing selection policy for %s", (source, expected) => {
    expect(shouldClearReviewSelection(source)).toBe(expected);
  });

  it("keeps the input domain explicit", () => {
    const sources: ReviewFilterUpdateSource[] = ["facet", "keyword", "reset"];
    expect(sources.map(shouldClearReviewSelection)).toEqual([true, false, false]);
  });

  it("only replaces the selection for facet filters", () => {
    const filters = { status: "pending", keyword: "" };
    const selectedIds = new Set([4, 8]);
    const state = { filters, selectedIds };

    expect(reduceReviewFilterSelection(state, "facet")).toEqual({
      filters,
      selectedIds: new Set(),
    });
    expect(reduceReviewFilterSelection(state, "keyword")).toBe(state);
    expect(reduceReviewFilterSelection(state, "reset")).toBe(state);
    expect(selectedIds).toEqual(new Set([4, 8]));
  });
});

describe("toggleAllSelection", () => {
  it("selects all when not all checked", () => {
    expect(toggleAllSelection([1, 2, 3], false)).toEqual(new Set([1, 2, 3]));
  });

  it("deselects all when all checked", () => {
    expect(toggleAllSelection([1, 2, 3], true)).toEqual(new Set());
  });

  it("returns empty set for empty items", () => {
    expect(toggleAllSelection([], false)).toEqual(new Set());
    expect(toggleAllSelection([], true)).toEqual(new Set());
  });
});

describe("toggleSingleSelection", () => {
  it("adds an unselected ID", () => {
    const result = toggleSingleSelection(new Set([1, 2]), 3);
    expect(result).toEqual(new Set([1, 2, 3]));
  });

  it("removes a selected ID", () => {
    const result = toggleSingleSelection(new Set([1, 2, 3]), 2);
    expect(result).toEqual(new Set([1, 3]));
  });

  it("does not mutate the original set", () => {
    const original = new Set([1, 2]);
    const result = toggleSingleSelection(original, 3);
    expect(original).toEqual(new Set([1, 2]));
    expect(result).not.toBe(original);
  });
});

import { describe, expect, it } from "vitest";
import {
  reduceReviewFilterSelection,
  shouldClearReviewSelection,
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

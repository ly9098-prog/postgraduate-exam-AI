import { describe, expect, it } from "vitest";
import {
  isReviewFacetFilter,
  reduceReviewFilters,
} from "./review-filter-interaction";
import { createDefaultReviewFilters } from "./review-query-state";

describe("review filter interaction", () => {
  it("replaces only the requested filter without mutating the input", () => {
    const current = createDefaultReviewFilters();
    const next = reduceReviewFilters(current, "risk_level", "high");

    expect(next).toEqual({ ...current, risk_level: "high" });
    expect(current.risk_level).toBe("");
  });

  it("keeps source_type as a non-selection-clearing request filter", () => {
    expect(isReviewFacetFilter("source_type")).toBe(false);
    expect(isReviewFacetFilter("batch_id")).toBe(true);
    expect(isReviewFacetFilter("status")).toBe(true);
    expect(isReviewFacetFilter("subject_id")).toBe(true);
    expect(isReviewFacetFilter("risk_level")).toBe(true);
    expect(isReviewFacetFilter("answer_status")).toBe(true);
  });
});

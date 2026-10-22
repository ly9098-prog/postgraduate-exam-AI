import { describe, expect, it } from "vitest";
import {
  buildReviewQueueParams,
  createDefaultReviewFilters,
  shouldShowReviewFilterReset,
  type ReviewFilters,
} from "./review-query-state";

const filters: ReviewFilters = {
  batch_id: "",
  status: "pending",
  subject_id: "",
  source_type: "",
  keyword: "",
  risk_level: "",
  answer_status: "",
};

describe("import review queue query state", () => {
  it("creates the existing default filters with pending status and no active facets", () => {
    const defaults = createDefaultReviewFilters();
    expect(defaults).toEqual({
      batch_id: "",
      status: "pending",
      subject_id: "",
      source_type: "",
      keyword: "",
      risk_level: "",
      answer_status: "",
    });
  });

  it("shows reset for the same active facets while ignoring status and inherited batch id", () => {
    expect(shouldShowReviewFilterReset(filters)).toBe(false);
    expect(shouldShowReviewFilterReset({ ...filters, status: "approved" })).toBe(false);
    expect(shouldShowReviewFilterReset({ ...filters, source_type: "pdf" })).toBe(false);
    for (const key of ["batch_id", "subject_id", "risk_level", "answer_status", "keyword"] as const) {
      expect(shouldShowReviewFilterReset({ ...filters, [key]: "active" })).toBe(true);
    }
  });

  it("uses the URL batch id when the filter has no explicit batch", () => {
    const { batch_id, status, subject_id, source_type, risk_level, answer_status } = filters;
    expect(buildReviewQueueParams({
      batch_id,
      status,
      subject_id,
      source_type,
      risk_level,
      answer_status,
    }, 2, "url-batch", "stem")).toEqual({
      page: 2,
      page_size: 50,
      batch_id: "url-batch",
      status: "pending",
      subject_id: undefined,
      source_type: "",
      keyword: "stem",
      risk_level: undefined,
      answer_status: undefined,
    });
  });

  it("prefers explicit filters and retains existing numeric conversion", () => {
    expect(buildReviewQueueParams({
      ...filters,
      batch_id: "selected-batch",
      subject_id: "not-a-number",
      risk_level: "high",
      answer_status: "missing",
    }, 1, "url-batch", "")).toEqual({
      page: 1,
      page_size: 50,
      batch_id: "selected-batch",
      status: "pending",
      subject_id: Number.NaN,
      source_type: "",
      keyword: "",
      risk_level: "high",
      answer_status: "missing",
    });
  });
});

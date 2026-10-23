import { describe, expect, it } from "vitest";
import { buildQuestionPaginationViewport } from "./question-pagination-viewport";

describe("question pagination viewport", () => {
  it("returns no pages when the total is not positive", () => {
    expect(buildQuestionPaginationViewport({ page: 1, totalPages: 0 })).toEqual([]);
  });

  it("returns every page when there are at most five pages", () => {
    expect(buildQuestionPaginationViewport({ page: 4, totalPages: 5 })).toEqual([1, 2, 3, 4, 5]);
  });

  it("keeps a sliding five-page window near the middle", () => {
    expect(buildQuestionPaginationViewport({ page: 6, totalPages: 10 })).toEqual([4, 5, 6, 7, 8]);
  });

  it("pins the window to the last five pages", () => {
    expect(buildQuestionPaginationViewport({ page: 10, totalPages: 10 })).toEqual([6, 7, 8, 9, 10]);
  });
});

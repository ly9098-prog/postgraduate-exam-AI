import { describe, expect, it } from "vitest";
import { normalizeQuestionPageSize, positiveInt } from "../question-list-state";
import { buildQueryParams } from "../question-query-params";

describe("question pagination state", () => {
  it("reads valid positive page values and falls back to page 1", () => {
    expect(positiveInt("3", 1)).toBe(3);
    expect(positiveInt("0", 1)).toBe(1);
    expect(positiveInt("invalid", 1)).toBe(1);
  });

  it("normalizes page size to the supported values", () => {
    expect(normalizeQuestionPageSize("50")).toBe(50);
    expect(normalizeQuestionPageSize("100")).toBe(100);
    expect(normalizeQuestionPageSize("30")).toBe(20);
    expect(normalizeQuestionPageSize(null)).toBe(20);
  });

  it("keeps filters, page, and page size in the list query contract", () => {
    expect(buildQueryParams(
      {
        subject_id: "2",
        is_active: "true",
        question_type: "choice",
        keyword: "tree",
        year: "",
        difficulty: "",
        import_batch_id: "",
        knowledge_point_id: "",
      },
      3,
      50,
    )).toEqual({
      subject_id: 2,
      is_active: "true",
      question_type: "choice",
      keyword: "tree",
      year: "",
      difficulty: undefined,
      import_batch_id: undefined,
      knowledge_point_id: undefined,
      page: 3,
      page_size: 50,
    });
  });
});

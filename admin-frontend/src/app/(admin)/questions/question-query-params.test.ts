import { describe, expect, it } from "vitest";
import type { QuestionListFilters } from "./question-list-state";
import { buildQueryParams } from "./question-query-params";

const filters: QuestionListFilters = {
  subject_id: "5",
  is_active: "true",
  question_type: "multiple_choice",
  keyword: "test",
  year: "2024",
  difficulty: "3",
  import_batch_id: "batch-1",
  knowledge_point_id: "42",
};

describe("buildQueryParams", () => {
  it("maps all filter fields to query params", () => {
    const params = buildQueryParams(filters, 1, 20);
    expect(params).toEqual({
      page: 1,
      page_size: 20,
      subject_id: 5,
      is_active: "true",
      question_type: "multiple_choice",
      keyword: "test",
      year: "2024",
      difficulty: 3,
      import_batch_id: "batch-1",
      knowledge_point_id: 42,
    });
  });

  it("returns undefined for empty string fields", () => {
    const emptyFilters: QuestionListFilters = {
      subject_id: "",
      is_active: "true",
      question_type: "",
      keyword: "",
      year: "",
      difficulty: "",
      import_batch_id: "",
      knowledge_point_id: "",
    };
    const params = buildQueryParams(emptyFilters, 2, 50);
    expect(params.subject_id).toBeUndefined();
    expect(params.difficulty).toBeUndefined();
    expect(params.import_batch_id).toBeUndefined();
    expect(params.knowledge_point_id).toBeUndefined();
    expect(params.page).toBe(2);
    expect(params.page_size).toBe(50);
  });
});

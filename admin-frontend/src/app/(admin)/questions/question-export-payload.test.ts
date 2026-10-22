import { describe, expect, it } from "vitest";
import type { QuestionListFilters } from "./question-list-state";
import { buildExportPayload } from "./question-export-payload";

const baseFilters: QuestionListFilters = {
  subject_id: "5",
  is_active: "true",
  question_type: "multiple_choice",
  keyword: "函数",
  year: "2024",
  difficulty: "3",
  import_batch_id: "batch-abc",
  knowledge_point_id: "42",
};

describe("buildExportPayload", () => {
  it("maps all filter fields to export payload", () => {
    const payload = buildExportPayload("csv", baseFilters, new Set());
    expect(payload.format).toBe("csv");
    expect(payload.ids).toBeUndefined();
    expect(payload.subject_id).toBe(5);
    expect(payload.is_active).toBe(true);
    expect(payload.question_type).toBe("multiple_choice");
    expect(payload.keyword).toBe("函数");
    expect(payload.year).toBe(2024);
    expect(payload.difficulty).toBe(3);
    expect(payload.import_batch_id).toBe("batch-abc");
    expect(payload.knowledge_point_id).toBe(42);
  });

  it("includes selected IDs when set is non-empty", () => {
    const payload = buildExportPayload("docx", baseFilters, new Set([1, 3, 5]));
    expect(payload.format).toBe("docx");
    expect(payload.ids).toEqual([1, 3, 5]);
  });

  it("returns undefined for empty string fields", () => {
    const emptyFilters: QuestionListFilters = {
      subject_id: "",
      is_active: "",
      question_type: "",
      keyword: "",
      year: "",
      difficulty: "",
      import_batch_id: "",
      knowledge_point_id: "",
    };
    const payload = buildExportPayload("csv", emptyFilters, new Set());
    expect(payload.ids).toBeUndefined();
    expect(payload.subject_id).toBeUndefined();
    expect(payload.is_active).toBeUndefined();
    expect(payload.question_type).toBeUndefined();
    expect(payload.keyword).toBeUndefined();
    expect(payload.year).toBeUndefined();
    expect(payload.difficulty).toBeUndefined();
    expect(payload.import_batch_id).toBeUndefined();
    expect(payload.knowledge_point_id).toBeUndefined();
  });

  it("converts is_active=false to boolean false", () => {
    const payload = buildExportPayload("csv", { ...baseFilters, is_active: "false" }, new Set());
    expect(payload.is_active).toBe(false);
  });
});

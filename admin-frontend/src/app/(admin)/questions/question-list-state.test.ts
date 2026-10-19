import { describe, expect, it } from "vitest";
import {
  buildQuestionListHref,
  DEFAULT_QUESTION_FILTERS,
  normalizeQuestionPageSize,
  positiveInt,
  readQuestionListFilters,
} from "./question-list-state";

describe("question list URL state", () => {
  it("uses active questions and omits default pagination", () => {
    const filters = readQuestionListFilters(new URLSearchParams());
    expect(filters).toEqual(DEFAULT_QUESTION_FILTERS);
    expect(buildQuestionListHref(filters, 1, 20, null)).toBe("/questions");
    expect(filters).not.toBe(DEFAULT_QUESTION_FILTERS);
  });

  it.each(["", "false", "true"])("preserves explicit active status %j", (status) => {
    const filters = readQuestionListFilters(new URLSearchParams({ is_active: status }));
    expect(filters.is_active).toBe(status);
    const href = buildQuestionListHref(filters, 1, 20, null);
    expect(href).toBe(status === "true" ? "/questions" : `/questions?is_active=${status}`);
  });

  it("round trips all filters and encodes special characters", () => {
    const filters = {
      subject_id: "3",
      is_active: "",
      question_type: "single_choice",
      keyword: "积分 & x+y",
      year: "2026",
      difficulty: "2",
      import_batch_id: "batch/a",
      knowledge_point_id: "19",
    };
    const href = buildQuestionListHref(filters, 3, 50, 123);
    const params = new URL(href, "https://admin.test").searchParams;
    expect(readQuestionListFilters(params)).toEqual(filters);
    expect(params.get("page")).toBe("3");
    expect(params.get("page_size")).toBe("50");
    expect(params.get("selected_id")).toBe("123");
    expect(href).toContain("keyword=%E7%A7%AF%E5%88%86+%26+x%2By");
    expect([...params.keys()]).toEqual([
      ...Object.keys(filters), "page", "page_size", "selected_id",
    ]);
  });

  it("ignores unrelated query parameters", () => {
    expect(readQuestionListFilters(new URLSearchParams("unknown=value&page=9")))
      .toEqual(DEFAULT_QUESTION_FILTERS);
  });
});

describe("question list numeric parameters", () => {
  it.each([null, "", "0", "-1", "1.5", "NaN", "Infinity", "invalid"])(
    "uses the fallback for %j", (value) => {
      expect(positiveInt(value)).toBeNull();
      expect(positiveInt(value, 1)).toBe(1);
    },
  );

  it.each(["2", " 2 ", "2e0", "2.0"])("preserves numeric coercion for %j", (value) => {
    expect(positiveInt(value)).toBe(2);
  });

  it.each([
    [null, 20], ["", 20], ["19", 20], ["0", 20], ["-50", 20],
    ["50.5", 20], ["20", 20], ["50", 50], ["100", 100], ["5e1", 50],
  ] as const)("normalizes page size %j to %i", (value, expected) => {
    expect(normalizeQuestionPageSize(value)).toBe(expected);
  });
});

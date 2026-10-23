import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { QuestionListFilters } from "../question-list-state";
import { useQuestionToolbarState } from "./use-question-toolbar-state";

const base: QuestionListFilters = {
  subject_id: "",
  question_type: "",
  year: "",
  is_active: "true",
  keyword: "",
  difficulty: "",
  import_batch_id: "",
  knowledge_point_id: "",
};

function renderHook(filters: QuestionListFilters) {
  let result!: ReturnType<typeof useQuestionToolbarState>;
  function Probe() {
    result = useQuestionToolbarState(filters);
    return null;
  }
  renderToStaticMarkup(createElement(Probe));
  return result;
}

describe("question toolbar state", () => {
  it("treats default active-only filters as inactive", () => {
    expect(renderHook(base).hasActiveFilters).toBe(false);
  });

  it.each([
    ["subject_id"],
    ["question_type"],
    ["year"],
    ["keyword"],
    ["difficulty"],
    ["import_batch_id"],
    ["knowledge_point_id"],
  ] as const)("detects %s as an active filter", (key) => {
    expect(renderHook({ ...base, [key]: "value" }).hasActiveFilters).toBe(true);
  });

  it("detects a non-default active state", () => {
    expect(renderHook({ ...base, is_active: "false" }).hasActiveFilters).toBe(true);
  });
});

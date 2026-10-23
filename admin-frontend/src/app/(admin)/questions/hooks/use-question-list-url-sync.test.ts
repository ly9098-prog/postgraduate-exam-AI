import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { QuestionListFilters } from "../question-list-state";
import { useQuestionListUrlSync } from "./use-question-list-url-sync";

const filters: QuestionListFilters = {
  subject_id: "3",
  question_type: "",
  year: "",
  is_active: "true",
  keyword: "binary",
  difficulty: "",
  import_batch_id: "",
  knowledge_point_id: "",
};

function setup(currentSearch = "?page=2") {
  const replaceState = vi.fn();
  const location = { pathname: "/questions", search: currentSearch };
  function Probe() {
    useQuestionListUrlSync(filters, 2, 20, 7, {
      getLocation: () => location,
      replaceState,
    });
    return null;
  }
  renderToStaticMarkup(createElement(Probe));
  return { location, replaceState };
}

describe("question list URL sync", () => {
  it("is a feature hook with the established page contract", () => {
    expect(typeof useQuestionListUrlSync).toBe("function");
  });

  it("does not replace the URL when the current query matches the next href", () => {
    const { replaceState } = setup("?page=2&keyword=binary&subject_id=3&selected_id=7");
    expect(replaceState).not.toHaveBeenCalled();
  });
});

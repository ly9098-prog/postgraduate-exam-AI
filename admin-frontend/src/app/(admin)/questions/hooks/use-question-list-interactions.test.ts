import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { useQuestionListInteractions } from "./use-question-list-interactions";

const defaultFilters = {
  subject_id: "",
  question_type: "",
  year: "",
  is_active: "true",
  keyword: "",
  difficulty: "",
  import_batch_id: "",
  knowledge_point_id: "",
};

function setup() {
  const state = {
    setFilters: vi.fn(),
    setPage: vi.fn(),
    setPageSize: vi.fn(),
  };
  const actions = {
    clearSelection: vi.fn(),
    closeDetailDrawer: vi.fn(),
    closeCommonFilterMenu: vi.fn(),
  };
  let hook!: ReturnType<typeof useQuestionListInteractions>;
  function Probe() {
    hook = useQuestionListInteractions(state, actions);
    return null;
  }
  renderToStaticMarkup(createElement(Probe));
  return { actions, hook, state };
}

describe("question list interactions", () => {
  it("updates one filter, resets the page, and closes the current context", () => {
    const { actions, hook, state } = setup();
    state.setFilters.mockImplementation(
      () => ({ ...defaultFilters, keyword: "binary" }),
    );

    hook.updateFilter("keyword", "binary");

    expect(state.setFilters).toHaveBeenCalledOnce();
    expect(state.setFilters.mock.results[0].value).toEqual({
      ...defaultFilters,
      keyword: "binary",
    });
    expect(state.setPage).toHaveBeenCalledWith(1);
    expect(actions.clearSelection).toHaveBeenCalledOnce();
    expect(actions.closeDetailDrawer).toHaveBeenCalledOnce();
  });

  it("applies a preset and closes the common filter menu", () => {
    const { actions, hook, state } = setup();
    const filters = { ...defaultFilters, subject_id: "3" };

    hook.applyFilterPreset(filters);

    expect(state.setFilters).toHaveBeenCalledWith(filters);
    expect(state.setPage).toHaveBeenCalledWith(1);
    expect(actions.clearSelection).toHaveBeenCalledOnce();
    expect(actions.closeDetailDrawer).toHaveBeenCalledOnce();
    expect(actions.closeCommonFilterMenu).toHaveBeenCalledOnce();
  });

  it("resets the page when page size changes", () => {
    const { hook, state } = setup();

    hook.updatePageSize(50);

    expect(state.setPageSize).toHaveBeenCalledWith(50);
    expect(state.setPage).toHaveBeenCalledWith(1);
  });
});

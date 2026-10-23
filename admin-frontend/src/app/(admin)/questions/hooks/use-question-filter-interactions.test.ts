import { createElement, useRef, useState } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_QUESTION_FILTERS, type QuestionListFilters } from "../question-list-state";
import { SAVED_FILTER_STORAGE_KEY } from "./question-filter-interactions-test-constants";
import { useQuestionFilterInteractions } from "./use-question-filter-interactions";

function storageWith(raw: string | null = null) {
  let stored = raw;
  return {
    getItem: vi.fn((): string | null => stored),
    removeItem: vi.fn(() => { stored = null; }),
    setItem: vi.fn((_key: string, value: string) => { stored = value; }),
    getStored: () => stored,
  };
}

type Interactions = ReturnType<typeof useQuestionFilterInteractions>;

function renderInteractions(initialFilters: QuestionListFilters = { ...DEFAULT_QUESTION_FILTERS }) {
  const onFilterChanged = vi.fn();
  const onFilterPresetApplied = vi.fn();
  const onPageSizeChanged = vi.fn();
  const onMessage = vi.fn();
  const storage = storageWith();
  const actions: Array<(interactions: Interactions) => void> = [];
  function Probe() {
    const step = useRef(0);
    const [tick, setTick] = useState(0);
    const interactions = useQuestionFilterInteractions({
      initialFilters,
      onFilterChanged,
      onFilterPresetApplied,
      onPageSizeChanged,
      onMessage,
      getStorage: () => storage,
    });
    latest = interactions;
    if (step.current < actions.length) {
      actions[step.current++](interactions);
      setTick(tick + 1);
    }
    return null;
  }
  const render = () => renderToStaticMarkup(createElement(Probe));
  let latest: Interactions;
  const run = (action: (interactions: Interactions) => void) => {
    actions.push(action);
    render();
  };
  const observe = () => latest;
  return {
    run,
    observe,
    onFilterChanged,
    onFilterPresetApplied,
    onPageSizeChanged,
    onMessage,
    storage,
  };
}

describe("useQuestionFilterInteractions", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  it("debounces keyword input and clears an empty keyword sooner", () => {
    const h = renderInteractions();

    let observed!: Interactions;
    h.run(interactions => {
      interactions.handleKeywordChange("  数据");
    });
    observed = h.observe();
    expect(observed.keywordInput).toBe("  数据");
    expect(h.onFilterChanged).not.toHaveBeenCalled();
    vi.advanceTimersByTime(300);
    expect(h.onFilterChanged).toHaveBeenCalledTimes(1);
    h.onFilterChanged.mockClear();

    h.run(interactions => {
      interactions.handleKeywordChange("  数据 ");
    });
    observed = h.observe();
    vi.advanceTimersByTime(99);
    expect(observed.searchDebouncing).toBe(true);
    expect(observed.keywordInput).toBe("  数据 ");
    expect(h.onFilterChanged).not.toHaveBeenCalled();
  });

  it("submits import batches after the existing debounce and trims values", () => {
    const h = renderInteractions();

    h.run(interactions => interactions.handleImportBatchChange(" batch-1 "));
    expect(h.onFilterChanged).not.toHaveBeenCalled();
    vi.advanceTimersByTime(449);
    expect(h.onFilterChanged).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(h.onFilterChanged).toHaveBeenCalledTimes(1);
  });

  it("clears pending timers and resets inputs when filters are reset", () => {
    const h = renderInteractions();

    h.run(interactions => {
      interactions.handleKeywordChange("算法");
      interactions.handleImportBatchChange("batch-1");
      interactions.handleResetFilters();
    });
    const observed = h.observe();
    vi.advanceTimersByTime(1000);

    expect(observed.keywordInput).toBe("");
    expect(observed.importBatchInput).toBe("");
    expect(observed.searchDebouncing).toBe(false);
    expect(h.onFilterChanged).not.toHaveBeenCalled();
    expect(h.onFilterPresetApplied).toHaveBeenCalledWith({ ...DEFAULT_QUESTION_FILTERS });
  });

  it("applies presets with defaults and updates both input fields", () => {
    const h = renderInteractions();

    h.run(interactions => {
      interactions.applyFilterPreset({ keyword: "图", import_batch_id: "batch-2" });
    });
    const observed = h.observe();

    expect(observed.keywordInput).toBe("图");
    expect(observed.importBatchInput).toBe("batch-2");
    expect(h.onFilterPresetApplied).toHaveBeenCalledWith({
      ...DEFAULT_QUESTION_FILTERS,
      keyword: "图",
      import_batch_id: "batch-2",
    });
  });

  it("saves and reloads persisted filters through the existing persistence contract", () => {
    const h = renderInteractions();
    const filters = { ...DEFAULT_QUESTION_FILTERS, keyword: "排序" };

    h.run(interactions => interactions.handleSaveCurrentFilters(filters));
    expect(h.onMessage).toHaveBeenCalledWith("当前筛选条件已保存到本机。 ");
    expect(h.storage.setItem).toHaveBeenCalledExactlyOnceWith(
      SAVED_FILTER_STORAGE_KEY,
      JSON.stringify(filters),
    );

    const fresh = renderInteractions();
    fresh.storage.getItem.mockReturnValue(JSON.stringify(filters));
    fresh.run(interactions => interactions.handleApplySavedFilters());
    expect(fresh.onFilterPresetApplied).toHaveBeenCalledWith(filters);
  });
});

"use client";

import { useCallback } from "react";
import type { QuestionListFilters } from "../question-list-state";

type ListInteractionState = {
  setPage: (page: number) => void;
  setFilters: React.Dispatch<React.SetStateAction<QuestionListFilters>>;
  setPageSize: (pageSize: number) => void;
};

type ListInteractionActions = {
  clearSelection: () => void;
  closeDetailDrawer: () => void;
  closeCommonFilterMenu: () => void;
};

export function useQuestionListInteractions(
  state: ListInteractionState,
  actions: ListInteractionActions,
) {
  const updateFilter = useCallback(
    (key: keyof QuestionListFilters, value: string) => {
      state.setFilters((current) => ({ ...current, [key]: value }));
      state.setPage(1);
      // 与公式库保持一致：筛选刷新时保留详情上下文，等新列表返回后再自动校正选中项。
      actions.clearSelection();
      actions.closeDetailDrawer();
    },
    [actions, state],
  );

  const applyFilterPreset = useCallback((filters: QuestionListFilters) => {
    state.setFilters(filters);
    state.setPage(1);
    actions.clearSelection();
    actions.closeDetailDrawer();
    actions.closeCommonFilterMenu();
  }, [actions, state]);

  const updatePageSize = useCallback((pageSize: number) => {
    state.setPageSize(pageSize);
    state.setPage(1);
  }, [state]);

  return { updateFilter, applyFilterPreset, updatePageSize };
}

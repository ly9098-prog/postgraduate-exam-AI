"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type QuestionDetailNavigationOptions = {
  initialSelectedQuestionId: number | null;
  items: Array<{ id: number }>;
  isFetching: boolean;
  setEditing: (editing: boolean) => void;
  setEditForm: (form: Record<string, unknown>) => void;
  openDetailDrawer: (open: boolean) => void;
  prefetch: (id: number) => void;
  onScrollTop: () => void;
  requestAnimationFrame: (callback: () => void) => number;
  cancelAnimationFrame: (frame: number) => void;
};

export function resolveQuestionListSelection(
  items: Array<{ id: number }>,
  isFetching: boolean,
  selectedQuestionId: number | null,
): number | null {
  if (!items.length) return isFetching ? selectedQuestionId : null;
  if (
    selectedQuestionId !== null &&
    items.some((item) => item.id === selectedQuestionId)
  ) {
    return selectedQuestionId;
  }
  return items[0].id;
}

export function useQuestionDetailNavigation({
  initialSelectedQuestionId,
  items,
  isFetching,
  setEditing,
  setEditForm,
  openDetailDrawer,
  prefetch,
  onScrollTop,
  requestAnimationFrame,
  cancelAnimationFrame,
}: QuestionDetailNavigationOptions) {
  const [selectedQuestionId, setSelectedQuestionIdState] = useState(initialSelectedQuestionId);
  const selectedQuestionIdRef = useRef(selectedQuestionId);

  const setSelectedQuestionId = useCallback((id: number | null) => {
    selectedQuestionIdRef.current = id;
    setSelectedQuestionIdState(id);
  }, []);

  const editorCallbacksRef = useRef({ setEditing, setEditForm });
  useEffect(() => {
    editorCallbacksRef.current = { setEditing, setEditForm };
  }, [setEditForm, setEditing]);

  const selectQuestion = useCallback((id: number) => {
    setSelectedQuestionId(id);
    editorCallbacksRef.current.setEditing(false);
    editorCallbacksRef.current.setEditForm({});
  }, [setSelectedQuestionId]);

  const openDetail = useCallback((id: number) => {
    selectQuestion(id);
    openDetailDrawer(true);
  }, [openDetailDrawer, selectQuestion]);

  // Match the pre-refactor page behavior: keep detail context while a list
  // refresh is in flight, then auto-select the first visible question.
  useEffect(() => {
    const next = resolveQuestionListSelection(items, isFetching, selectedQuestionIdRef.current);
    if (next === selectedQuestionIdRef.current) return;
    if (next === null) {
      setSelectedQuestionId(null);
      return;
    }
    selectQuestion(next);
  }, [isFetching, items, selectQuestion, setSelectedQuestionId]);

  const prefetchDetail = useCallback((id: number) => {
    void prefetch(id);
  }, [prefetch]);

  useEffect(() => {
    if (selectedQuestionId === null) return;
    const frame = requestAnimationFrame(onScrollTop);
    return () => cancelAnimationFrame(frame);
  }, [cancelAnimationFrame, onScrollTop, requestAnimationFrame, selectedQuestionId]);

  return {
    selectedQuestionId,
    selectedQuestionIdRef,
    setSelectedQuestionId,
    selectQuestion,
    openDetail,
    prefetchDetail,
  };
}

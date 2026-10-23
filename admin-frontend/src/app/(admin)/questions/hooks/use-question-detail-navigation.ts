"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type QuestionDetailNavigationOptions = {
  initialSelectedQuestionId: number | null;
  setEditing: (editing: boolean) => void;
  setEditForm: (form: Record<string, unknown>) => void;
  openDetailDrawer: (open: boolean) => void;
  prefetch: (id: number) => void;
  onScrollTop: () => void;
  requestAnimationFrame: (callback: () => void) => number;
  cancelAnimationFrame: (frame: number) => void;
};

export function useQuestionDetailNavigation({
  initialSelectedQuestionId,
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

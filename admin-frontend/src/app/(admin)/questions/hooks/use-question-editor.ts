import {
  useCallback, useEffect, useMemo, useState,
  type Dispatch, type RefObject, type SetStateAction,
} from "react";
import type { AdminQuestion, QuestionEditRequest } from "@/lib/api/types";
import { createQuestionEditDraft } from "../question-edit-draft";
import { buildQuestionEditPatch } from "../question-edit-patch";
import {
  listenQuestionEditorEscape, lockQuestionDrawerScroll, protectQuestionEditorUnload,
} from "../question-editor-events";

type UnsavedIntent = "cancel-edit" | "close-drawer" | null;
type EditorState = {
  editing: boolean;
  dirty: boolean;
  setEditing: Dispatch<SetStateAction<boolean>>;
  setEditForm: Dispatch<SetStateAction<QuestionEditRequest>>;
  setEditStemText: Dispatch<SetStateAction<string>>;
  setUnsavedIntent: Dispatch<SetStateAction<UnsavedIntent>>;
};
type DrawerState = {
  isDetailDrawerOpen: boolean;
  setIsDetailDrawerOpen: Dispatch<SetStateAction<boolean>>;
  confirmState: unknown | null;
  detailScrollRef: RefObject<HTMLDivElement | null>;
};

export function useQuestionEditorActions(
  question: AdminQuestion | undefined,
  state: EditorState,
  drawer: Pick<DrawerState, "setIsDetailDrawerOpen" | "detailScrollRef">,
) {
  const { editing, dirty, setEditing, setEditForm, setEditStemText, setUnsavedIntent } = state;
  const { setIsDetailDrawerOpen, detailScrollRef } = drawer;
  const startEditing = () => {
    if (!question) return;
    const draft = createQuestionEditDraft(question);
    setEditStemText(draft.stemText);
    setEditForm(draft.form);
    setEditing(true);
    window.requestAnimationFrame(() => {
      detailScrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    });
  };
  const finishCancelEditing = useCallback(() => {
    setEditing(false);
    setEditForm({});
    setEditStemText("");
    setUnsavedIntent(null);
  }, [setEditing, setEditForm, setEditStemText, setUnsavedIntent]);
  const finishCloseDetailDrawer = useCallback(() => {
    finishCancelEditing();
    setIsDetailDrawerOpen(false);
  }, [finishCancelEditing, setIsDetailDrawerOpen]);
  const cancelEditing = () => {
    if (dirty) {
      setUnsavedIntent("cancel-edit");
      return;
    }
    finishCancelEditing();
  };
  const closeDetailDrawer = () => {
    if (editing && dirty) {
      setUnsavedIntent("close-drawer");
      return;
    }
    finishCloseDetailDrawer();
  };
  return {
    startEditing, finishCancelEditing, finishCloseDetailDrawer, cancelEditing, closeDetailDrawer,
  };
}

function useQuestionEditorGuards(
  state: EditorState & { unsavedIntent: UnsavedIntent },
  drawer: DrawerState,
  actions: ReturnType<typeof useQuestionEditorActions>,
) {
  const { editing, dirty, unsavedIntent, setUnsavedIntent } = state;
  const { isDetailDrawerOpen, confirmState } = drawer;
  const { finishCancelEditing, finishCloseDetailDrawer } = actions;
  useEffect(() => {
    if (!isDetailDrawerOpen) return;
    return lockQuestionDrawerScroll();
  }, [isDetailDrawerOpen]);
  useEffect(() => {
    if (!(editing && dirty)) return;
    return protectQuestionEditorUnload();
  }, [dirty, editing]);
  useEffect(() => {
    if (!isDetailDrawerOpen) return;
    return listenQuestionEditorEscape({
      editing, dirty, blocked: confirmState !== null || unsavedIntent !== null,
      cancel: finishCancelEditing,
      close: finishCloseDetailDrawer,
      requestCancel: () => setUnsavedIntent("cancel-edit"),
    });
  }, [
    confirmState, dirty, editing, finishCancelEditing, finishCloseDetailDrawer,
    isDetailDrawerOpen, unsavedIntent, setUnsavedIntent,
  ]);
}

export function useQuestionEditor(question: AdminQuestion | undefined, drawer: DrawerState) {
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState<QuestionEditRequest>({});
  const [editStemText, setEditStemText] = useState("");
  const [unsavedIntent, setUnsavedIntent] = useState<UnsavedIntent>(null);
  const dirty = useMemo(() => {
    if (!question) return false;
    return Object.keys(buildQuestionEditPatch(editForm, question, editStemText)).length > 0;
  }, [editForm, editStemText, question]);
  const state = {
    editing, dirty, setEditing, setEditForm, setEditStemText, unsavedIntent, setUnsavedIntent,
  };
  const actions = useQuestionEditorActions(question, state, drawer);
  useQuestionEditorGuards(state, drawer, actions);
  return { ...state, editForm, editStemText, ...actions };
}

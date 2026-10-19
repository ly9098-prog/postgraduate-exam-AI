export type QuestionEditorEscapeState = {
  editing: boolean;
  dirty: boolean;
  blocked: boolean;
  cancel: () => void;
  close: () => void;
  requestCancel: () => void;
};

export function lockQuestionDrawerScroll() {
  const previousOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";
  return () => {
    document.body.style.overflow = previousOverflow;
  };
}

export function protectQuestionEditorUnload() {
  const handleBeforeUnload = (event: BeforeUnloadEvent) => {
    event.preventDefault();
    event.returnValue = "";
  };
  window.addEventListener("beforeunload", handleBeforeUnload);
  return () => window.removeEventListener("beforeunload", handleBeforeUnload);
}

export function listenQuestionEditorEscape(state: QuestionEditorEscapeState) {
  const handleDrawerEscape = (event: KeyboardEvent) => {
    if (event.key !== "Escape" || event.defaultPrevented) return;
    // Portaled selects and confirmation dialogs own their Escape key.
    if (document.querySelector('[role="combobox"][aria-expanded="true"]')) return;
    if (document.querySelector('[data-confirm-dialog="true"]')) return;
    if (state.blocked) return;

    event.preventDefault();
    if (state.editing) {
      if (state.dirty) state.requestCancel();
      else state.cancel();
    } else {
      state.close();
    }
  };
  document.addEventListener("keydown", handleDrawerEscape);
  return () => document.removeEventListener("keydown", handleDrawerEscape);
}

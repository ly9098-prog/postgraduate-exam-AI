import { createElement, useState } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AdminQuestion } from "@/lib/api/types";
import { useQuestionEditor } from "./hooks/use-question-editor";
import {
  listenQuestionEditorEscape, lockQuestionDrawerScroll, protectQuestionEditorUnload,
} from "./question-editor-events";

const question: AdminQuestion = {
  id: 7, question_type: "single_choice", answer: "A", difficulty: 2,
  content: { stem: "stem" }, options: { A: "yes", B: "no" },
  review_status: "approved", is_active: true,
};
type Editor = ReturnType<typeof useQuestionEditor>;
const frameCallbacks: FrameRequestCallback[] = [];
const scrollTo = vi.fn();
const setDrawerOpen = vi.fn();
function runEditor(steps: Array<(editor: Editor) => void>, baseline = question) {
  let result!: Editor;
  function Probe() {
    const [step, setStep] = useState(0);
    result = useQuestionEditor(baseline, {
      isDetailDrawerOpen: true, confirmState: null, setIsDetailDrawerOpen: setDrawerOpen,
      detailScrollRef: { current: { scrollTo } as unknown as HTMLDivElement },
    });
    if (steps[step]) {
      steps[step](result);
      setStep(step + 1);
    }
    return null;
  }
  renderToStaticMarkup(createElement(Probe));
  return result;
}

beforeEach(() => {
  frameCallbacks.length = 0;
  const browserWindow = new EventTarget();
  Object.assign(browserWindow, {
    requestAnimationFrame: vi.fn((callback: FrameRequestCallback) => {
      frameCallbacks.push(callback);
      return frameCallbacks.length;
    }),
  });
  const browserDocument = new EventTarget();
  Object.assign(browserDocument, {
    body: { style: { overflow: "auto" } },
    querySelector: vi.fn(() => null),
  });
  vi.stubGlobal("window", browserWindow);
  vi.stubGlobal("document", browserDocument);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("question editor state and transitions with real React server rerenders", () => {
  it("opens an independent draft then scrolls on the scheduled frame", () => {
    const editor = runEditor([(state) => state.startEditing()]);
    expect(editor.editing).toBe(true);
    expect(editor.dirty).toBe(false);
    expect(editor.editStemText).toBe("stem");
    expect(editor.editForm.content).toEqual(question.content);
    expect(editor.editForm.content).not.toBe(question.content);
    expect(scrollTo).not.toHaveBeenCalled();
    frameCallbacks[0](0);
    expect(scrollTo).toHaveBeenCalledExactlyOnceWith({ top: 0, behavior: "smooth" });
    expect(setDrawerOpen).not.toHaveBeenCalled();
  });

  it("does nothing when opening before detail is available", () => {
    let result!: Editor;
    function Probe() {
      result = useQuestionEditor(undefined, {
        isDetailDrawerOpen: false, setIsDetailDrawerOpen: setDrawerOpen,
        confirmState: null, detailScrollRef: { current: null },
      });
      return null;
    }
    renderToStaticMarkup(createElement(Probe));
    result.startEditing();
    expect(result.editing).toBe(false);
    expect(result.dirty).toBe(false);
    expect(frameCallbacks).toHaveLength(0);
  });

  it.each(["cancelEditing", "closeDetailDrawer"] as const)(
    "clears a clean draft with %s", (action) => {
      const editor = runEditor([
        (state) => state.startEditing(),
        (state) => state[action](),
      ]);
      expect(editor.editing).toBe(false);
      expect(editor.editForm).toEqual({});
      expect(editor.editStemText).toBe("");
      expect(editor.unsavedIntent).toBeNull();
      expect(setDrawerOpen.mock.calls).toEqual(action === "closeDetailDrawer" ? [[false]] : []);
    },
  );

  it.each([
    ["cancelEditing", "cancel-edit"], ["closeDetailDrawer", "close-drawer"],
  ] as const)("preserves dirty state while %s asks for confirmation", (action, intent) => {
    const editor = runEditor([
      (state) => state.startEditing(),
      (state) => state.setEditStemText("changed"),
      (state) => state[action](),
    ]);
    expect(editor.unsavedIntent).toBe(intent);
    expect(editor.editing).toBe(true);
    expect(editor.dirty).toBe(true);
    expect(editor.editStemText).toBe("changed");
    expect(setDrawerOpen).not.toHaveBeenCalled();
  });

  it("keeps the draft when dismissing confirmation and detects form edits", () => {
    const editor = runEditor([
      (state) => state.startEditing(),
      (state) => state.setEditForm((form) => ({ ...form, answer: "B" })),
      (state) => state.closeDetailDrawer(),
      (state) => {
        expect(state.unsavedIntent).toBe("close-drawer");
        state.setUnsavedIntent(null);
      },
    ]);
    expect(editor.unsavedIntent).toBeNull();
    expect(editor.dirty).toBe(true);
    expect(editor.editForm.answer).toBe("B");
    expect(setDrawerOpen).not.toHaveBeenCalled();
  });

  it.each(["finishCancelEditing", "finishCloseDetailDrawer"] as const)(
    "discards a confirmed draft through %s", (action) => {
      const editor = runEditor([
        (state) => state.startEditing(),
        (state) => state.setEditStemText("changed"),
        (state) => state.closeDetailDrawer(),
        (state) => state[action](),
      ]);
      expect(editor.editing).toBe(false);
      expect(editor.editForm).toEqual({});
      expect(editor.editStemText).toBe("");
      expect(editor.unsavedIntent).toBeNull();
      expect(setDrawerOpen.mock.calls).toEqual(action === "finishCloseDetailDrawer" ? [[false]] : []);
    },
  );

  it("closes without confirmation outside edit mode even when the empty form is dirty", () => {
    const editor = runEditor([(state) => {
      expect(state.dirty).toBe(true);
      expect(state.editing).toBe(false);
      state.closeDetailDrawer();
    }]);
    expect(editor.unsavedIntent).toBeNull();
    expect(setDrawerOpen).toHaveBeenCalledExactlyOnceWith(false);
  });

  it("keeps editor state local to each page instance", () => {
    const first = runEditor([
      (state) => state.startEditing(),
      (state) => state.setEditStemText("first draft"),
      (state) => state.cancelEditing(),
    ]);
    const second = runEditor([]);
    expect(first.editStemText).toBe("first draft");
    expect(first.unsavedIntent).toBe("cancel-edit");
    expect(second.editing).toBe(false);
    expect(second.editStemText).toBe("");
    expect(second.editForm).toEqual({});
    expect(second.unsavedIntent).toBeNull();
  });
});

describe("question editor browser subscriptions", () => {
  it("restores the existing body overflow value when the drawer effect cleans up", () => {
    document.body.style.overflow = "scroll";
    const cleanup = lockQuestionDrawerScroll();
    expect(document.body.style.overflow).toBe("hidden");
    cleanup();
    expect(document.body.style.overflow).toBe("scroll");
  });

  it("prevents unload and unregisters the exact callback", () => {
    const add = vi.spyOn(window, "addEventListener");
    const remove = vi.spyOn(window, "removeEventListener");
    const cleanup = protectQuestionEditorUnload();
    const event = new Event("beforeunload", { cancelable: true });
    // Node's Event has a boolean returnValue; browsers give BeforeUnloadEvent a string.
    Object.defineProperty(event, "returnValue", { value: "initial", writable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect(event.returnValue).toBe("");
    cleanup();
    expect(remove).toHaveBeenCalledWith("beforeunload", add.mock.calls[0][1]);
    const after = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(after);
    expect(after.defaultPrevented).toBe(false);
  });

  it.each([
    [true, true, "requestCancel"], [true, false, "cancel"], [false, true, "close"],
  ] as const)("routes Escape for editing=%s dirty=%s", (editing, dirty, expected) => {
    const callbacks = { cancel: vi.fn(), close: vi.fn(), requestCancel: vi.fn() };
    const cleanup = listenQuestionEditorEscape({ editing, dirty, blocked: false, ...callbacks });
    const event = Object.assign(new Event("keydown", { cancelable: true }), { key: "Escape" });
    document.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    for (const [name, callback] of Object.entries(callbacks)) {
      expect(callback).toHaveBeenCalledTimes(name === expected ? 1 : 0);
    }
    cleanup();
    document.dispatchEvent(Object.assign(new Event("keydown"), { key: "Escape" }));
    expect(callbacks[expected]).toHaveBeenCalledTimes(1);
  });

  it.each(["other-key", "prevented", "select", "dialog", "blocked"])(
    "leaves Escape to an existing owner: %s", (owner) => {
      const callbacks = { cancel: vi.fn(), close: vi.fn(), requestCancel: vi.fn() };
      vi.spyOn(document, "querySelector").mockImplementation((selector) => (
        (owner === "select" && selector.includes("combobox")) ||
        (owner === "dialog" && selector.includes("confirm-dialog"))
      ) ? {} as Element : null);
      const cleanup = listenQuestionEditorEscape({
        editing: true, dirty: true, blocked: owner === "blocked", ...callbacks,
      });
      const event = Object.assign(new Event("keydown", { cancelable: true }), {
        key: owner === "other-key" ? "Enter" : "Escape",
      });
      if (owner === "prevented") event.preventDefault();
      document.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(owner === "prevented");
      Object.values(callbacks).forEach((callback) => expect(callback).not.toHaveBeenCalled());
      cleanup();
    },
  );
});

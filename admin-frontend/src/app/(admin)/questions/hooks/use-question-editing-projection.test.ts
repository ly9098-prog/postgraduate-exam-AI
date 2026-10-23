import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { useQuestionEditingProjection } from "./use-question-editing-projection";

const form = {
  content: {
    segments: [
      { type: "code", text: "print('ok')" },
      { type: "code", text: "" },
      {
        type: "table",
        requires_review: true,
        rows: [{ cells: [{ text: "A" }] }],
      },
    ],
  } as Record<string, unknown>,
};

function renderHook(setEditForm = vi.fn()) {
  let result!: ReturnType<typeof useQuestionEditingProjection>;
  function Probe() {
    result = useQuestionEditingProjection(form, undefined, { setEditForm });
    return null;
  }
  renderToStaticMarkup(createElement(Probe));
  return { result, setEditForm };
}

describe("question editing projection", () => {
  it("projects segments and counts blocking editors", () => {
    const { result } = renderHook();

    expect(result.editingSegments).toHaveLength(3);
    expect(result.editingFallbackStemImageUrls).toEqual([]);
    expect(result.unresolvedEditingTableCount).toBe(1);
    expect(result.emptyEditingCodeCount).toBe(1);
  });

  it("exposes segment replacement and code-segment addition handlers", () => {
    const { result, setEditForm } = renderHook();

    result.replaceEditingSegments([]);
    result.addEditingCodeSegment();

    expect(setEditForm).toHaveBeenCalledTimes(2);
    expect(typeof setEditForm.mock.calls[0][0]).toBe("function");
    expect(typeof setEditForm.mock.calls[1][0]).toBe("function");
  });
});

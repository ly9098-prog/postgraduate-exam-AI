import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { useQuestionFeedback } from "./use-question-feedback";

function renderHook() {
  let result!: ReturnType<typeof useQuestionFeedback>;
  function Probe() {
    result = useQuestionFeedback();
    return null;
  }
  renderToStaticMarkup(createElement(Probe));
  return result;
}

describe("question feedback", () => {
  it("starts without a message and exposes the established handlers", () => {
    const hook = renderHook();

    expect(hook.message).toBeNull();
    expect(typeof hook.setMessage).toBe("function");
    expect(typeof hook.clearMessage).toBe("function");
  });

  it("does not schedule auto-close for a null message", () => {
    const schedule = vi.fn();
    let result!: ReturnType<typeof useQuestionFeedback>;
    function Probe() {
      result = useQuestionFeedback(schedule, vi.fn());
      return null;
    }
    renderToStaticMarkup(createElement(Probe));

    expect(schedule).not.toHaveBeenCalled();
    expect(result.message).toBeNull();
  });
});

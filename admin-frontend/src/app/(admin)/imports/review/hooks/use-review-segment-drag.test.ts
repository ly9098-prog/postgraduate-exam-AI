import { createElement, useRef, useState, type DragEvent } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { useReviewSegmentDrag } from "./use-review-segment-drag";

function event() {
  return {
    preventDefault: vi.fn(),
    dataTransfer: { setData: vi.fn(), effectAllowed: "", dropEffect: "" },
  };
}

function renderHook<T>(useFeature: () => T): T {
  let result!: T;
  function Probe() {
    result = useFeature();
    return null;
  }
  renderToStaticMarkup(createElement(Probe));
  return result;
}

describe("review visual segment drag", () => {
  it("keeps drag state and ref source through rerenders and resets on leaving, dropping and ending", () => {
    const segments = [{ type: "image" }, { type: "newline" }, { type: "image" }];
    const onChange = vi.fn();
    const dragEvent = event();
    const input = dragEvent as unknown as DragEvent;
    const observed: number[][] = [];
    const actions: Array<(drag: ReturnType<typeof useReviewSegmentDrag>) => void> = [
      (drag) => drag.start(0, input),
      (drag) => drag.over(1, input),
      (drag) => drag.leave(),
      (drag) => drag.over(2, input),
      (drag) => drag.drop(2, input),
      (drag) => drag.start(1, input),
      (drag) => drag.end(),
    ];
    function Probe() {
      const drag = useReviewSegmentDrag(segments, onChange);
      const step = useRef(0);
      const [tick, setTick] = useState(0);
      observed.push([drag.dragIndex, drag.overIndex]);
      if (step.current < actions.length) {
        actions[step.current++](drag);
        setTick(tick + 1);
      }
      return null;
    }
    renderToStaticMarkup(createElement(Probe));
    expect(observed).toEqual([[-1, -1], [0, -1], [0, 1], [0, -1], [0, 2], [-1, -1], [1, -1], [-1, -1]]);
    expect(onChange).toHaveBeenCalledExactlyOnceWith([segments[1], segments[2], segments[0]]);
    expect(dragEvent.dataTransfer.effectAllowed).toBe("move");
    expect(dragEvent.dataTransfer.dropEffect).toBe("move");
    expect(dragEvent.dataTransfer.setData.mock.calls).toEqual([["text/plain", "0"], ["text/plain", "1"]]);
    expect(dragEvent.preventDefault).toHaveBeenCalledTimes(3);
  });

  it("ignores unset and same-index sources and isolates refs across hook instances", () => {
    const segments = [{ type: "image" }, { type: "newline" }];
    const onChange = vi.fn();
    const hooks = renderHook(() => [
      useReviewSegmentDrag(segments, onChange), useReviewSegmentDrag(segments, onChange),
    ]);
    const input = event() as unknown as DragEvent;
    hooks[0].drop(1, input);
    hooks[0].start(0, input);
    hooks[0].drop(0, input);
    hooks[1].drop(1, input);
    expect(onChange).not.toHaveBeenCalled();
    hooks[0].drop(1, input);
    expect(onChange).toHaveBeenCalledExactlyOnceWith([segments[1], segments[0]]);
    expect(segments[0].type).toBe("image");
  });
});

import { createElement, useRef, useState } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { useQuestionDetailNavigation } from "./use-question-detail-navigation";

type Navigation = ReturnType<typeof useQuestionDetailNavigation>;

function harness() {
  const calls: unknown[] = [];
  const options = {
    initialSelectedQuestionId: null as number | null,
    setEditing: (value: boolean) => calls.push(["editing", value]),
    setEditForm: (value: Record<string, unknown>) => calls.push(["form", value]),
    openDetailDrawer: (value: boolean) => calls.push(["drawer", value]),
    prefetch: vi.fn(),
    onScrollTop: () => calls.push(["scroll"]),
    requestAnimationFrame: vi.fn(() => 1),
    cancelAnimationFrame: vi.fn(),
  };
  return { options, calls };
}

type NavigationOptions = Parameters<typeof useQuestionDetailNavigation>[0];

function render(options: NavigationOptions) {
  let observed!: Navigation;
  const actions: Array<(navigation: Navigation) => void> = [];
  function Probe() {
    const step = useRef(0);
    const [tick, setTick] = useState(0);
    const navigation = useQuestionDetailNavigation(options);
    observed = navigation;
    if (step.current < actions.length) {
      actions[step.current++](navigation);
      setTick(tick + 1);
    }
    return null;
  }
  renderToStaticMarkup(createElement(Probe));
  return {
    get current() { return observed; },
    run: (action: (navigation: Navigation) => void) => {
      actions.push(action);
      renderToStaticMarkup(createElement(Probe));
    },
  };
}

describe("useQuestionDetailNavigation", () => {
  it("keeps an explicitly selected question", () => {
    const h = harness();
    const navigation = render(h.options);
    navigation.run(value => {
      value.setSelectedQuestionId(2);
    });

    expect(navigation.current.selectedQuestionId).toBe(2);
    expect(h.calls).toEqual([]);
  });

  it("starts with the URL-selected question", () => {
    const h = harness();
    h.options.initialSelectedQuestionId = 1;
    const navigation = render(h.options);
    expect(navigation.current.selectedQuestionId).toBe(1);
    expect(h.calls).toEqual([]);
  });

  it("clears selection through the explicit setter", () => {
    const h = harness();
    h.options.initialSelectedQuestionId = 3;
    const navigation = render(h.options);
    navigation.run(value => value.setSelectedQuestionId(null));
    expect(navigation.current.selectedQuestionId).toBeNull();
  });

  it("opens detail by selecting then opening the drawer", () => {
    const h = harness();
    const navigation = render(h.options);
    navigation.run(value => value.openDetail(2));
    navigation.run(value => value.selectQuestion(3));

    expect(navigation.current.selectedQuestionId).toBe(3);
    expect(h.calls).toEqual([
      ["editing", false],
      ["form", {}],
      ["drawer", true],
      ["editing", false],
      ["form", {}],
      ["drawer", true],
      ["editing", false],
      ["form", {}],
    ]);
    expect(h.options.prefetch).not.toHaveBeenCalled();
  });

  it("prefetches with the established detail options and schedule scrolling on selection", () => {
    const h = harness();
    const navigation = render(h.options);
    navigation.run(value => value.setSelectedQuestionId(4));
    navigation.run(value => value.setSelectedQuestionId(5));
    navigation.run(value => value.prefetchDetail(4));

    expect(h.options.prefetch).toHaveBeenCalledExactlyOnceWith(4);
    expect(h.options.requestAnimationFrame).not.toHaveBeenCalled();
    expect(h.options.cancelAnimationFrame).not.toHaveBeenCalled();
  });
});

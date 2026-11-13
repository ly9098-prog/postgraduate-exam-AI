import { createElement, useEffect, useState } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useQuestionFeedback } from "./use-question-feedback";

vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>();
  return { ...actual, useEffect: vi.fn(), useState: vi.fn(actual.useState) };
});

function renderHook(
  message: string | null = null,
  ...timers: Parameters<typeof useQuestionFeedback>
) {
  const setMessage = vi.fn();
  const effectStart = vi.mocked(useEffect).mock.calls.length;
  vi.mocked(useState).mockReturnValueOnce([message, setMessage]);
  let result!: ReturnType<typeof useQuestionFeedback>;
  function Probe() {
    result = useQuestionFeedback(...timers);
    return null;
  }
  renderToStaticMarkup(createElement(Probe));
  const cleanups = vi.mocked(useEffect).mock.calls.slice(effectStart).map(([effect]) => effect());
  return {
    ...result,
    setMessage,
    cleanup: () => cleanups.forEach((cleanup) => cleanup?.()),
  };
}

describe("question feedback", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("starts without a message and exposes the established handlers", () => {
    const hook = renderHook();

    expect(hook.message).toBeNull();
    expect(typeof hook.setMessage).toBe("function");
    expect(typeof hook.clearMessage).toBe("function");
  });

  it("does not schedule auto-close for a null message", () => {
    const schedule = vi.fn();
    const hook = renderHook(null, schedule, vi.fn());

    expect(schedule).not.toHaveBeenCalled();
    expect(hook.message).toBeNull();
    expect(() => hook.cleanup()).not.toThrow();
  });

  it("auto-closes a visible message after 3800 milliseconds", () => {
    const hook = renderHook("题干和选项已复制。");

    vi.advanceTimersByTime(3799);
    expect(hook.setMessage).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(hook.setMessage).toHaveBeenCalledExactlyOnceWith(null);
    hook.cleanup();
  });

  it("cleans up the default timer with the browser global receiver", () => {
    const clearTimer = globalThis.clearTimeout;
    const browserClearTimeout = vi.fn(function (
      this: unknown,
      timer: ReturnType<typeof setTimeout>,
    ) {
      if (this !== undefined && this !== globalThis) {
        throw new TypeError("Illegal invocation");
      }
      clearTimer(timer);
    });
    vi.stubGlobal("clearTimeout", browserClearTimeout);
    const hook = renderHook("题目已更新。");

    expect(vi.getTimerCount()).toBe(1);
    expect(() => hook.cleanup()).not.toThrow();
    expect(browserClearTimeout).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(3800);
    expect(hook.setMessage).not.toHaveBeenCalled();
  });

  it("keeps manual dismissal and injected timer cleanup working", () => {
    const timer = setTimeout(() => {}, 60_000);
    const schedule = vi.fn(() => timer);
    const cancel = vi.fn((pending: ReturnType<typeof setTimeout>) => clearTimeout(pending));
    const hook = renderHook("复制失败，请重试。", schedule, cancel);

    hook.clearMessage();
    hook.cleanup();

    expect(schedule).toHaveBeenCalledWith(expect.any(Function), 3800);
    expect(hook.setMessage).toHaveBeenCalledExactlyOnceWith(null);
    expect(cancel).toHaveBeenCalledExactlyOnceWith(timer);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("calls injected native timers without binding them to a ref", () => {
    const scheduleTimer = globalThis.setTimeout;
    const cancelTimer = globalThis.clearTimeout;
    const schedule = vi.fn(function (
      this: unknown,
      callback: () => void,
      delay: number,
    ) {
      if (this !== undefined && this !== globalThis) {
        throw new TypeError("Illegal invocation");
      }
      return scheduleTimer(callback, delay);
    });
    const cancel = vi.fn(function (this: unknown, timer: ReturnType<typeof setTimeout>) {
      if (this !== undefined && this !== globalThis) {
        throw new TypeError("Illegal invocation");
      }
      cancelTimer(timer);
    });
    const hook = renderHook("题目已更新。", schedule, cancel);

    expect(schedule).toHaveBeenCalledWith(expect.any(Function), 3800);
    expect(() => hook.cleanup()).not.toThrow();
    expect(cancel).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("cancels the previous message timer before starting its replacement", () => {
    const previous = renderHook("题目已更新。");
    vi.advanceTimersByTime(2000);
    previous.cleanup();
    const replacement = renderHook("题干和选项已复制。");

    expect(vi.getTimerCount()).toBe(1);
    vi.advanceTimersByTime(1800);
    expect(previous.setMessage).not.toHaveBeenCalled();
    expect(replacement.setMessage).not.toHaveBeenCalled();
    vi.advanceTimersByTime(2000);
    expect(replacement.setMessage).toHaveBeenCalledExactlyOnceWith(null);
    replacement.cleanup();
    expect(vi.getTimerCount()).toBe(0);
  });
});

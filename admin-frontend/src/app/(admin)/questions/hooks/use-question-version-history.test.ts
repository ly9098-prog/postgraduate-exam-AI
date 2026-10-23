import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { useQuestionVersion, useQuestionVersions } from "./use-question-queries";
import { useQuestionVersionHistory } from "./use-question-version-history";

vi.mock("./use-question-queries", () => ({
  useQuestionVersions: vi.fn(),
  useQuestionVersion: vi.fn(),
}));

const emptyVersions = { items: [], total: 0, total_pages: 1, page: 1, page_size: 100 };

describe("question version history contract", () => {
  function renderHook(questionId: number | null = 1) {
    let result!: ReturnType<typeof useQuestionVersionHistory>;
    function Probe() {
      result = useQuestionVersionHistory(questionId);
      return null;
    }
    renderToStaticMarkup(createElement(Probe));
    return result;
  }

  it("loads all version queries through the feature hook", () => {
    const versions = { data: emptyVersions, isFetching: false };
    const baseDetail = { data: { version: 1 }, isFetching: false };
    const compareDetail = { data: null, isFetching: false };
    vi.mocked(useQuestionVersions).mockReturnValue(versions as never);
    vi.mocked(useQuestionVersion)
      .mockReturnValueOnce(baseDetail as never)
      .mockReturnValueOnce(compareDetail as never);

    const hook = renderHook(1);

    expect(useQuestionVersions).toHaveBeenCalledWith(1);
    expect(useQuestionVersion).toHaveBeenNthCalledWith(1, 1, "current");
    expect(useQuestionVersion).toHaveBeenNthCalledWith(2, 1, null);
    expect(hook.versions).toBe(versions);
    expect(hook.baseVersionDetail).toBe(baseDetail);
    expect(hook.compareVersionDetail).toBe(compareDetail);
    expect(hook.versionHistoryOpen).toBe(false);
    expect(hook.compareVersion).toBeNull();
  });

  it("exposes stable version history handlers", () => {
    vi.mocked(useQuestionVersions).mockReturnValue({ data: undefined, isFetching: false } as never);
    vi.mocked(useQuestionVersion).mockReturnValue({ data: undefined, isFetching: false } as never);
    const hook = renderHook(1);

    expect(hook.toggleVersionHistory).toBeInstanceOf(Function);
    expect(hook.swapVersions).toBeInstanceOf(Function);
    expect(hook.setBaseVersion).toBeInstanceOf(Function);
    expect(hook.setCompareVersion).toBeInstanceOf(Function);
  });
});

import { describe, expect, it } from "vitest";
import type { QuestionVersionDetail } from "@/lib/api/types";
import { buildVersionLabels } from "./question-version-labels";

function makeDetail(version: number | null, isFetching = false) {
  return {
    data: version != null ? { version } as unknown as QuestionVersionDetail : null,
    isFetching,
  };
}

describe("buildVersionLabels", () => {
  it("labels current version", () => {
    const result = buildVersionLabels({
      base: "current", compare: null,
      baseDetail: makeDetail(null), compareDetail: makeDetail(null),
    });
    expect(result.baseVersionLabel).toBe("当前版本");
    expect(result.compareVersionLabel).toBe("请选择版本");
    expect(result.versionComparisonLoading).toBe(false);
    expect(result.pendingVersionLabel).toBeNull();
  });

  it("labels numeric versions with data", () => {
    const result = buildVersionLabels({
      base: 3, compare: 5,
      baseDetail: makeDetail(3), compareDetail: makeDetail(5),
    });
    expect(result.baseVersionLabel).toBe("v3");
    expect(result.compareVersionLabel).toBe("v5");
  });

  it("labels numeric versions without data as pending", () => {
    const result = buildVersionLabels({
      base: 3, compare: 5,
      baseDetail: makeDetail(null), compareDetail: makeDetail(null),
    });
    expect(result.baseVersionLabel).toBe("v3");
    expect(result.compareVersionLabel).toBe("v5");
  });

  it("labels compare as current", () => {
    const result = buildVersionLabels({
      base: 2, compare: "current",
      baseDetail: makeDetail(2), compareDetail: makeDetail(null),
    });
    expect(result.compareVersionLabel).toBe("当前版本");
  });

  it("detects loading state", () => {
    const result = buildVersionLabels({
      base: 2, compare: 3,
      baseDetail: makeDetail(2, true), compareDetail: makeDetail(null, false),
    });
    expect(result.versionComparisonLoading).toBe(true);
    expect(result.pendingVersionLabel).toBe("v2");
  });

  it("detects compare loading state", () => {
    const result = buildVersionLabels({
      base: "current", compare: 4,
      baseDetail: makeDetail(null, false), compareDetail: makeDetail(null, true),
    });
    expect(result.versionComparisonLoading).toBe(true);
    expect(result.pendingVersionLabel).toBe("v4");
  });

  it("returns null pending when not loading", () => {
    const result = buildVersionLabels({
      base: "current", compare: null,
      baseDetail: makeDetail(null, false), compareDetail: makeDetail(null, false),
    });
    expect(result.pendingVersionLabel).toBeNull();
  });
});

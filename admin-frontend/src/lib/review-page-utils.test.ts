import { describe, it, expect } from "vitest";
import {
  unresolvedTableCount,
  textFromContent,
  renderJson,
  statusTone,
  duplicateStatusTone,
  isBlockedByVisualIssues,
  buildVisualBlockReasons,
  selectRollbackBaselineVersion,
  toggleBatchSelection,
  pruneStaleSelections,
} from "./review-page-utils";
import type { OptionVisualModel } from "@/lib/option-visual-utils";

describe("unresolvedTableCount", () => {
  it("returns 0 for null", () => {
    expect(unresolvedTableCount(null)).toBe(0);
  });
  it("returns 0 for non-object", () => {
    expect(unresolvedTableCount("string")).toBe(0);
  });
  it("returns 0 for object without segments", () => {
    expect(unresolvedTableCount({ foo: "bar" })).toBe(0);
  });
  it("returns 0 for segments without tables", () => {
    expect(unresolvedTableCount({ segments: [{ type: "text", content: "hello" }] })).toBe(0);
  });
  it("returns 0 for empty segments array", () => {
    expect(unresolvedTableCount({ segments: [] })).toBe(0);
  });
});

describe("textFromContent", () => {
  it("returns empty for null", () => {
    expect(textFromContent(null)).toBe("");
  });
  it("returns string content directly", () => {
    expect(textFromContent("hello")).toBe("hello");
  });
  it("extracts stem field", () => {
    expect(textFromContent({ stem: "question text" })).toBe("question text");
  });
  it("extracts text field", () => {
    expect(textFromContent({ text: "question text" })).toBe("question text");
  });
  it("falls back to JSON", () => {
    expect(textFromContent({ foo: "bar" })).toBe(JSON.stringify({ foo: "bar" }, null, 2));
  });
});

describe("renderJson", () => {
  it("returns dash for null/undefined/empty", () => {
    expect(renderJson(null)).toBe("—");
    expect(renderJson(undefined)).toBe("—");
    expect(renderJson("")).toBe("—");
  });
  it("returns string as-is", () => {
    expect(renderJson("hello")).toBe("hello");
  });
  it("returns number as string", () => {
    expect(renderJson(42)).toBe("42");
  });
  it("JSON-stringifies objects", () => {
    expect(renderJson({ a: 1 })).toBe('{\n  "a": 1\n}');
  });
});

describe("statusTone", () => {
  it("returns success for approved", () => { expect(statusTone("approved")).toBe("success"); });
  it("returns danger for rejected", () => { expect(statusTone("rejected")).toBe("danger"); });
  it("returns warning for re_pending", () => { expect(statusTone("re_pending")).toBe("warning"); });
  it("returns primary for unknown", () => { expect(statusTone("draft")).toBe("primary"); });
});

describe("duplicateStatusTone", () => {
  it("returns warning for possible_duplicate", () => { expect(duplicateStatusTone("possible_duplicate")).toBe("warning"); });
  it("returns success for normal", () => { expect(duplicateStatusTone("normal")).toBe("success"); });
  it("returns neutral for null", () => { expect(duplicateStatusTone(null)).toBe("neutral"); });
  it("returns neutral for undefined", () => { expect(duplicateStatusTone(undefined)).toBe("neutral"); });
});

const baseModel: OptionVisualModel = {
  mode: "none",
  optionImages: {},
  placeholderKeys: [],
  missingImageKeys: [],
  hasValidVisual: false,
  expectedOptionKeys: [],
  detectedOptionKeys: [],
  consumedSegmentIds: [],
  legacy: false,
  issues: [],
};

describe("isBlockedByVisualIssues", () => {
  it("false when all clear", () => {
    expect(isBlockedByVisualIssues(baseModel, 0, [])).toBe(false);
  });
  it("true for placeholder_missing mode", () => {
    expect(isBlockedByVisualIssues({ ...baseModel, mode: "placeholder_missing" }, 0, [])).toBe(true);
  });
  it("true for unknown_visual mode", () => {
    expect(isBlockedByVisualIssues({ ...baseModel, mode: "unknown_visual" }, 0, [])).toBe(true);
  });
  it("true when legacy and issues exist", () => {
    expect(isBlockedByVisualIssues({ ...baseModel, legacy: true, issues: ["x"] }, 0, [])).toBe(true);
  });
  it("false when legacy but no issues", () => {
    expect(isBlockedByVisualIssues({ ...baseModel, legacy: true, issues: [] }, 0, [])).toBe(false);
  });
  it("true when unresolved tables exist", () => {
    expect(isBlockedByVisualIssues(baseModel, 1, [])).toBe(true);
  });
  it("true when runtime issues exist", () => {
    expect(isBlockedByVisualIssues(baseModel, 0, ["error"])).toBe(true);
  });
});

describe("buildVisualBlockReasons", () => {
  it("returns null when not blocked", () => {
    expect(buildVisualBlockReasons(baseModel, 0, [])).toBeNull();
  });
  it("includes placeholder reason", () => {
    const r = buildVisualBlockReasons({ ...baseModel, mode: "placeholder_missing" }, 0, []);
    expect(r).toEqual(["选项图片缺失"]);
  });
  it("includes unknown_visual reason", () => {
    const r = buildVisualBlockReasons({ ...baseModel, mode: "unknown_visual" }, 0, []);
    expect(r).toEqual(["选项状态未知，需人工确认"]);
  });
  it("includes table count reason", () => {
    const r = buildVisualBlockReasons(baseModel, 3, []);
    expect(r).toEqual(["3 个结构化表格尚未人工核验"]);
  });
  it("includes runtime issues", () => {
    const r = buildVisualBlockReasons(baseModel, 0, ["图片加载失败"]);
    expect(r).toEqual(["图片加载失败"]);
  });
  it("combines multiple reasons in order", () => {
    const r = buildVisualBlockReasons(
      { ...baseModel, mode: "placeholder_missing" },
      2,
      ["运行时错误"],
    );
    expect(r).toEqual(["选项图片缺失", "2 个结构化表格尚未人工核验", "运行时错误"]);
  });
  it("returns null for legacy without issues", () => {
    expect(buildVisualBlockReasons({ ...baseModel, legacy: true, issues: [] }, 0, [])).toBeNull();
  });
});

describe("selectRollbackBaselineVersion", () => {
  it("returns undefined for undefined versions", () => {
    expect(selectRollbackBaselineVersion(undefined)).toBeUndefined();
  });
  it("returns undefined when only one version exists (current only)", () => {
    expect(selectRollbackBaselineVersion([{ version: 3 }])).toBeUndefined();
  });
  it("returns the second version as the baseline (desc order)", () => {
    // versions endpoint returns DESC: [v3 (current), v2 (previous), v1 ...]
    expect(selectRollbackBaselineVersion([{ version: 3 }, { version: 2 }, { version: 1 }])).toBe(2);
  });
  it("does not return the first (current) version", () => {
    expect(selectRollbackBaselineVersion([{ version: 5 }, { version: 4 }])).not.toBe(5);
  });
});

describe("toggleBatchSelection", () => {
  it("adds an id when checked", () => {
    expect(toggleBatchSelection([1, 2], 3, true)).toEqual([1, 2, 3]);
  });
  it("removes an id when unchecked", () => {
    expect(toggleBatchSelection([1, 2, 3], 2, false)).toEqual([1, 3]);
  });
  it("does not add when already at cap", () => {
    const full = Array.from({ length: 50 }, (_, i) => i + 1);
    expect(toggleBatchSelection(full, 999, true)).toBe(full);
  });
  it("does not duplicate when already selected", () => {
    expect(toggleBatchSelection([1, 2], 1, true)).toEqual([1, 2, 1]);
  });
  it("respects custom maxSelection", () => {
    expect(toggleBatchSelection([1, 2], 3, true, 2)).toEqual([1, 2]);
  });
  it("allows unchecking even when at cap", () => {
    const full = Array.from({ length: 50 }, (_, i) => i + 1);
    const result = toggleBatchSelection(full, 1, false);
    expect(result).toHaveLength(49);
    expect(result).not.toContain(1);
  });
});

describe("pruneStaleSelections", () => {
  it("returns same reference when nothing is stale", () => {
    const current = [1, 2];
    expect(pruneStaleSelections(current, [{ id: 1 }, { id: 2 }])).toBe(current);
  });
  it("removes ids not in visible items", () => {
    expect(pruneStaleSelections([1, 2, 3], [{ id: 1 }, { id: 3 }])).toEqual([1, 3]);
  });
  it("returns same reference when visible items is empty", () => {
    const current = [1, 2];
    expect(pruneStaleSelections(current, [])).toBe(current);
  });
  it("returns empty when no selections are visible", () => {
    expect(pruneStaleSelections([1, 2], [{ id: 3 }, { id: 4 }])).toEqual([]);
  });
});

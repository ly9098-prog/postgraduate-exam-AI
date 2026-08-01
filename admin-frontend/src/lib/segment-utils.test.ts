import { describe, it, expect } from "vitest";
import {
  hasVisualSegments,
  hasTableSegments,
  isTableSegmentType,
  isImageSegmentType,
  getSegmentTypeLabel,
  reorderSegmentUp,
  reorderSegmentDown,
  moveSegment,
  deleteSegmentAtIndex,
  updateSegOptionKey,
  updateSegUrl,
  type SegmentData,
} from "./segment-utils";

// ── fixture helpers ──────────────────────────────────────────────────────

function seg(type: string, overrides: Partial<SegmentData> = {}): SegmentData {
  return { type, ...overrides };
}

// ── hasVisualSegments ───────────────────────────────────────────────────

describe("hasVisualSegments", () => {
  it("returns false for null", () => {
    expect(hasVisualSegments(null)).toBe(false);
  });

  it("returns false for undefined", () => {
    expect(hasVisualSegments(undefined)).toBe(false);
  });

  it("returns false for empty array", () => {
    expect(hasVisualSegments([])).toBe(false);
  });

  it("returns false when only non-visual segments exist", () => {
    expect(hasVisualSegments([seg("text"), seg("newline")])).toBe(false);
  });

  it("returns true when image-type segment exists", () => {
    expect(hasVisualSegments([seg("math_image")])).toBe(true);
  });

  it("detects all image segment types", () => {
    expect(hasVisualSegments([seg("image")])).toBe(true);
    expect(hasVisualSegments([seg("table_image")])).toBe(true);
    expect(hasVisualSegments([seg("code_image")])).toBe(true);
  });

  it("is case-insensitive", () => {
    expect(hasVisualSegments([seg("Math_Image")])).toBe(true);
    expect(hasVisualSegments([seg("IMAGE")])).toBe(true);
  });

  it("returns true when visual segment is among other types", () => {
    expect(hasVisualSegments([seg("text"), seg("newline"), seg("image")])).toBe(true);
  });
});

// ── isImageSegmentType ──────────────────────────────────────────────────

describe("isImageSegmentType", () => {
  it("recognizes image", () => {
    expect(isImageSegmentType("image")).toBe(true);
  });

  it("recognizes math_image", () => {
    expect(isImageSegmentType("math_image")).toBe(true);
  });

  it("recognizes table_image", () => {
    expect(isImageSegmentType("table_image")).toBe(true);
  });

  it("recognizes code_image", () => {
    expect(isImageSegmentType("code_image")).toBe(true);
  });

  it("is case-insensitive", () => {
    expect(isImageSegmentType("Math_Image")).toBe(true);
    expect(isImageSegmentType("CODE_IMAGE")).toBe(true);
  });

  it("rejects text", () => {
    expect(isImageSegmentType("text")).toBe(false);
  });

  it("rejects newline", () => {
    expect(isImageSegmentType("newline")).toBe(false);
  });

  it("rejects empty string", () => {
    expect(isImageSegmentType("")).toBe(false);
  });

  it("rejects unknown types", () => {
    expect(isImageSegmentType("table_markdown")).toBe(false);
    expect(isImageSegmentType("source_region")).toBe(false);
  });
});

// ── table segment helpers ────────────────────────────────────────────────

describe("table segment helpers", () => {
  it("recognizes canonical and legacy table segments", () => {
    expect(isTableSegmentType("table")).toBe(true);
    expect(isTableSegmentType("TABLE_MARKDOWN")).toBe(true);
    expect(isTableSegmentType("table_image")).toBe(false);
  });

  it("detects table segments in mixed content", () => {
    expect(hasTableSegments([seg("text"), seg("table")])).toBe(true);
    expect(hasTableSegments([seg("text"), seg("table_image")])).toBe(false);
  });
});

// ── getSegmentTypeLabel ─────────────────────────────────────────────────

describe("getSegmentTypeLabel", () => {
  it('returns "公式" for math_image', () => {
    expect(getSegmentTypeLabel("math_image")).toBe("公式");
  });

  it('returns "表格" for table_image', () => {
    expect(getSegmentTypeLabel("table_image")).toBe("表格");
  });

  it('returns "代码" for code_image', () => {
    expect(getSegmentTypeLabel("code_image")).toBe("代码");
  });

  it('returns "换行" for newline', () => {
    expect(getSegmentTypeLabel("newline")).toBe("换行");
  });

  it('returns "图片" for image', () => {
    expect(getSegmentTypeLabel("image")).toBe("图片");
  });

  it("is case-insensitive", () => {
    expect(getSegmentTypeLabel("Math_Image")).toBe("公式");
  });

  it("labels canonical and legacy table segments", () => {
    expect(getSegmentTypeLabel("table")).toBe("结构化表格");
    expect(getSegmentTypeLabel("table_markdown")).toBe("结构化表格");
  });

  it("returns the type as-is for unknown types", () => {
    expect(getSegmentTypeLabel("unknown")).toBe("unknown");
  });
});

// ── reorderSegmentUp ────────────────────────────────────────────────────

describe("reorderSegmentUp", () => {
  const segs = [seg("a"), seg("b"), seg("c")];

  it("swaps with previous element when index > 0", () => {
    const result = reorderSegmentUp(segs, 1);
    expect(result).toEqual([seg("b"), seg("a"), seg("c")]);
  });

  it("does not move the first element (index 0)", () => {
    const result = reorderSegmentUp(segs, 0);
    expect(result).toEqual(segs);
  });

  it("handles last element correctly", () => {
    const result = reorderSegmentUp(segs, 2);
    expect(result).toEqual([seg("a"), seg("c"), seg("b")]);
  });

  it("does not mutate the original array", () => {
    const copy = [...segs];
    reorderSegmentUp(segs, 1);
    expect(segs).toEqual(copy);
  });

  it("returns new array even when no-op", () => {
    const result = reorderSegmentUp(segs, 0);
    expect(result).not.toBe(segs);
  });
});

// ── reorderSegmentDown ──────────────────────────────────────────────────

describe("reorderSegmentDown", () => {
  const segs = [seg("a"), seg("b"), seg("c")];

  it("swaps with next element when index < last", () => {
    const result = reorderSegmentDown(segs, 1);
    expect(result).toEqual([seg("a"), seg("c"), seg("b")]);
  });

  it("does not move the last element", () => {
    const result = reorderSegmentDown(segs, 2);
    expect(result).toEqual(segs);
  });

  it("handles first element correctly", () => {
    const result = reorderSegmentDown(segs, 0);
    expect(result).toEqual([seg("b"), seg("a"), seg("c")]);
  });

  it("does not mutate the original array", () => {
    const copy = [...segs];
    reorderSegmentDown(segs, 1);
    expect(segs).toEqual(copy);
  });
});

// ── moveSegment (drag-and-drop) ─────────────────────────────────────────

describe("moveSegment", () => {
  const segs = [seg("a"), seg("b"), seg("c"), seg("d")];

  it("moves element to a later position", () => {
    const result = moveSegment(segs, 0, 2);
    expect(result).toEqual([seg("b"), seg("c"), seg("a"), seg("d")]);
  });

  it("moves element to an earlier position", () => {
    const result = moveSegment(segs, 3, 1);
    expect(result).toEqual([seg("a"), seg("d"), seg("b"), seg("c")]);
  });

  it("is a no-op when from === to", () => {
    const result = moveSegment(segs, 1, 1);
    expect(result).toEqual(segs);
  });

  it("returns a new array", () => {
    const result = moveSegment(segs, 0, 2);
    expect(result).not.toBe(segs);
  });

  it("is a no-op when from is out of bounds", () => {
    expect(moveSegment(segs, -1, 1)).toEqual(segs);
    expect(moveSegment(segs, 10, 1)).toEqual(segs);
  });

  it("is a no-op when to is out of bounds", () => {
    expect(moveSegment(segs, 1, -1)).toEqual(segs);
    expect(moveSegment(segs, 1, 10)).toEqual(segs);
  });

  it("handles single-element array", () => {
    const single = [seg("a")];
    expect(moveSegment(single, 0, 0)).toEqual(single);
  });

  it("moves to the very end", () => {
    const result = moveSegment(segs, 0, 3);
    expect(result).toEqual([seg("b"), seg("c"), seg("d"), seg("a")]);
  });

  it("moves to the very beginning", () => {
    const result = moveSegment(segs, 3, 0);
    expect(result).toEqual([seg("d"), seg("a"), seg("b"), seg("c")]);
  });
});

// ── deleteSegmentAtIndex ────────────────────────────────────────────────

describe("deleteSegmentAtIndex", () => {
  const segs = [seg("a"), seg("b"), seg("c")];

  it("removes the middle element", () => {
    expect(deleteSegmentAtIndex(segs, 1)).toEqual([seg("a"), seg("c")]);
  });

  it("removes the first element", () => {
    expect(deleteSegmentAtIndex(segs, 0)).toEqual([seg("b"), seg("c")]);
  });

  it("removes the last element", () => {
    expect(deleteSegmentAtIndex(segs, 2)).toEqual([seg("a"), seg("b")]);
  });

  it("returns empty array when removing the only element", () => {
    expect(deleteSegmentAtIndex([seg("a")], 0)).toEqual([]);
  });

  it("does not mutate the original array", () => {
    const copy = [...segs];
    deleteSegmentAtIndex(segs, 0);
    expect(segs).toEqual(copy);
  });

  it("removes the correct element when multiple same types exist", () => {
    const items = [seg("x"), seg("y"), seg("x")];
    const result = deleteSegmentAtIndex(items, 0);
    expect(result).toEqual([seg("y"), seg("x")]);
  });
});

// ── updateSegOptionKey ──────────────────────────────────────────────────

describe("updateSegOptionKey", () => {
  const segs: SegmentData[] = [
    seg("image", { option_key: "A", assignment_method: "auto" }),
    seg("math_image", { option_key: undefined }),
  ];

  it("updates option_key to a new value", () => {
    const result = updateSegOptionKey(segs, 0, "B");
    expect(result[0].option_key).toBe("B");
  });

  it("sets assignment_method to manual_review when key changes", () => {
    const result = updateSegOptionKey(segs, 0, "B");
    expect(result[0].assignment_method).toBe("manual_review");
  });

  it("clears option_key when val is empty", () => {
    const result = updateSegOptionKey(segs, 0, "");
    expect(result[0].option_key).toBeUndefined();
  });

  it("keeps assignment_method unchanged when option_key stays the same", () => {
    const result = updateSegOptionKey(segs, 0, "A");
    expect(result[0].assignment_method).toBe("auto");
  });

  it("does not affect other segments", () => {
    const result = updateSegOptionKey(segs, 0, "B");
    expect(result[1].option_key).toBeUndefined();
    expect(result[1].type).toBe("math_image");
  });

  it("does not mutate the original array", () => {
    const copy = segs.map((s) => ({ ...s }));
    updateSegOptionKey(segs, 0, "B");
    expect(segs[0].option_key).toBe("A");
    expect(segs[0].assignment_method).toBe("auto");
  });

  it("handles setting option_key on a segment that had none", () => {
    const result = updateSegOptionKey(segs, 1, "B");
    expect(result[1].option_key).toBe("B");
    expect(result[1].assignment_method).toBe("manual_review");
  });
});

// ── updateSegUrl ────────────────────────────────────────────────────────

describe("updateSegUrl", () => {
  const segs: SegmentData[] = [
    seg("image", { url: "http://old.url/img.png", assignment_method: "auto" }),
    seg("text", { text: "hello" }),
  ];

  it("updates the URL at the given index", () => {
    const result = updateSegUrl(segs, 0, "http://new.url/img2.png");
    expect(result[0].url).toBe("http://new.url/img2.png");
  });

  it("sets assignment_method to manual_review", () => {
    const result = updateSegUrl(segs, 0, "http://new.url/img2.png");
    expect(result[0].assignment_method).toBe("manual_review");
  });

  it("does not affect other segments", () => {
    const result = updateSegUrl(segs, 0, "http://new.url/img2.png");
    expect(result[1].text).toBe("hello");
  });

  it("does not mutate the original array", () => {
    const copy = segs.map((s) => ({ ...s }));
    updateSegUrl(segs, 0, "http://new.url/img2.png");
    expect(segs[0].url).toBe("http://old.url/img.png");
    expect(segs[0].assignment_method).toBe("auto");
  });
});

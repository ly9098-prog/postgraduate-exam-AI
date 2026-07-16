import { describe, it, expect } from "vitest";
import {
  isImageOptionPlaceholder,
  extractOptionVisualModel,
  normalizeOptionTextForDisplay,
} from "./option-visual-utils";

// ─── isImageOptionPlaceholder ────────────────────────────────────

describe("isImageOptionPlaceholder", () => {
  it("detects [图片选项A]", () => {
    expect(isImageOptionPlaceholder("[图片选项A]")).toBe(true);
  });

  it("detects [图片选项A，原题图已内嵌]", () => {
    expect(isImageOptionPlaceholder("[图片选项A，原题图已内嵌]")).toBe(true);
  });

  it("detects [图片选项B,原题图已内嵌]", () => {
    expect(isImageOptionPlaceholder("[图片选项B,原题图已内嵌]")).toBe(true);
  });

  it("detects bare 图片选项C", () => {
    expect(isImageOptionPlaceholder("图片选项C，原题图已内嵌")).toBe(true);
  });

  it("detects [图形选项D]", () => {
    expect(isImageOptionPlaceholder("[图形选项D]")).toBe(true);
  });

  it("detects 见原图", () => {
    expect(isImageOptionPlaceholder("见原图")).toBe(true);
  });

  it("detects 图略", () => {
    expect(isImageOptionPlaceholder("图略")).toBe(true);
  });

  it("detects 【图片选项B】", () => {
    expect(isImageOptionPlaceholder("【图片选项B】")).toBe(true);
  });

  it("detects option image placeholder (English)", () => {
    expect(isImageOptionPlaceholder("option image placeholder A")).toBe(true);
  });

  it("returns false for normal text options", () => {
    expect(isImageOptionPlaceholder("A. 42")).toBe(false);
    expect(isImageOptionPlaceholder("O(log n)")).toBe(false);
    expect(isImageOptionPlaceholder("Ⅰ、Ⅱ、Ⅲ")).toBe(false);
  });

  it("returns false for empty/null/undefined", () => {
    expect(isImageOptionPlaceholder("")).toBe(false);
    expect(isImageOptionPlaceholder(null)).toBe(false);
    expect(isImageOptionPlaceholder(undefined)).toBe(false);
    expect(isImageOptionPlaceholder(42)).toBe(false);
  });
});

// ─── normalizeOptionTextForDisplay ───────────────────────────────

describe("normalizeOptionTextForDisplay", () => {
  it("returns empty for placeholder text", () => {
    expect(normalizeOptionTextForDisplay("[图片选项A]")).toBe("");
    expect(normalizeOptionTextForDisplay("图片选项B，原题图已内嵌")).toBe("");
  });

  it("returns empty for null/undefined/empty", () => {
    expect(normalizeOptionTextForDisplay(null)).toBe("");
    expect(normalizeOptionTextForDisplay(undefined)).toBe("");
    expect(normalizeOptionTextForDisplay("")).toBe("");
  });

  it("returns normal text as-is", () => {
    expect(normalizeOptionTextForDisplay("42")).toBe("42");
    expect(normalizeOptionTextForDisplay("O(log n)")).toBe("O(log n)");
  });
});

// ─── extractOptionVisualModel ────────────────────────────────────

function pc(segments: Record<string, unknown>[]): Record<string, unknown> {
  return { segments };
}

const EMPTY: Record<string, unknown> = {};

describe("extractOptionVisualModel", () => {
  // ── 1. option_images from parsed_options segments ──
  it("detects option_images from rich parsed_options segments", () => {
    const result = extractOptionVisualModel(EMPTY, {
      A: { text: "", segments: [{ type: "image", url: "/img/a.png", option_key: "A" }] },
      B: { text: "", segments: [{ type: "image", url: "/img/b.png", option_key: "B" }] },
    });
    expect(result.mode).toBe("option_images");
    expect(result.hasValidVisual).toBe(true);
    expect(result.optionImages["A"]).toHaveLength(1);
    expect(result.optionImages["B"]).toHaveLength(1);
    expect(result.expectedOptionKeys).toContain("A");
    expect(result.expectedOptionKeys).toContain("B");
  });

  // ── 2. option_images from parsed_content.segments with option_key ──
  it("detects option_images from parsed_content segments with option_key", () => {
    const result = extractOptionVisualModel(
      pc([
        { type: "image", url: "/img/a.png", option_key: "A" },
        { type: "image", url: "/img/b.png", option_key: "B" },
        { type: "text", text: "stem" },
      ]),
      { A: "", B: "" },
    );
    expect(result.mode).toBe("option_images");
    expect(result.hasValidVisual).toBe(true);
    expect(result.optionImages["A"]).toHaveLength(1);
    expect(result.consumedSegmentIds).toHaveLength(2);
  });

  // ── 3. option_group with explicit region_type ──
  it("detects option_group with explicit region_type", () => {
    const result = extractOptionVisualModel(
      pc([
        {
          type: "image",
          url: "/img/group.png",
          region_type: "option_group",
          region_id: "q229_option_group",
          expected_option_count: 4,
          detected_option_count: 4,
          placement: "before_options",
          semantic_role: "content_image",
        },
      ]),
      { A: "", B: "", C: "", D: "" },
    );
    expect(result.mode).toBe("option_group");
    expect(result.hasValidVisual).toBe(true);
    expect(result.groupImage).toBeDefined();
    expect(result.groupImage!.url).toBe("/img/group.png");
    expect(result.consumedSegmentIds).toContain("q229_option_group");
    expect(result.legacy).toBe(false);
    expect(result.issues).toHaveLength(0);
  });

  it("reports issues for option_group with missing counts", () => {
    const result = extractOptionVisualModel(
      pc([
        {
          type: "image",
          url: "/img/group.png",
          region_type: "option_group",
          expected_option_count: 0,
          detected_option_count: 0,
        },
      ]),
      { A: "", B: "", C: "", D: "" },
    );
    expect(result.mode).toBe("option_group");
    expect(result.issues.length).toBeGreaterThan(0);
    expect(result.issues.some((i) => i.includes("invalid counts"))).toBe(true);
  });

  // ── 4. Legacy fallback (region_id contains "option_group") ──
  it("detects legacy option_group from region_id fallback", () => {
    const result = extractOptionVisualModel(
      pc([
        {
          type: "image",
          url: "/img/legacy.png",
          region_id: "q369_option_group",
          expected_option_count: 4,
          detected_option_count: 4,
          semantic_role: "content_image",
        },
      ]),
      { A: "", B: "", C: "", D: "" },
    );
    expect(result.mode).toBe("option_group");
    expect(result.legacy).toBe(true);
    expect(result.groupImage?.requiresReview).toBe(true);
    expect(result.issues.some((i) => i.includes("legacy_region_type_fallback"))).toBe(true);
  });

  // ── 5. Strict Plan B heuristic ──
  it("detects legacy option_group via strict Plan B heuristic", () => {
    const result = extractOptionVisualModel(
      pc([
        {
          type: "image",
          url: "/img/content.png",
          semantic_role: "content_image",
          region_type: "diagram",
          expected_option_count: 4,
          detected_option_count: 4,
          placement: "before_options",
        },
      ]),
      { A: "", B: "", C: "", D: "" },
    );
    expect(result.mode).toBe("option_group");
    expect(result.legacy).toBe(true);
    expect(result.issues.some((i) => i.includes("legacy_plan_b_heuristic"))).toBe(true);
  });

  it("returns unknown_visual when Plan B heuristic criteria not met", () => {
    const result = extractOptionVisualModel(
      pc([
        {
          type: "image",
          url: "/img/content.png",
          semantic_role: "content_image",
          expected_option_count: 0,
          detected_option_count: 0,
          placement: "",
        },
      ]),
      { A: "", B: "", C: "", D: "" },
    );
    expect(result.mode).toBe("unknown_visual");
    expect(result.legacy).toBe(true);
    expect(result.issues.length).toBeGreaterThan(0);
  });

  // ── 6. placeholder_missing ──
  it("detects placeholder_missing from parsed_options text", () => {
    const result = extractOptionVisualModel(EMPTY, {
      A: "[图片选项A，原题图已内嵌]",
      B: "[图片选项B，原题图已内嵌]",
      C: "正常文本",
      D: "",
    });
    expect(result.mode).toBe("placeholder_missing");
    expect(result.placeholderKeys).toContain("A");
    expect(result.placeholderKeys).toContain("B");
    expect(result.missingImageKeys).toContain("A");
    expect(result.hasValidVisual).toBe(false);
  });

  // ── 7. none (normal text options) ──
  it("returns none for normal text options", () => {
    const result = extractOptionVisualModel(EMPTY, {
      A: "O(log n)",
      B: "O(n)",
    });
    expect(result.mode).toBe("none");
    expect(result.hasValidVisual).toBe(false);
    expect(result.issues).toHaveLength(0);
  });

  // ── 8. null/undefined inputs ──
  it("handles null/undefined inputs gracefully", () => {
    const result1 = extractOptionVisualModel(null, null);
    expect(result1.mode).toBe("none");

    const result2 = extractOptionVisualModel(undefined, undefined);
    expect(result2.mode).toBe("none");

    const result3 = extractOptionVisualModel(null, { A: "text" });
    expect(result3.mode).toBe("none");
  });

  // ── 9. consumedSegmentIds deduplication ──
  it("deduplicates consumedSegmentIds when same region_id appears", () => {
    const result = extractOptionVisualModel(
      pc([
        { type: "image", url: "/img/a.png", region_id: "dup", option_key: "A" },
        { type: "image", url: "/img/b.png", region_id: "dup", option_key: "B" },
      ]),
      { A: "", B: "" },
    );
    expect(result.mode).toBe("option_images");
    // Same region_id → only 1 unique consumedSegmentId
    expect(result.consumedSegmentIds.filter((id) => id === "dup")).toHaveLength(1);
  });

  // ── 10. Backfill region_type bug reproduction ──
  it("handles the exact backfill bug case (region_type=q369_option_group)", () => {
    // This is what the backfill currently produces: region_type gets the value of region_id
    const result = extractOptionVisualModel(
      pc([
        {
          type: "image",
          url: "/img/q369.png",
          region_type: "q369_option_group",
          region_id: "q369_option_group",
          expected_option_count: 4,
          detected_option_count: 4,
          placement: "before_options",
          semantic_role: "content_image",
        },
      ]),
      { A: "", B: "", C: "", D: "" },
    );
    // Should detect via legacy fallback (region_id contains "option_group")
    // since region_type !== "option_group"
    expect(result.mode).toBe("option_group");
    expect(result.legacy).toBe(true);
    expect(result.groupImage?.requiresReview).toBe(true);
  });

  // ── 11. Existing option_group (q369 reference) consumes segment ──
  it("consumes segments for option_group display", () => {
    const result = extractOptionVisualModel(
      pc([
        { type: "text", text: "stem" },
        {
          type: "image",
          url: "/img/group.png",
          region_type: "option_group",
          region_id: "q369_option_group",
          expected_option_count: 4,
          detected_option_count: 4,
          placement: "before_options",
          semantic_role: "content_image",
        },
        { type: "image", url: "/img/other.png", semantic_role: "illustration" },
      ]),
      { A: "", B: "", C: "", D: "" },
    );
    expect(result.mode).toBe("option_group");
    expect(result.consumedSegmentIds).toContain("q369_option_group");
    // Only the option_group segment is consumed, not the illustration
    expect(result.consumedSegmentIds).toHaveLength(1);
  });
});

import { describe, expect, it } from "vitest";

import { buildQuestionTypeChange } from "./review-question-type-change";

describe("buildQuestionTypeChange", () => {
  it("returns noop when type unchanged", () => {
    const result = buildQuestionTypeChange({
      currentType: "single_choice",
      newCode: "single_choice",
      hasMultiBlankGroups: false,
      confirmed: false,
    });
    expect(result.action).toBe("noop");
  });

  it("clears multi-blank when switching away with groups and confirmed", () => {
    const result = buildQuestionTypeChange({
      currentType: "multi_blank_choice",
      newCode: "single_choice",
      hasMultiBlankGroups: true,
      confirmed: true,
    });
    expect(result.action).toBe("clear_multi_blank");
    if (result.action === "clear_multi_blank") {
      expect(result.nextState.question_type).toBe("single_choice");
      expect(result.nextState.multiBlank).toBeUndefined();
      expect(result.nextState.options).toEqual([]);
    }
  });

  it("returns noop when switching away with groups but not confirmed", () => {
    const result = buildQuestionTypeChange({
      currentType: "multi_blank_choice",
      newCode: "single_choice",
      hasMultiBlankGroups: true,
      confirmed: false,
    });
    expect(result.action).toBe("noop");
  });

  it("updates type when switching between multi-blank types", () => {
    const result = buildQuestionTypeChange({
      currentType: "multi_blank_choice",
      newCode: "multi_blank_multiple_choice",
      hasMultiBlankGroups: true,
      confirmed: false,
    });
    expect(result.action).toBe("update_type");
  });

  it("initializes multi-blank when switching to multi-blank from non-multi-blank", () => {
    const result = buildQuestionTypeChange({
      currentType: "single_choice",
      newCode: "multi_blank_choice",
      hasMultiBlankGroups: false,
      confirmed: false,
    });
    expect(result.action).toBe("init_multi_blank");
    if (result.action === "init_multi_blank") {
      expect(result.nextState.multiBlank.groups).toEqual([]);
      expect(result.nextState.multiBlank.usesSharedOptions).toBe(false);
    }
  });

  it("updates type for plain non-multi-blank switch", () => {
    const result = buildQuestionTypeChange({
      currentType: "single_choice",
      newCode: "multiple_choice",
      hasMultiBlankGroups: false,
      confirmed: false,
    });
    expect(result.action).toBe("update_type");
  });

  it("clears without confirm when no groups exist", () => {
    const result = buildQuestionTypeChange({
      currentType: "multi_blank_choice",
      newCode: "single_choice",
      hasMultiBlankGroups: false,
      confirmed: false,
    });
    expect(result.action).toBe("update_type");
  });
});

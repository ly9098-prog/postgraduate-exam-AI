import { describe, it, expect } from "vitest";
import {
  getQuestionTypeLabel,
  getQuestionTypeShortLabel,
  formatUnknownType,
  isValidQuestionType,
  QUESTION_TYPE_OPTIONS,
  QUESTION_TYPE_LABELS,
  QUESTION_TYPE_SHORT_LABELS,
  QUESTION_TYPE_CODES,
  type QuestionTypeCode,
} from "./question-types";

// ── Canonical codes → labels ──

describe("QUESTION_TYPE_LABELS", () => {
  it("contains all 7 canonical types", () => {
    const codes: QuestionTypeCode[] = [
      "single_choice",
      "multiple_choice",
      "true_false",
      "fill_blank",
      "multi_blank_choice",
      "multi_blank_multiple_choice",
      "subjective",
    ];
    for (const code of codes) {
      expect(QUESTION_TYPE_LABELS[code]).toBeTruthy();
    }
  });

  it("single_choice → 单选题", () => {
    expect(QUESTION_TYPE_LABELS.single_choice).toBe("单选题");
  });

  it("multiple_choice → 多选题", () => {
    expect(QUESTION_TYPE_LABELS.multiple_choice).toBe("多选题");
  });

  it("true_false → 判断题", () => {
    expect(QUESTION_TYPE_LABELS.true_false).toBe("判断题");
  });

  it("fill_blank → 填空题", () => {
    expect(QUESTION_TYPE_LABELS.fill_blank).toBe("填空题");
  });

  it("multi_blank_choice → 多空（单选）选择题", () => {
    expect(QUESTION_TYPE_LABELS.multi_blank_choice).toBe("多空（单选）选择题");
  });

  it("multi_blank_multiple_choice → 多空（多选）选择题", () => {
    expect(QUESTION_TYPE_LABELS.multi_blank_multiple_choice).toBe("多空（多选）选择题");
  });

  it("subjective → 问答题", () => {
    expect(QUESTION_TYPE_LABELS.subjective).toBe("问答题");
  });
});

// ── getQuestionTypeLabel ──

describe("getQuestionTypeLabel", () => {
  it("returns label for canonical code", () => {
    expect(getQuestionTypeLabel("single_choice")).toBe("单选题");
    expect(getQuestionTypeLabel("multiple_choice")).toBe("多选题");
  });

  it('returns "未识别" for null/undefined/empty', () => {
    expect(getQuestionTypeLabel(null)).toBe("未识别");
    expect(getQuestionTypeLabel(undefined)).toBe("未识别");
    expect(getQuestionTypeLabel("")).toBe("未识别");
  });

  it('returns "历史未知题型(xxx)" for truly unknown value', () => {
    expect(getQuestionTypeLabel("foobar_type")).toBe("历史未知题型(foobar_type)");
  });
});

// ── QUESTION_TYPE_SHORT_LABELS ──

describe("QUESTION_TYPE_SHORT_LABELS", () => {
  it("single_choice → 单选", () => {
    expect(QUESTION_TYPE_SHORT_LABELS.single_choice).toBe("单选");
  });

  it("multiple_choice → 多选", () => {
    expect(QUESTION_TYPE_SHORT_LABELS.multiple_choice).toBe("多选");
  });

  it("true_false → 判断", () => {
    expect(QUESTION_TYPE_SHORT_LABELS.true_false).toBe("判断");
  });

  it("fill_blank → 填空", () => {
    expect(QUESTION_TYPE_SHORT_LABELS.fill_blank).toBe("填空");
  });

  it("multi_blank_choice → 多空单选", () => {
    expect(QUESTION_TYPE_SHORT_LABELS.multi_blank_choice).toBe("多空单选");
  });

  it("multi_blank_multiple_choice → 多空多选", () => {
    expect(QUESTION_TYPE_SHORT_LABELS.multi_blank_multiple_choice).toBe("多空多选");
  });

  it("subjective → 问答", () => {
    expect(QUESTION_TYPE_SHORT_LABELS.subjective).toBe("问答");
  });
});

// ── getQuestionTypeShortLabel ──

describe("getQuestionTypeShortLabel", () => {
  it("returns short label for canonical code", () => {
    expect(getQuestionTypeShortLabel("single_choice")).toBe("单选");
    expect(getQuestionTypeShortLabel("multiple_choice")).toBe("多选");
    expect(getQuestionTypeShortLabel("true_false")).toBe("判断");
    expect(getQuestionTypeShortLabel("fill_blank")).toBe("填空");
    expect(getQuestionTypeShortLabel("multi_blank_choice")).toBe("多空单选");
    expect(getQuestionTypeShortLabel("multi_blank_multiple_choice")).toBe("多空多选");
    expect(getQuestionTypeShortLabel("subjective")).toBe("问答");
  });

  it('returns "未识别" for null/undefined/empty', () => {
    expect(getQuestionTypeShortLabel(null)).toBe("未识别");
    expect(getQuestionTypeShortLabel(undefined)).toBe("未识别");
    expect(getQuestionTypeShortLabel("")).toBe("未识别");
  });

  it('returns "历史未知题型(xxx)" for truly unknown value', () => {
    expect(getQuestionTypeShortLabel("foobar_type")).toBe("历史未知题型(foobar_type)");
  });
});

// ── formatUnknownType ──

describe("formatUnknownType", () => {
  it("formats unknown type display text", () => {
    expect(formatUnknownType("old_type_v1")).toBe("历史未知题型(old_type_v1)");
  });
});

// ── isValidQuestionType ──

describe("isValidQuestionType", () => {
  it("returns true for canonical codes", () => {
    expect(isValidQuestionType("single_choice")).toBe(true);
    expect(isValidQuestionType("fill_blank")).toBe(true);
  });

  it("returns false for null/undefined/empty", () => {
    expect(isValidQuestionType(null)).toBe(false);
    expect(isValidQuestionType("")).toBe(false);
  });

  it("returns false for unknown values", () => {
    expect(isValidQuestionType("foobar_type")).toBe(false);
  });
});

// ── QUESTION_TYPE_OPTIONS ──

describe("QUESTION_TYPE_OPTIONS", () => {
  it("has exactly 7 options", () => {
    expect(QUESTION_TYPE_OPTIONS).toHaveLength(7);
  });

  it("each option has value and label", () => {
    for (const opt of QUESTION_TYPE_OPTIONS) {
      expect(opt.value).toBeTruthy();
      expect(opt.label).toBeTruthy();
    }
  });

  it("options are in canonical order", () => {
    expect(QUESTION_TYPE_OPTIONS[0].value).toBe("single_choice");
    expect(QUESTION_TYPE_OPTIONS[1].value).toBe("multiple_choice");
    expect(QUESTION_TYPE_OPTIONS[2].value).toBe("true_false");
    expect(QUESTION_TYPE_OPTIONS[3].value).toBe("fill_blank");
    expect(QUESTION_TYPE_OPTIONS[4].value).toBe("multi_blank_choice");
    expect(QUESTION_TYPE_OPTIONS[5].value).toBe("multi_blank_multiple_choice");
    expect(QUESTION_TYPE_OPTIONS[6].value).toBe("subjective");
  });

  it("options match QUESTION_TYPE_CODES order", () => {
    QUESTION_TYPE_OPTIONS.forEach((opt, i) => {
      expect(opt.value).toBe(QUESTION_TYPE_CODES[i]);
    });
  });
});

// ── CustomSelect: payload validation ──

describe("payload code validation", () => {
  it("QUESTION_TYPE_OPTIONS values are canonical codes (not labels)", () => {
    const canonicalCodes = new Set(QUESTION_TYPE_CODES);
    for (const opt of QUESTION_TYPE_OPTIONS) {
      expect(canonicalCodes.has(opt.value as QuestionTypeCode)).toBe(true);
      // Label is Chinese, not code
      expect(opt.label).not.toBe(opt.value);
      expect(opt.label.length).toBeGreaterThan(0);
    }
  });
});

import { describe, expect, it } from "vitest";
import type { ImportQuestionItem } from "@/lib/api/types";
import {
  answersEquivalent,
  completeSuggestionFromItem,
  normalizeAnswerForCompare,
  stringSuggestion,
} from "./review-completion-suggestion";

function item(aiMetadata: Record<string, unknown> | null | undefined): ImportQuestionItem {
  return { ai_metadata: aiMetadata } as ImportQuestionItem;
}

describe("review completion suggestion", () => {
  it("accepts only object suggestions and ignores arrays, primitives and missing metadata", () => {
    const suggestion = { answer: "B" };
    expect(completeSuggestionFromItem(item({ complete_suggestion: suggestion }))).toBe(suggestion);
    expect(completeSuggestionFromItem(item({ complete_suggestion: ["B"] }))).toBeNull();
    expect(completeSuggestionFromItem(item({ complete_suggestion: "B" }))).toBeNull();
    expect(completeSuggestionFromItem(item({}))).toBeNull();
    expect(completeSuggestionFromItem(null)).toBeNull();
  });

  it("returns only trimmed non-empty string suggestions", () => {
    expect(stringSuggestion("  B  ")).toBe("B");
    expect(stringSuggestion("   ")).toBe("");
    expect(stringSuggestion(1)).toBe("");
    expect(stringSuggestion(null)).toBe("");
  });

  it("keeps answer normalization compatible with separators and option order", () => {
    expect(normalizeAnswerForCompare(" c, a ")).toBe("c,,a");
    expect(normalizeAnswerForCompare("CA")).toBe("CA");
    expect(normalizeAnswerForCompare("A， C、B")).toBe("A,B,C");
    expect(normalizeAnswerForCompare(" , A,, B , ")).toBe("A,,,B");
    expect(normalizeAnswerForCompare("选项 A")).toBe("选项,A");
    expect(normalizeAnswerForCompare("")).toBe("");
  });

  it("requires two non-empty normalized answers to be equivalent", () => {
    expect(answersEquivalent("c,a", "A,C")).toBe(true);
    expect(answersEquivalent(" A ", "A")).toBe(true);
    expect(answersEquivalent("A", "")).toBe(false);
    expect(answersEquivalent("", "")).toBe(false);
    expect(answersEquivalent("A", "B")).toBe(false);
    expect(answersEquivalent(undefined, "A")).toBe(false);
  });
});

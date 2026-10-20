import { describe, expect, it } from "vitest";
import { isReviewAnswerSelected, toggleReviewAnswer } from "./review-answer-selection";

describe("review answer selection", () => {
  it("matches only whole multi-choice tokens and retains case-sensitive option keys", () => {
    for (const type of ["multiple_choice", " MULTIPLE-CHOICE "]) {
      expect(isReviewAnswerSelected(type, "A，C D\tE", "C")).toBe(true);
      expect(isReviewAnswerSelected(type, "AB", "A")).toBe(false);
      expect(isReviewAnswerSelected(type, "a,B", "A")).toBe(false);
      expect(isReviewAnswerSelected(type, "", "")).toBe(true);
    }
  });

  it("keeps multi-choice order and duplicates when adding, and removes all matching tokens", () => {
    expect(toggleReviewAnswer("multiple_choice", " C，A A\n", "B")).toBe("C,A,A,B");
    expect(toggleReviewAnswer("multiple_choice", " C，A A\n", "A")).toBe("C");
    expect(toggleReviewAnswer("multiple_choice", "A", "A")).toBe("");
    expect(toggleReviewAnswer("multiple_choice", "", "B")).toBe("B");
    expect(toggleReviewAnswer("multiple_choice", "AC", "A")).toBe("AC,A");
    expect(toggleReviewAnswer("multiple_choice", "a", "A")).toBe("a,A");
  });

  it("preserves exact single-choice matching and unknown-type fallback", () => {
    for (const type of ["single_choice", "unknown", "多选题", ""]) {
      expect(isReviewAnswerSelected(type, "A,B", "A")).toBe(false);
      expect(isReviewAnswerSelected(type, "A", "A")).toBe(true);
      expect(toggleReviewAnswer(type, "A", "A")).toBe("");
      expect(toggleReviewAnswer(type, "A", "B")).toBe("B");
    }
  });
});

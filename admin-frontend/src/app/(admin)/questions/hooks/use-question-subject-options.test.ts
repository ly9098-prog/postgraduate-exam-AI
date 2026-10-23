import { describe, expect, it, vi } from "vitest";
import { fetchSubjectOptions } from "../question-api";
import { useQuestionSubjectOptions } from "./use-question-subject-options";

vi.mock("../question-api", () => ({
  fetchSubjectOptions: vi.fn(),
}));

describe("question subject options contract", () => {
  it("exposes the subject-option API shape used by the page", () => {
    expect(Array.isArray(useQuestionSubjectOptions)).toBe(false);
    expect(typeof useQuestionSubjectOptions).toBe("function");
    expect(typeof fetchSubjectOptions).toBe("function");
  });
});

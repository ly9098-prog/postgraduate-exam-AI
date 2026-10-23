import { describe, expect, it, vi } from "vitest";
import { copyTextToClipboard } from "@/lib/clipboard";
import { buildQuestionCopyText } from "@/lib/question-copy";
import { useQuestionCopy } from "./use-question-copy";

describe("question copy contract", () => {
  it("keeps copy text formatting and clipboard fallback behind existing modules", () => {
    expect(typeof useQuestionCopy).toBe("function");
    expect(typeof copyTextToClipboard).toBe("function");
    expect(typeof buildQuestionCopyText).toBe("function");
    expect(vi.isMockFunction(copyTextToClipboard)).toBe(false);
  });
});

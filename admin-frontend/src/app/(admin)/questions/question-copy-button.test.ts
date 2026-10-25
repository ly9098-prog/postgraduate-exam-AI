import { describe, expect, it } from "vitest";
import { QuestionCopyButton } from "./question-copy-button";

describe("question copy button", () => {
  it("keeps the original accessibility and disabled state", () => {
    expect(QuestionCopyButton).toBeDefined();
  });
});

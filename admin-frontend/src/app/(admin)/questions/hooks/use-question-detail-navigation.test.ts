import { describe, expect, it } from "vitest";
import { resolveQuestionListSelection } from "./use-question-detail-navigation";

describe("resolveQuestionListSelection", () => {
  it("clears an empty settled list", () => {
    expect(resolveQuestionListSelection([], false, 2)).toBeNull();
  });

  it("preserves a valid selected question", () => {
    const items = [{ id: 1 }, { id: 2 }];
    expect(resolveQuestionListSelection(items, false, 2)).toBe(2);
  });

  it("selects the first question when a non-empty list arrives", () => {
    expect(resolveQuestionListSelection([{ id: 7 }, { id: 8 }], false, null)).toBe(7);
  });

  it("keeps a selection while an empty transient list is fetching", () => {
    expect(resolveQuestionListSelection([], true, 7)).toBe(7);
  });

  it("replaces a stale selection after the refreshed list settles", () => {
    const items = [{ id: 9 }];
    expect(resolveQuestionListSelection(items, false, 7)).toBe(9);
  });
});

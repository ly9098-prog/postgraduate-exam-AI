import { describe, expect, it } from "vitest";
import {
  closeQuestionMenu,
  closeQuestionMenus,
  toggleQuestionMenu,
  type QuestionMenus,
} from "./use-question-menus";

const closed: QuestionMenus = {
  isCommonFilterOpen: false,
  isMoreFilterOpen: false,
  isExportOpen: false,
};

describe("question menu state", () => {
  it("opens one menu and closes the others", () => {
    expect(toggleQuestionMenu(closed, "isMoreFilterOpen")).toEqual({
      isCommonFilterOpen: false,
      isMoreFilterOpen: true,
      isExportOpen: false,
    });
  });

  it("closes an open menu and keeps unrelated menus unchanged", () => {
    const current = { ...closed, isExportOpen: true };
    expect(closeQuestionMenu(current, "isExportOpen")).toEqual(closed);
    expect(closeQuestionMenu(current, "isCommonFilterOpen")).toEqual(current);
  });

  it("closes every menu", () => {
    expect(closeQuestionMenus()).toEqual(closed);
  });
});

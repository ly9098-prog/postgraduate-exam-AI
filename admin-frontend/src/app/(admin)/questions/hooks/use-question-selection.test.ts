import { describe, expect, it } from "vitest";
import { toggleAllSelection, toggleSingleSelection } from "@/lib/selection-ops";

describe("question selection operations", () => {
  it("selects all current-page IDs when the page is not fully selected", () => {
    expect(toggleAllSelection([1, 2], false)).toEqual(new Set([1, 2]));
  });

  it("clears the selection when the current page is fully selected", () => {
    expect(toggleAllSelection([1, 2], true)).toEqual(new Set());
  });

  it("toggles a single ID without mutating the previous set", () => {
    const previous = new Set([1]);
    expect(toggleSingleSelection(previous, 2)).toEqual(new Set([1, 2]));
    expect(toggleSingleSelection(previous, 1)).toEqual(new Set());
    expect(previous).toEqual(new Set([1]));
  });
});

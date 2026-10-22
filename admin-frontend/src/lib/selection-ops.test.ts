import { describe, expect, it } from "vitest";
import { toggleAllSelection, toggleSingleSelection } from "./selection-ops";

describe("toggleAllSelection", () => {
  it("selects all when not all checked", () => {
    expect(toggleAllSelection([1, 2, 3], false)).toEqual(new Set([1, 2, 3]));
  });

  it("deselects all when all checked", () => {
    expect(toggleAllSelection([1, 2, 3], true)).toEqual(new Set());
  });

  it("returns empty set for empty items", () => {
    expect(toggleAllSelection([], false)).toEqual(new Set());
    expect(toggleAllSelection([], true)).toEqual(new Set());
  });

  it("works with string IDs", () => {
    expect(toggleAllSelection(["a", "b"], false)).toEqual(new Set(["a", "b"]));
  });
});

describe("toggleSingleSelection", () => {
  it("adds an unselected ID", () => {
    expect(toggleSingleSelection(new Set([1, 2]), 3)).toEqual(new Set([1, 2, 3]));
  });

  it("removes a selected ID", () => {
    expect(toggleSingleSelection(new Set([1, 2, 3]), 2)).toEqual(new Set([1, 3]));
  });

  it("does not mutate the original set", () => {
    const original = new Set([1, 2]);
    const result = toggleSingleSelection(original, 3);
    expect(original).toEqual(new Set([1, 2]));
    expect(result).not.toBe(original);
  });

  it("works with string IDs", () => {
    expect(toggleSingleSelection(new Set(["a"]), "b")).toEqual(new Set(["a", "b"]));
  });
});

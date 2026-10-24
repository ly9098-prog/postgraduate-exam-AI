import { describe, it, expect } from "vitest";
import {
  computePermissionChanges,
  sortCategoryEntries,
  computeTotalPermissionCount,
} from "./role-permission-utils";

describe("computePermissionChanges", () => {
  it("returns zero for identical sets", () => {
    const s = new Set([1, 2, 3]);
    expect(computePermissionChanges(s, s)).toEqual({ added: 0, removed: 0 });
  });
  it("counts added permissions", () => {
    expect(computePermissionChanges(new Set([1]), new Set([1, 2, 3]))).toEqual({ added: 2, removed: 0 });
  });
  it("counts removed permissions", () => {
    expect(computePermissionChanges(new Set([1, 2, 3]), new Set([1]))).toEqual({ added: 0, removed: 2 });
  });
  it("counts mixed changes", () => {
    expect(computePermissionChanges(new Set([1, 2, 3]), new Set([2, 4, 5]))).toEqual({ added: 2, removed: 2 });
  });
  it("handles empty original", () => {
    expect(computePermissionChanges(new Set(), new Set([1, 2]))).toEqual({ added: 2, removed: 0 });
  });
  it("handles empty active", () => {
    expect(computePermissionChanges(new Set([1, 2]), new Set())).toEqual({ added: 0, removed: 2 });
  });
  it("handles both empty", () => {
    expect(computePermissionChanges(new Set(), new Set())).toEqual({ added: 0, removed: 0 });
  });
});

describe("sortCategoryEntries", () => {
  const order = ["users", "questions", "formulas"];
  it("sorts by predefined order", () => {
    const entries: Array<[string, string[]]> = [
      ["formulas", []],
      ["users", []],
      ["questions", []],
    ];
    const out = sortCategoryEntries(entries, order);
    expect(out.map(([k]) => k)).toEqual(["users", "questions", "formulas"]);
  });
  it("places unknown categories after known ones", () => {
    const entries: Array<[string, string[]]> = [
      ["custom", []],
      ["users", []],
      ["formulas", []],
    ];
    const out = sortCategoryEntries(entries, order);
    expect(out[0][0]).toBe("users");
    expect(out[1][0]).toBe("formulas");
    expect(out[2][0]).toBe("custom");
  });
  it("sorts unknown categories alphabetically", () => {
    const entries: Array<[string, string[]]> = [
      ["zebra", []],
      ["alpha", []],
    ];
    const out = sortCategoryEntries(entries, order);
    expect(out[0][0]).toBe("alpha");
    expect(out[1][0]).toBe("zebra");
  });
  it("handles empty entries", () => {
    expect(sortCategoryEntries<string>([] as Array<[string, string[]]>, order)).toEqual([] as Array<[string, string[]]>);
  });
});

describe("computeTotalPermissionCount", () => {
  it("sums items across categories", () => {
    expect(computeTotalPermissionCount<number>([
      ["a", [1, 2, 3]],
      ["b", [1, 2]],
    ])).toBe(5);
  });
  it("handles empty entries", () => {
    expect(computeTotalPermissionCount<number>([])).toBe(0);
  });
  it("handles empty categories", () => {
    expect(computeTotalPermissionCount<number>([["a", []], ["b", []]])).toBe(0);
  });
});

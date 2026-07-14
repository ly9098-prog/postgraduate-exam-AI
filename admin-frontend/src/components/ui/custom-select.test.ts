import { describe, it, expect } from "vitest";
import { getNextEnabledIndex, type SelectOption } from "./custom-select";

const options: SelectOption[] = [
  { value: "a", label: "A" },
  { value: "b", label: "B", disabled: true },
  { value: "c", label: "C" },
  { value: "d", label: "D", disabled: true },
  { value: "e", label: "E" },
];

describe("getNextEnabledIndex", () => {
  it("moves to next enabled option with ArrowDown", () => {
    expect(getNextEnabledIndex(-1, 1, options)).toBe(0); // A
    expect(getNextEnabledIndex(0, 1, options)).toBe(2); // C (skip B)
    expect(getNextEnabledIndex(2, 1, options)).toBe(4); // E (skip D)
  });

  it("wraps around from last to first enabled", () => {
    expect(getNextEnabledIndex(4, 1, options)).toBe(0);
  });

  it("moves to previous enabled option with ArrowUp", () => {
    expect(getNextEnabledIndex(4, -1, options)).toBe(2); // C (skip D)
    expect(getNextEnabledIndex(2, -1, options)).toBe(0); // A (skip B)
  });

  it("wraps around from first to last enabled", () => {
    expect(getNextEnabledIndex(0, -1, options)).toBe(4);
  });

  it("returns -1 for empty list", () => {
    expect(getNextEnabledIndex(-1, 1, [])).toBe(-1);
  });

  it("returns -1 when all disabled", () => {
    const allDisabled = [
      { value: "x", label: "X", disabled: true },
      { value: "y", label: "Y", disabled: true },
    ];
    expect(getNextEnabledIndex(-1, 1, allDisabled)).toBe(-1);
  });

  it("handles single enabled option", () => {
    const single = [
      { value: "a", label: "A" },
      { value: "b", label: "B", disabled: true },
    ];
    expect(getNextEnabledIndex(-1, 1, single)).toBe(0);
    expect(getNextEnabledIndex(0, 1, single)).toBe(0); // wraps to itself
    expect(getNextEnabledIndex(0, -1, single)).toBe(0);
  });

  it("returns first enabled when starting from disabled index", () => {
    // When starting on a disabled item (index 1), ArrowDown goes to the first enabled (index 0)
    expect(getNextEnabledIndex(1, 1, options)).toBe(0);
  });

  it("returns first enabled when going up from disabled index", () => {
    // When starting on a disabled item (index 1), ArrowUp wraps to last enabled (index 4)
    expect(getNextEnabledIndex(1, -1, options)).toBe(4);
  });
});

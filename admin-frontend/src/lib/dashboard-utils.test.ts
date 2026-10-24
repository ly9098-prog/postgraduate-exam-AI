import { describe, it, expect } from "vitest";
import { numberValue, toPieData, normalizeSeries } from "./dashboard-utils";

describe("numberValue", () => {
  it("formats finite number", () => {
    expect(numberValue(1234)).toBe("1,234");
  });
  it("returns -- for NaN", () => {
    expect(numberValue(NaN)).toBe("--");
  });
  it("returns -- for Infinity", () => {
    expect(numberValue(Infinity)).toBe("--");
  });
  it("returns -- for string", () => {
    expect(numberValue("abc")).toBe("--");
  });
  it("returns -- for null", () => {
    expect(numberValue(null)).toBe("--");
  });
  it("returns -- for undefined", () => {
    expect(numberValue(undefined)).toBe("--");
  });
  it("formats 0", () => {
    expect(numberValue(0)).toBe("0");
  });
});

describe("toPieData", () => {
  it("returns empty for undefined", () => {
    expect(toPieData(undefined)).toEqual([]);
  });
  it("passes through array input", () => {
    const input = [{ name: "a", count: 1 }];
    expect(toPieData(input as any)).toEqual(input);
  });
  it("converts object to array", () => {
    const result = toPieData({ a: 1, b: 2 } as any);
    expect(result.length).toBe(2);
    expect(result[0]).toEqual({ name: "a", count: 1 });
  });
});

describe("normalizeSeries", () => {
  it("replaces undefined with 0", () => {
    expect(normalizeSeries([1, undefined, 3])).toEqual([1, 0, 3]);
  });
  it("replaces null with 0", () => {
    expect(normalizeSeries([1, null, 3])).toEqual([1, 0, 3]);
  });
  it("replaces NaN with 0", () => {
    expect(normalizeSeries([1, NaN, 3])).toEqual([1, 0, 3]);
  });
  it("preserves finite numbers", () => {
    expect(normalizeSeries([1, 2, 3])).toEqual([1, 2, 3]);
  });
  it("handles empty array", () => {
    expect(normalizeSeries([])).toEqual([]);
  });
});

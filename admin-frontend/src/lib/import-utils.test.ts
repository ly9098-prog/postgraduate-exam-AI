import { describe, it, expect } from "vitest";
import { parseProgressPercent, validatePageStart, validatePageEnd } from "./import-utils";

// ── parseProgressPercent ────────────────────────────────────────────────

describe("parseProgressPercent", () => {
  it('parses "3/10 pages" → 30', () => {
    expect(parseProgressPercent("3/10 pages")).toBe(30);
  });

  it('parses "3/10 page" (singular) → 30', () => {
    // Backend uses "pages" but test singular form too
    expect(parseProgressPercent("3/10 page")).toBe(30);
  });

  it('parses "30%" → 30', () => {
    expect(parseProgressPercent("30%")).toBe(30);
  });

  it("returns 0 for empty string", () => {
    expect(parseProgressPercent("")).toBe(0);
  });

  it("returns 0 for null", () => {
    expect(parseProgressPercent(null)).toBe(0);
  });

  it("returns 0 for undefined", () => {
    expect(parseProgressPercent(undefined)).toBe(0);
  });

  it("returns 0 for invalid input", () => {
    expect(parseProgressPercent("invalid")).toBe(0);
  });

  it("clamps 300% to 100", () => {
    expect(parseProgressPercent("300%")).toBe(100);
  });

  it('clamps "10/3 pages" to 100', () => {
    // 10/3 = 333% → clamped to 100
    expect(parseProgressPercent("10/3 pages")).toBe(100);
  });

  it('parses "0/10 pages" → 0', () => {
    expect(parseProgressPercent("0/10 pages")).toBe(0);
  });
});

// ── validatePageStart ───────────────────────────────────────────────────

describe("validatePageStart", () => {
  it("accepts empty (no page range)", () => {
    expect(validatePageStart("")).toEqual({ valid: true });
  });

  it("accepts null", () => {
    expect(validatePageStart(null)).toEqual({ valid: true });
  });

  it("accepts undefined", () => {
    expect(validatePageStart(undefined)).toEqual({ valid: true });
  });

  it("accepts positive integer", () => {
    expect(validatePageStart("3")).toEqual({ valid: true });
  });

  it("rejects 0", () => {
    expect(validatePageStart("0")).toEqual({ valid: false, error: expect.any(String) });
  });

  it("rejects negative", () => {
    expect(validatePageStart("-1")).toEqual({ valid: false, error: expect.any(String) });
  });

  it("rejects decimal", () => {
    expect(validatePageStart("2.5")).toEqual({ valid: false, error: expect.any(String) });
  });

  it("rejects non-numeric", () => {
    expect(validatePageStart("abc")).toEqual({ valid: false, error: expect.any(String) });
  });
});

// ── validatePageEnd ─────────────────────────────────────────────────────

describe("validatePageEnd", () => {
  it("accepts empty", () => {
    expect(validatePageEnd("", "1")).toEqual({ valid: true });
  });

  it("accepts positive integer", () => {
    expect(validatePageEnd("5", "1")).toEqual({ valid: true });
  });

  it("rejects 0", () => {
    expect(validatePageEnd("0", "1")).toEqual({ valid: false, error: expect.any(String) });
  });

  it("rejects negative", () => {
    expect(validatePageEnd("-1", "1")).toEqual({ valid: false, error: expect.any(String) });
  });

  it("rejects decimal", () => {
    expect(validatePageEnd("3.7", "1")).toEqual({ valid: false, error: expect.any(String) });
  });

  it("rejects non-numeric", () => {
    expect(validatePageEnd("xyz", "1")).toEqual({ valid: false, error: expect.any(String) });
  });

  it("rejects end < start", () => {
    expect(validatePageEnd("2", "5")).toEqual({ valid: false, error: expect.any(String) });
  });

  it("allows end == start", () => {
    expect(validatePageEnd("3", "3")).toEqual({ valid: true });
  });

  it("allows end > start", () => {
    expect(validatePageEnd("7", "3")).toEqual({ valid: true });
  });

  it("accepts end without start", () => {
    expect(validatePageEnd("3", "")).toEqual({ valid: true });
  });
});

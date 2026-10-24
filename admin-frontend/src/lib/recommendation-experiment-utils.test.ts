import { describe, it, expect } from "vitest";
import { parseExperimentVariants, buildExperimentPayload } from "./recommendation-experiment-utils";

describe("parseExperimentVariants", () => {
  it("parses valid 2-variant array", () => {
    const raw = JSON.stringify([
      { key: "A", strategy: "default", ratio: 0.5 },
      { key: "B", strategy: "scored", ratio: 0.5 },
    ]);
    const r = parseExperimentVariants(raw);
    expect(r.ok).toBe(true);
  });
  it("rejects invalid JSON", () => {
    const r = parseExperimentVariants("{bad}");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.message).toBe("分组 JSON 格式错误");
  });
  it("rejects empty string fallback to [] (needs >= 2)", () => {
    const r = parseExperimentVariants("");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.message).toContain("至少需要 2 个分组");
  });
  it("rejects single variant", () => {
    const r = parseExperimentVariants(JSON.stringify([{ key: "A", strategy: "x", ratio: 1 }]));
    expect(r.ok).toBe(false);
  });
  it("rejects non-array", () => {
    const r = parseExperimentVariants('{"a":1}');
    expect(r.ok).toBe(false);
  });
  it("rejects missing key", () => {
    const r = parseExperimentVariants(JSON.stringify([
      { key: "", strategy: "x", ratio: 0.5 },
      { key: "B", strategy: "y", ratio: 0.5 },
    ]));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.message).toContain("key");
  });
  it("rejects missing strategy", () => {
    const r = parseExperimentVariants(JSON.stringify([
      { key: "A", strategy: "", ratio: 0.5 },
      { key: "B", strategy: "y", ratio: 0.5 },
    ]));
    expect(r.ok).toBe(false);
  });
  it("rejects ratio out of range", () => {
    const r = parseExperimentVariants(JSON.stringify([
      { key: "A", strategy: "x", ratio: 1.5 },
      { key: "B", strategy: "y", ratio: -0.5 },
    ]));
    expect(r.ok).toBe(false);
  });
  it("rejects duplicate keys", () => {
    const r = parseExperimentVariants(JSON.stringify([
      { key: "A", strategy: "x", ratio: 0.5 },
      { key: "A", strategy: "y", ratio: 0.5 },
    ]));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.message).toContain("key 不能重复");
  });
  it("rejects ratio sum != 1", () => {
    const r = parseExperimentVariants(JSON.stringify([
      { key: "A", strategy: "x", ratio: 0.3 },
      { key: "B", strategy: "y", ratio: 0.3 },
    ]));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.message).toContain("0.6000");
  });
  it("accepts ratio sum exactly 1", () => {
    const r = parseExperimentVariants(JSON.stringify([
      { key: "A", strategy: "x", ratio: 0.7 },
      { key: "B", strategy: "y", ratio: 0.3 },
    ]));
    expect(r.ok).toBe(true);
  });
  it("accepts 3+ variants", () => {
    const r = parseExperimentVariants(JSON.stringify([
      { key: "A", strategy: "x", ratio: 0.5 },
      { key: "B", strategy: "y", ratio: 0.3 },
      { key: "C", strategy: "z", ratio: 0.2 },
    ]));
    expect(r.ok).toBe(true);
  });
});

describe("buildExperimentPayload", () => {
  const variants = [
    { key: "A", strategy: "x", ratio: 0.5 },
    { key: "B", strategy: "y", ratio: 0.5 },
  ];
  it("builds payload from valid inputs", () => {
    const p = buildExperimentPayload("test", "practice", variants);
    expect(p).toEqual({ name: "test", scene: "practice", variants, traffic_ratio: 1.0 });
  });
  it("trims name", () => {
    const p = buildExperimentPayload("  spaced  ", "s", variants);
    expect(p?.name).toBe("spaced");
  });
  it("returns null for empty name", () => {
    expect(buildExperimentPayload("", "s", variants)).toBeNull();
  });
  it("returns null for whitespace-only name", () => {
    expect(buildExperimentPayload("   ", "s", variants)).toBeNull();
  });
});

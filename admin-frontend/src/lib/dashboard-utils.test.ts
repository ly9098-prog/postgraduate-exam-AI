import { describe, it, expect } from "vitest";
import {
  numberValue,
  toPieData,
  normalizeSeries,
  computeReviewRate,
  computeQueuePending,
  computeQueueErrors,
  computeRedisStatus,
  computeTaskQueueStatus,
} from "./dashboard-utils";

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
    expect(toPieData(input)).toEqual(input);
  });
  it("converts object to array", () => {
    const result = toPieData({ a: 1, b: 2 } as unknown as Array<{ name: string; count: number }>);
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

describe("computeReviewRate", () => {
  const pie = [
    { name: "approved", count: 10 },
    { name: "published", count: 5 },
    { name: "rejected", count: 5 },
  ];
  it("calculates rate with approved+published", () => {
    expect(computeReviewRate(pie)).toBe("75.0%");
  });
  it("returns -- for empty data", () => {
    expect(computeReviewRate([])).toBe("--");
  });
  it("returns -- when all zero", () => {
    expect(computeReviewRate([{ name: "approved", count: 0 }])).toBe("--");
  });
  it("handles only approved", () => {
    expect(computeReviewRate([{ name: "approved", count: 3 }, { name: "rejected", count: 1 }])).toBe("75.0%");
  });
  it("handles 100%", () => {
    expect(computeReviewRate([{ name: "published", count: 4 }])).toBe("100.0%");
  });
  it("handles 0%", () => {
    expect(computeReviewRate([{ name: "rejected", count: 4 }])).toBe("0.0%");
  });
});

describe("computeQueuePending", () => {
  it("sums ready+processing+retry", () => {
    expect(computeQueuePending({ ready: 1, processing: 2, retry: 3 })).toBe(6);
  });
  it("defaults undefined to 0", () => {
    expect(computeQueuePending({ ready: 5 })).toBe(5);
    expect(computeQueuePending({})).toBe(0);
  });
  it("returns 0 for undefined", () => {
    expect(computeQueuePending(undefined)).toBe(0);
  });
});

describe("computeQueueErrors", () => {
  it("sums dead+corrupt", () => {
    expect(computeQueueErrors({ dead: 1, corrupt: 2 })).toBe(3);
  });
  it("defaults undefined to 0", () => {
    expect(computeQueueErrors({ dead: 5 })).toBe(5);
    expect(computeQueueErrors({})).toBe(0);
  });
  it("returns 0 for undefined", () => {
    expect(computeQueueErrors(undefined)).toBe(0);
  });
});

describe("computeRedisStatus", () => {
  it("returns 检测中 when loading", () => {
    expect(computeRedisStatus(true, undefined)).toEqual({ tone: "muted", label: "检测中" });
  });
  it("returns 未获取 when no data", () => {
    expect(computeRedisStatus(false, undefined)).toEqual({ tone: "muted", label: "未获取" });
  });
  it("returns 未配置 when not configured", () => {
    expect(computeRedisStatus(false, { configured: false })).toEqual({ tone: "muted", label: "未配置" });
  });
  it("returns 正常 when configured and available", () => {
    expect(computeRedisStatus(false, { configured: true, available: true })).toEqual({ tone: "ok", label: "正常" });
  });
  it("returns 不可用 when configured but not available", () => {
    expect(computeRedisStatus(false, { configured: true, available: false })).toEqual({ tone: "error", label: "不可用" });
  });
  it("returns 不可用 when configured but available undefined", () => {
    expect(computeRedisStatus(false, { configured: true })).toEqual({ tone: "error", label: "不可用" });
  });
});

describe("computeTaskQueueStatus", () => {
  it("returns 检测中 when loading", () => {
    expect(computeTaskQueueStatus(true, undefined, 0, 0)).toEqual({ tone: "muted", label: "检测中" });
  });
  it("returns 未获取 when no data", () => {
    expect(computeTaskQueueStatus(false, undefined, 0, 0)).toEqual({ tone: "muted", label: "未获取" });
  });
  it("returns 未启用 when not configured", () => {
    expect(computeTaskQueueStatus(false, { configured: false }, 0, 0)).toEqual({ tone: "muted", label: "未启用" });
  });
  it("returns 异常 when errors > 0", () => {
    expect(computeTaskQueueStatus(false, { configured: true }, 0, 2)).toEqual({ tone: "error", label: "异常 2" });
  });
  it("returns 积压 when pending > 0 and no errors", () => {
    expect(computeTaskQueueStatus(false, { configured: true }, 5, 0)).toEqual({ tone: "warning", label: "积压 5" });
  });
  it("returns 正常 when no errors and no pending", () => {
    expect(computeTaskQueueStatus(false, { configured: true }, 0, 0)).toEqual({ tone: "ok", label: "正常" });
  });
  it("errors take precedence over pending", () => {
    expect(computeTaskQueueStatus(false, { configured: true }, 5, 2)).toEqual({ tone: "error", label: "异常 2" });
  });
});

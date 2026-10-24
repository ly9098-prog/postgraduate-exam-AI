import { describe, it, expect } from "vitest";
import {
  csvEscape,
  buildUserCsvHeader,
  buildUserCsvRow,
  filterBatchActionCandidates,
  noCandidatesMessage,
  type AppUserLike,
} from "./app-user-utils";

const baseUser: AppUserLike = {
  id: 1, nickname: "Test", openid: "abc123",
  is_banned: false, banned_reason: null, banned_at: null, created_at: "2024-01-01T00:00:00Z",
};

describe("csvEscape", () => {
  it("wraps string in quotes", () => {
    expect(csvEscape("hello")).toBe('"hello"');
  });
  it("doubles internal quotes", () => {
    expect(csvEscape('he"llo')).toBe('"he""llo"');
  });
  it("returns empty quotes for null", () => {
    expect(csvEscape(null)).toBe('""');
  });
  it("returns empty quotes for undefined", () => {
    expect(csvEscape(undefined)).toBe('""');
  });
  it("converts number to string", () => {
    expect(csvEscape(42)).toBe('"42"');
  });
  it("handles empty string", () => {
    expect(csvEscape("")).toBe('""');
  });
  it("handles comma in value", () => {
    expect(csvEscape("a,b")).toBe('"a,b"');
  });
});

describe("buildUserCsvHeader", () => {
  it("returns 7 columns", () => {
    expect(buildUserCsvHeader()).toHaveLength(7);
  });
  it("includes ID and 昵称", () => {
    const h = buildUserCsvHeader();
    expect(h[0]).toBe("ID");
    expect(h[1]).toBe("昵称");
  });
});

describe("buildUserCsvRow", () => {
  const fmt = (v: string | null | undefined) => v || "";
  it("builds row for unbanned user", () => {
    const row = buildUserCsvRow(baseUser, fmt);
    expect(row[3]).toBe("正常");
    expect(row[5]).toBe("");
  });
  it("builds row for banned user", () => {
    const row = buildUserCsvRow({ ...baseUser, is_banned: true, banned_reason: "spam", banned_at: "2024-06-01T00:00:00Z" }, fmt);
    expect(row[3]).toBe("已封禁");
    expect(row[4]).toBe("spam");
    expect(row[5]).toBe("2024-06-01T00:00:00Z");
  });
  it("uses fallback nickname", () => {
    const row = buildUserCsvRow({ ...baseUser, nickname: null }, fmt);
    expect(row[1]).toBe("未设置昵称");
  });
  it("passes id and openid", () => {
    const row = buildUserCsvRow(baseUser, fmt);
    expect(row[0]).toBe(1);
    expect(row[2]).toBe("abc123");
  });
});

describe("filterBatchActionCandidates", () => {
  const users = [
    { ...baseUser, id: 1, is_banned: false },
    { ...baseUser, id: 2, is_banned: true },
    { ...baseUser, id: 3, is_banned: false },
  ];
  it("returns unbanned users for ban action", () => {
    const out = filterBatchActionCandidates(users, "ban");
    expect(out.map((u) => u.id)).toEqual([1, 3]);
  });
  it("returns banned users for unban action", () => {
    const out = filterBatchActionCandidates(users, "unban");
    expect(out.map((u) => u.id)).toEqual([2]);
  });
  it("returns empty when all banned for ban action", () => {
    expect(filterBatchActionCandidates([{ ...baseUser, is_banned: true }], "ban")).toEqual([]);
  });
  it("returns empty when all unbanned for unban action", () => {
    expect(filterBatchActionCandidates([{ ...baseUser, is_banned: false }], "unban")).toEqual([]);
  });
  it("returns empty for empty input", () => {
    expect(filterBatchActionCandidates([], "ban")).toEqual([]);
  });
});

describe("noCandidatesMessage", () => {
  it("ban message", () => {
    expect(noCandidatesMessage("ban")).toBe("所选用户均已处于封禁状态。");
  });
  it("unban message", () => {
    expect(noCandidatesMessage("unban")).toBe("所选用户均为正常状态，无需解封。");
  });
});

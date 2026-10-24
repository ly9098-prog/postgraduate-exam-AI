import { describe, it, expect } from "vitest";
import {
  checkPassword,
  isPasswordReady,
  isFormReady,
  filterManagedRoles,
  filterEditableRoles,
  buildRoleOptions,
  findSelectedFormRole,
  isSuperAdminUser,
  buildPagination,
  endOfChinaDateUtcIso,
  statusToQuery,
} from "./admin-user-utils";
import type { Role } from "./api/types";

const roles: Role[] = [
  { id: 1, name: "super_admin", display_name: "超级管理员", is_system: true },
  { id: 2, name: "admin", display_name: "管理员", is_system: true },
  { id: 3, name: "user", display_name: "用户", is_system: true },
  { id: 4, name: "custom_role", display_name: "自定义", is_system: false },
];

describe("checkPassword", () => {
  it("passes strong password", () => {
    const c = checkPassword("Abcdefghijk1");
    expect(c.length).toBe(true);
    expect(c.uppercase).toBe(true);
    expect(c.lowercase).toBe(true);
    expect(c.digit).toBe(true);
  });
  it("fails short password", () => {
    expect(checkPassword("Ab1").length).toBe(false);
  });
  it("fails missing uppercase", () => {
    expect(checkPassword("abcdefghijk1").uppercase).toBe(false);
  });
  it("fails missing lowercase", () => {
    expect(checkPassword("ABCDEFGHIJK1").lowercase).toBe(false);
  });
  it("fails missing digit", () => {
    expect(checkPassword("Abcdefghijk").digit).toBe(false);
  });
  it("fails empty", () => {
    const c = checkPassword("");
    expect(c.length).toBe(false);
    expect(c.uppercase).toBe(false);
    expect(c.lowercase).toBe(false);
    expect(c.digit).toBe(false);
  });
});

describe("isPasswordReady", () => {
  it("true for strong password", () => {
    expect(isPasswordReady("Abcdefghijk1")).toBe(true);
  });
  it("false for weak password", () => {
    expect(isPasswordReady("weak")).toBe(false);
  });
});

describe("isFormReady", () => {
  it("true for edit with role_id", () => {
    expect(isFormReady({ id: 1, username: "", password: "", role_id: "2" })).toBe(true);
  });
  it("false for create without username", () => {
    expect(isFormReady({ username: "", password: "Abcdefghijk1", role_id: "2" })).toBe(false);
  });
  it("false for create with weak password", () => {
    expect(isFormReady({ username: "test", password: "weak", role_id: "2" })).toBe(false);
  });
  it("false without role_id", () => {
    expect(isFormReady({ id: 1, username: "test", password: "Abcdefghijk1", role_id: "" })).toBe(false);
  });
  it("true for create with all fields", () => {
    expect(isFormReady({ username: "test", password: "Abcdefghijk1", role_id: "2" })).toBe(true);
  });
  it("trims username", () => {
    expect(isFormReady({ username: "  test  ", password: "Abcdefghijk1", role_id: "2" })).toBe(true);
  });
  it("false for whitespace-only username on create", () => {
    expect(isFormReady({ username: "   ", password: "Abcdefghijk1", role_id: "2" })).toBe(false);
  });
});

describe("filterManagedRoles", () => {
  it("keeps super_admin, admin, user", () => {
    const out = filterManagedRoles(roles);
    expect(out).toHaveLength(3);
    expect(out.map((r) => r.name)).toEqual(["super_admin", "admin", "user"]);
  });
  it("drops custom roles", () => {
    expect(filterManagedRoles(roles).find((r) => r.name === "custom_role")).toBeUndefined();
  });
  it("empty input returns empty", () => {
    expect(filterManagedRoles([])).toEqual([]);
  });
});

describe("filterEditableRoles", () => {
  it("excludes super_admin", () => {
    const out = filterEditableRoles(roles);
    expect(out).toHaveLength(3);
    expect(out.find((r) => r.name === "super_admin")).toBeUndefined();
  });
});

describe("buildRoleOptions", () => {
  it("builds value/label pairs", () => {
    const opts = buildRoleOptions([roles[0], roles[1]]);
    expect(opts).toEqual([
      { value: "1", label: "超级管理员" },
      { value: "2", label: "管理员" },
    ]);
  });
});

describe("findSelectedFormRole", () => {
  it("finds by string id", () => {
    expect(findSelectedFormRole(roles, "2")?.name).toBe("admin");
  });
  it("returns undefined for missing", () => {
    expect(findSelectedFormRole(roles, "99")).toBeUndefined();
  });
  it("returns undefined for empty string", () => {
    expect(findSelectedFormRole(roles, "")).toBeUndefined();
  });
});

describe("isSuperAdminUser", () => {
  it("true when role_id matches super_admin", () => {
    expect(isSuperAdminUser({ role_id: 1 }, roles)).toBe(true);
  });
  it("false for non-super admin", () => {
    expect(isSuperAdminUser({ role_id: 2 }, roles)).toBe(false);
  });
  it("false when no super_admin role exists", () => {
    expect(isSuperAdminUser({ role_id: 1 }, roles.filter((r) => r.name !== "super_admin"))).toBe(false);
  });
});

describe("buildPagination", () => {
  it("returns all pages when total <= 7", () => {
    expect(buildPagination(1, 5)).toEqual([1, 2, 3, 4, 5]);
  });
  it("returns compact list when current near start", () => {
    expect(buildPagination(2, 10)).toEqual([1, 2, 3, 4, 5, "ellipsis-right", 10]);
  });
  it("returns compact list when current near end", () => {
    expect(buildPagination(9, 10)).toEqual([1, "ellipsis-left", 6, 7, 8, 9, 10]);
  });
  it("returns centered list in middle", () => {
    expect(buildPagination(5, 10)).toEqual([1, "ellipsis-left", 4, 5, 6, "ellipsis-right", 10]);
  });
  it("handles total of 7 exactly", () => {
    expect(buildPagination(1, 7)).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });
});

describe("endOfChinaDateUtcIso", () => {
  it("returns non-empty string for valid date", () => {
    const result = endOfChinaDateUtcIso("2025-01-15");
    expect(result).toBeTruthy();
    expect(typeof result).toBe("string");
  });
  it("returns empty string for empty input", () => {
    expect(endOfChinaDateUtcIso("")).toBe("");
  });
});

describe("statusToQuery", () => {
  it("returns true for active", () => {
    expect(statusToQuery("active")).toBe(true);
  });
  it("returns false for inactive", () => {
    expect(statusToQuery("inactive")).toBe(false);
  });
  it("returns undefined for all", () => {
    expect(statusToQuery("all")).toBeUndefined();
  });
});

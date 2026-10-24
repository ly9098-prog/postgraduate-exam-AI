/**
 * Pure helpers for app-users page, extracted from app-users/page.tsx.
 * Covers CSV escaping, user-row building, batch-action candidate filtering,
 * pagination, and date/status query mapping.
 */

import { chinaDateToUtcIso } from "@/lib/time";

export type UserAction = "ban" | "unban";

export type UserStatusFilter = "all" | "active" | "banned";

export type PaginationItem = number | "ellipsis-left" | "ellipsis-right";

/**
 * Build a compact pagination item list with ellipses for large page counts.
 */
export function buildPagination(current: number, total: number): PaginationItem[] {
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1);

  if (current <= 4) return [1, 2, 3, 4, 5, "ellipsis-right", total];
  if (current >= total - 3) return [1, "ellipsis-left", total - 4, total - 3, total - 2, total - 1, total];

  return [1, "ellipsis-left", current - 1, current, current + 1, "ellipsis-right", total];
}

/**
 * Map a user status filter to the API boolean value, or undefined for "all".
 * Note: "active" maps to false (not banned), "banned" maps to true.
 */
export function statusToQueryValue(status: UserStatusFilter): boolean | undefined {
  if (status === "active") return false;
  if (status === "banned") return true;
  return undefined;
}

/**
 * Convert a China calendar date to the UTC ISO string of its end.
 * Emits the final microsecond before the next China calendar day so
 * PostgreSQL microsecond precision is covered.
 */
export function endOfChinaDateUtcIso(date: string): string {
  const nextDay = chinaDateToUtcIso(date, 1);
  if (!nextDay) return "";
  return new Date(new Date(nextDay).getTime() - 1000).toISOString().replace(/\.\d{3}Z$/, ".999999Z");
}

export type AppUserLike = {
  id: number;
  nickname?: string | null;
  openid: string;
  is_banned: boolean;
  banned_reason?: string | null;
  banned_at?: string | null;
  created_at?: string | null;
};

/**
 * Escape a value for CSV output: wrap in quotes, double internal quotes.
 */
export function csvEscape(value: string | number | null | undefined): string {
  const text = value === null || value === undefined ? "" : String(value);
  return `"${text.replaceAll('"', '""')}"`;
}

/**
 * Build the CSV header row for user export.
 */
export function buildUserCsvHeader(): string[] {
  return ["ID", "昵称", "OpenID", "状态", "封禁原因", "封禁时间（北京时间）", "创建时间（北京时间）"];
}

/**
 * Build a CSV row array from a user record. The `formatDate` callback keeps
 * this function pure by deferring date formatting to the caller.
 */
export function buildUserCsvRow(
  user: AppUserLike,
  formatDate: (value: string | null | undefined) => string,
): Array<string | number> {
  return [
    user.id,
    user.nickname || "未设置昵称",
    user.openid,
    user.is_banned ? "已封禁" : "正常",
    user.banned_reason || "",
    user.banned_at ? formatDate(user.banned_at) : "",
    user.created_at ? formatDate(user.created_at) : "",
  ];
}

/**
 * Filter selected users to candidates for a ban/unban batch action.
 * For ban, returns users not currently banned; for unban, returns banned users.
 */
export function filterBatchActionCandidates<T extends AppUserLike>(
  users: T[],
  action: UserAction,
): T[] {
  return users.filter((user) => (action === "ban" ? !user.is_banned : user.is_banned));
}

/**
 * Build the "no candidates" notice message for a given action.
 */
export function noCandidatesMessage(action: UserAction): string {
  return action === "ban"
    ? "所选用户均已处于封禁状态。"
    : "所选用户均为正常状态，无需解封。";
}

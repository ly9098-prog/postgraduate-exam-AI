/**
 * Pure helpers for app-users page, extracted from app-users/page.tsx.
 * Covers CSV escaping, user-row building, and batch-action candidate filtering.
 */

export type UserAction = "ban" | "unban";

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

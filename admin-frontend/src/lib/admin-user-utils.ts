/**
 * Pure helpers for admin-users page, extracted from admin-users/page.tsx.
 * Covers password validation, role filtering, and form-readiness checks.
 */

import type { Role } from "@/lib/api/types";
import { chinaDateToUtcIso } from "@/lib/time";


export type PaginationItem = number | "ellipsis-left" | "ellipsis-right";

export type StatusFilter = "all" | "active" | "inactive";

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
 * Convert a China calendar date to the UTC ISO string of its end (23:59:59.999).
 */
export function endOfChinaDateUtcIso(date: string): string {
  const nextDay = chinaDateToUtcIso(date, 1);
  if (!nextDay) return "";
  return new Date(new Date(nextDay).getTime() - 1).toISOString();
}

/**
 * Map a status filter to the API boolean value, or undefined for "all".
 */
export function statusToQuery(status: StatusFilter): boolean | undefined {
  if (status === "active") return true;
  if (status === "inactive") return false;
  return undefined;
}

export const ADMIN_ROLE_NAMES = new Set(["super_admin", "admin", "user"]);

export type PasswordChecks = {
  length: boolean;
  uppercase: boolean;
  lowercase: boolean;
  digit: boolean;
};

/**
 * Validate a password against the strength policy (12+ chars, upper, lower, digit).
 */
export function checkPassword(password: string): PasswordChecks {
  return {
    length: password.length >= 12,
    uppercase: /[A-Z]/.test(password),
    lowercase: /[a-z]/.test(password),
    digit: /\d/.test(password),
  };
}

/**
 * True when all password strength checks pass.
 */
export function isPasswordReady(password: string): boolean {
  return Object.values(checkPassword(password)).every(Boolean);
}

export type AdminUserFormData = {
  id?: number;
  username: string;
  password: string;
  role_id: string;
};

/**
 * Determine whether the admin-user create/edit form is ready to submit.
 * For edit (has id), only role_id is required. For create, username and
 * a ready password are also required.
 */
export function isFormReady(form: AdminUserFormData): boolean {
  return Boolean(
    form.role_id &&
      (form.id || (form.username.trim().length > 0 && isPasswordReady(form.password))),
  );
}

/**
 * Filter roles to only managed roles (super_admin, admin, user).
 */
export function filterManagedRoles(roles: Role[]): Role[] {
  return roles.filter((item) => ADMIN_ROLE_NAMES.has(item.name));
}

/**
 * Filter roles to editable ones (exclude super_admin).
 */
export function filterEditableRoles(roles: Role[]): Role[] {
  return roles.filter((item) => item.name !== "super_admin");
}

/**
 * Build role options for a select dropdown from role summaries.
 */
export function buildRoleOptions(
  roles: Role[],
): Array<{ value: string; label: string }> {
  return roles.map((item) => ({ value: String(item.id), label: item.display_name }));
}

/**
 * Find the selected role in editable roles by string id.
 */
export function findSelectedFormRole(
  roles: Role[],
  roleId: string,
): Role | undefined {
  return roles.find((item) => String(item.id) === roleId);
}

/**
 * Check if a user is a super admin by comparing role_id to the super_admin role.
 */
export function isSuperAdminUser(
  user: { role_id: number },
  roles: Role[],
): boolean {
  const superAdminRole = roles.find((item) => item.name === "super_admin");
  return Boolean(superAdminRole && user.role_id === superAdminRole.id);
}

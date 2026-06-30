export type PermissionKey =
  | "dashboard:read"
  | "app-user:read"
  | "app-user:write"
  | "app-user:ban"
  | "admin-user:read"
  | "admin-user:create"
  | "admin-user:update"
  | "admin-user:delete"
  | "admin-user:force-logout"
  | "admin-user:reset-password"
  | "question:read"
  | "question:write"
  | "question:delete"
  | "role:read"
  | "role:write"
  | "permission:read"
  | "ai_setting:read"
  | "ai_setting:write"
  | "import:read"
  | "import:write"
  | "audit:read";

export function hasPermission(permissions: string[], permission?: PermissionKey) {
  if (!permission) return true;
  return permissions.includes("*") || permissions.includes(permission);
}

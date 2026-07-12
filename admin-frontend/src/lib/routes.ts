import {
  FileInput,
  FileQuestion,
  Gauge,
  History,
  ShieldCheck,
  SlidersHorizontal,
  Users,
  UserCog,
  Sigma,
  ListTree,
  ClipboardCheck,
} from "lucide-react";
import type { ComponentType } from "react";
import type { PermissionKey } from "@/lib/permissions/permissions";

export type AdminRoute = {
  href: string;
  label: string;
  description: string;
  permission?: PermissionKey;
  icon: ComponentType<{ className?: string }>;
};

/**
 * Determine which admin route is active based on the current pathname.
 *
 * Rules:
 * 1. Path must match exactly, or be a sub-path starting with `${href}/`
 * 2. Among candidates, pick the one with the longest href (most specific)
 * 3. This ensures /formulas/categories only matches "公式分类", not "公式库"
 */
export function getActiveAdminRoute(
  pathname: string,
  routes: AdminRoute[],
): AdminRoute | null {
  const candidates = routes.filter((route) => {
    if (route.href === pathname) return true;
    return pathname.startsWith(route.href + "/");
  });
  if (candidates.length === 0) return null;
  return candidates.reduce((a, b) => (a.href.length >= b.href.length ? a : b));
}

export const adminRoutes: AdminRoute[] = [
  { href: "/dashboard", label: "总览", description: "指标与趋势", permission: "dashboard:read", icon: Gauge },
  { href: "/app-users", label: "小程序用户", description: "封禁与资料", permission: "app-user:read", icon: Users },
  { href: "/admin-users", label: "管理员", description: "账号与角色", permission: "admin-user:read", icon: UserCog },
  { href: "/questions", label: "题库", description: "题目治理", permission: "question:read", icon: FileQuestion },
  { href: "/imports/tasks", label: "题目导入管理", description: "导入与审核", permission: "import:read", icon: FileInput },
  { href: "/roles", label: "角色权限", description: "权限矩阵", permission: "role:read", icon: ShieldCheck },
  { href: "/ai-settings", label: "AI 解析设置", description: "开关与额度", permission: "ai_setting:read", icon: SlidersHorizontal },
  { href: "/audit-logs", label: "审计日志", description: "操作追踪", permission: "audit:read", icon: History },
  { href: "/formulas", label: "公式库", description: "公式管理", permission: "formula:read", icon: Sigma },
  { href: "/formulas/categories", label: "公式分类", description: "分类树管理", permission: "formula-category:read", icon: ListTree },
  { href: "/formulas/review", label: "公式审核", description: "审核队列", permission: "formula:review", icon: ClipboardCheck },
];

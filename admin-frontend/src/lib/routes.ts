import {
  ClipboardCheck,
  FileQuestion,
  Gauge,
  History,
  ShieldCheck,
  Users,
  UserCog,
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

export const adminRoutes: AdminRoute[] = [
  { href: "/dashboard", label: "总览", description: "指标与趋势", permission: "dashboard:read", icon: Gauge },
  { href: "/app-users", label: "小程序用户", description: "封禁与资料", permission: "app-user:read", icon: Users },
  { href: "/admin-users", label: "管理员", description: "账号与角色", permission: "admin-user:read", icon: UserCog },
  { href: "/questions", label: "题库", description: "题目治理", permission: "question:read", icon: FileQuestion },
  { href: "/review", label: "审核工作台", description: "快速复核", permission: "question:review", icon: ClipboardCheck },
  { href: "/roles", label: "角色权限", description: "权限矩阵", permission: "role:read", icon: ShieldCheck },
  { href: "/audit-logs", label: "审计日志", description: "操作追踪", permission: "audit:read", icon: History },
];

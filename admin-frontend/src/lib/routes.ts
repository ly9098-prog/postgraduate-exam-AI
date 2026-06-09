import {
  FileInput,
  FileQuestion,
  Gauge,
  History,
  ShieldCheck,
  SlidersHorizontal,
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
  { href: "/imports/tasks", label: "题目导入管理", description: "导入与审核", permission: "import:read", icon: FileInput },
  { href: "/roles", label: "角色权限", description: "权限矩阵", permission: "role:read", icon: ShieldCheck },
  { href: "/ai-settings", label: "AI 解析设置", description: "开关与额度", permission: "ai_setting:read", icon: SlidersHorizontal },
  { href: "/audit-logs", label: "审计日志", description: "操作追踪", permission: "audit:read", icon: History },
];

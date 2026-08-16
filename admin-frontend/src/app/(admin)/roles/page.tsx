"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  Bot,
  Boxes,
  BookOpenCheck,
  ChevronDown,
  ClipboardList,
  KeyRound,
  LayoutDashboard,
  Library,
  LockKeyhole,
  Network,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  ShieldCheck,
  Sigma,
  Sparkles,
  Upload,
  UsersRound,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { CustomCheckbox } from "@/components/ui/custom-checkbox";
import { Toggle } from "@/components/ui/toggle";
import { apiRequest } from "@/lib/api/client";
import { useAuthStore } from "@/lib/auth/auth-store";
import type { Permission, Role } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const CATEGORY_META: Record<string, { label: string; description: string }> = {
  dashboard: { label: "仪表盘", description: "统计概览与运营数据" },
  admin_user: { label: "管理员管理", description: "后台管理员账号与安全操作" },
  app_user: { label: "用户管理", description: "小程序用户查看与状态管理" },
  question: { label: "题库管理", description: "题目查看、编辑、审核与删除" },
  subject: { label: "科目管理", description: "科目与题库分类维护" },
  knowledge: { label: "知识图谱", description: "知识点与知识图谱能力" },
  formula: { label: "公式管理", description: "公式、公式分类与审核发布流程" },
  import: { label: "导入管理", description: "批量导入任务与数据维护" },
  recommendation: { label: "推荐系统", description: "策略、实验、指标与报表" },
  ai_setting: { label: "AI 设置", description: "AI 解析与模型配置" },
  audit: { label: "审计日志", description: "后台关键操作审计记录" },
  sync: { label: "数据同步", description: "本地与云端数据同步" },
  rbac: { label: "角色权限", description: "角色、权限与 RBAC 配置" },
};

const CATEGORY_ORDER = [
  "dashboard",
  "admin_user",
  "app_user",
  "question",
  "subject",
  "knowledge",
  "formula",
  "import",
  "recommendation",
  "ai_setting",
  "audit",
  "sync",
  "rbac",
];

const ACTION_LABELS: Record<string, string> = {
  read: "查看",
  create: "创建",
  write: "管理",
  update: "编辑",
  delete: "删除",
  review: "审核",
  batch_review: "批审",
  publish: "发布",
  import: "导入",
  "ai-generate": "AI 生成",
  ban: "封禁",
  "force-logout": "下线",
  "reset-password": "重置密码",
};

const ACTION_ORDER = [
  "read",
  "create",
  "write",
  "update",
  "delete",
  "review",
  "batch_review",
  "publish",
  "import",
  "ai-generate",
  "ban",
  "force-logout",
  "reset-password",
];

const RESOURCE_LABELS: Record<string, string> = {
  dashboard: "仪表盘",
  "admin-user": "后台管理员",
  "app-user": "小程序用户",
  question: "题目",
  subject: "科目",
  knowledge: "知识图谱",
  formula: "公式",
  "formula-category": "公式分类",
  import: "导入任务",
  recommendation: "推荐系统",
  ai_setting: "AI 解析设置",
  audit: "审计日志",
  sync: "数据同步",
  role: "角色",
  permission: "权限",
};

const HIGH_RISK_PERMISSION_NAMES = new Set([
  "admin-user:delete",
  "admin-user:force-logout",
  "admin-user:reset-password",
  "question:delete",
  "subject:delete",
  "role:write",
  "role:delete",
  "formula:publish",
  "formula:delete",
  "sync:write",
]);

type MatrixRow = {
  resource: string;
  label: string;
  permissions: Permission[];
  byAction: Map<string, Permission>;
};

type CategoryMatrix = {
  category: string;
  items: Permission[];
  rows: MatrixRow[];
  actions: string[];
};

function categoryLabel(category: string) {
  return CATEGORY_META[category]?.label ?? category.replaceAll("_", " ");
}

function categoryDescription(category: string) {
  return CATEGORY_META[category]?.description ?? "该模块下的功能访问与操作权限";
}

function resourceLabel(resource: string) {
  return RESOURCE_LABELS[resource] ?? resource.replaceAll(/[-_]/g, " ");
}

function actionLabel(action: string) {
  return ACTION_LABELS[action] ?? action.replaceAll(/[-_]/g, " ");
}

function actionIndex(action: string) {
  const index = ACTION_ORDER.indexOf(action);
  return index === -1 ? Number.MAX_SAFE_INTEGER : index;
}

function CategoryIcon({ category }: { category: string }) {
  const className = "h-4 w-4";
  switch (category) {
    case "dashboard":
      return <LayoutDashboard className={className} />;
    case "admin_user":
      return <ShieldCheck className={className} />;
    case "app_user":
      return <UsersRound className={className} />;
    case "question":
      return <BookOpenCheck className={className} />;
    case "subject":
      return <Library className={className} />;
    case "knowledge":
      return <Network className={className} />;
    case "formula":
      return <Sigma className={className} />;
    case "import":
      return <Upload className={className} />;
    case "recommendation":
      return <Sparkles className={className} />;
    case "ai_setting":
      return <Bot className={className} />;
    case "audit":
      return <ClipboardList className={className} />;
    case "sync":
      return <RefreshCw className={className} />;
    case "rbac":
      return <KeyRound className={className} />;
    default:
      return <Boxes className={className} />;
  }
}

function samePermissionSet(left: Iterable<number>, right: Iterable<number>) {
  const leftSet = left instanceof Set ? left : new Set(left);
  const rightSet = right instanceof Set ? right : new Set(right);
  if (leftSet.size !== rightSet.size) return false;
  for (const id of leftSet) {
    if (!rightSet.has(id)) return false;
  }
  return true;
}

function buildMatrixRows(items: Permission[]): MatrixRow[] {
  const grouped = new Map<string, Permission[]>();
  items.forEach((permission) => {
    const current = grouped.get(permission.resource) ?? [];
    current.push(permission);
    grouped.set(permission.resource, current);
  });

  return Array.from(grouped.entries()).map(([resource, permissions]) => ({
    resource,
    label: resourceLabel(resource),
    permissions,
    byAction: new Map(permissions.map((permission) => [permission.action, permission])),
  }));
}

function permissionMatches(permission: Permission, category: string, keyword: string) {
  return [
    permission.name,
    permission.resource,
    permission.action,
    actionLabel(permission.action),
    permission.description ?? "",
    resourceLabel(permission.resource),
    categoryLabel(category),
    categoryDescription(category),
  ]
    .join(" ")
    .toLowerCase()
    .includes(keyword);
}

export default function RolesPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const role = useAuthStore((state) => state.role);
  const isBootstrapping = useAuthStore((state) => state.isBootstrapping);
  const isSuperAdmin = role?.name === "super_admin";
  const [selectedRoleId, setSelectedRoleId] = useState<number | null>(null);
  const [permissionOverrides, setPermissionOverrides] = useState<Record<number, number[]>>({});
  const [searchQuery, setSearchQuery] = useState("");
  const [onlyGranted, setOnlyGranted] = useState(false);
  const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(new Set());
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isBootstrapping && !isSuperAdmin) {
      router.replace("/dashboard");
    }
  }, [isBootstrapping, isSuperAdmin, router]);

  const roles = useQuery({
    queryKey: ["roles"],
    queryFn: () => apiRequest<{ items: Role[] }>("/roles"),
    enabled: isSuperAdmin,
  });

  const permissions = useQuery({
    queryKey: ["permissions-by-category"],
    queryFn: async () =>
      (await apiRequest<{ items: Record<string, Permission[]> }>("/permissions/by-category")).items,
    enabled: isSuperAdmin,
  });

  const roleItems = useMemo(() => roles.data?.items ?? [], [roles.data]);
  const activeRoleId =
    selectedRoleId ?? roleItems.find((role) => role.name === "admin")?.id ?? roleItems.find((role) => role.name !== "super_admin")?.id ?? roleItems[0]?.id ?? null;
  const selectedRole = useMemo(() => roleItems.find((role) => role.id === activeRoleId) ?? null, [roleItems, activeRoleId]);
  const originalPermissionIds = useMemo(() => new Set(selectedRole?.permission_ids ?? []), [selectedRole]);
  const activePermissionIds = useMemo(() => {
    if (!activeRoleId) return new Set<number>();
    const override = permissionOverrides[activeRoleId];
    return new Set(override ?? Array.from(originalPermissionIds));
  }, [activeRoleId, originalPermissionIds, permissionOverrides]);

  const isLocked = selectedRole?.name === "super_admin";
  const isDirty = Boolean(selectedRole && !samePermissionSet(originalPermissionIds, activePermissionIds));

  const permissionChanges = useMemo(() => {
    let added = 0;
    let removed = 0;
    activePermissionIds.forEach((id) => {
      if (!originalPermissionIds.has(id)) added += 1;
    });
    originalPermissionIds.forEach((id) => {
      if (!activePermissionIds.has(id)) removed += 1;
    });
    return { added, removed };
  }, [activePermissionIds, originalPermissionIds]);

  const allCategoryEntries = useMemo(() => {
    const entries = Object.entries(permissions.data ?? {});
    return entries.sort(([left], [right]) => {
      const leftIndex = CATEGORY_ORDER.indexOf(left);
      const rightIndex = CATEGORY_ORDER.indexOf(right);
      if (leftIndex === -1 && rightIndex === -1) return left.localeCompare(right);
      if (leftIndex === -1) return 1;
      if (rightIndex === -1) return -1;
      return leftIndex - rightIndex;
    });
  }, [permissions.data]);

  const categoryMatrices = useMemo<CategoryMatrix[]>(() => {
    const keyword = searchQuery.trim().toLowerCase();

    return allCategoryEntries
      .map(([category, items]) => {
        const allRows = buildMatrixRows(items);
        const categoryMatches =
          Boolean(keyword) && `${categoryLabel(category)} ${categoryDescription(category)} ${category}`.toLowerCase().includes(keyword);
        const rows = allRows.filter((row) => {
          if (onlyGranted && !row.permissions.some((permission) => activePermissionIds.has(permission.id))) return false;
          if (!keyword || categoryMatches) return true;
          return (
            `${row.label} ${row.resource}`.toLowerCase().includes(keyword) ||
            row.permissions.some((permission) => permissionMatches(permission, category, keyword))
          );
        });
        const actions = Array.from(new Set(items.map((permission) => permission.action))).sort(
          (left, right) => actionIndex(left) - actionIndex(right) || left.localeCompare(right),
        );
        return { category, items, rows, actions };
      })
      .filter((matrix) => matrix.rows.length > 0);
  }, [activePermissionIds, allCategoryEntries, onlyGranted, searchQuery]);

  const totalPermissionCount = useMemo(
    () => allCategoryEntries.reduce((total, [, items]) => total + items.length, 0),
    [allCategoryEntries],
  );

  const visibleResourceCount = useMemo(
    () => categoryMatrices.reduce((total, matrix) => total + matrix.rows.length, 0),
    [categoryMatrices],
  );

  const saveMutation = useMutation({
    mutationFn: async ({ roleId, permissionIds }: { roleId: number; permissionIds: number[] }) =>
      apiRequest<{ status: string; permission_ids: number[] }>(`/roles/${roleId}/permissions`, {
        method: "PUT",
        body: JSON.stringify({ permission_ids: permissionIds }),
      }),
    onSuccess: async (_data, variables) => {
      await queryClient.invalidateQueries({ queryKey: ["roles"] });
      setPermissionOverrides((current) => {
        const next = { ...current };
        delete next[variables.roleId];
        return next;
      });
      setMessage("角色权限已保存并立即生效");
      setConfirmOpen(false);
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : "保存失败，请稍后重试。"),
  });

  useEffect(() => {
    if (!message) return;
    const timer = window.setTimeout(() => setMessage(null), 2800);
    return () => window.clearTimeout(timer);
  }, [message]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const isTyping = Boolean(target?.closest("input, textarea, [contenteditable='true']"));

      if (event.key === "/" && !isTyping) {
        event.preventDefault();
        searchInputRef.current?.focus();
        return;
      }

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        if (!selectedRole || isLocked || !isDirty || saveMutation.isPending) return;
        event.preventDefault();
        setConfirmOpen(true);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isDirty, isLocked, saveMutation.isPending, selectedRole]);

  const replaceActivePermissions = (nextIds: Iterable<number>) => {
    if (!selectedRole || isLocked) return;
    setPermissionOverrides((current) => ({
      ...current,
      [selectedRole.id]: Array.from(new Set(nextIds)).sort((a, b) => a - b),
    }));
    setMessage(null);
  };

  const togglePermission = (permissionId: number) => {
    const next = new Set(activePermissionIds);
    if (next.has(permissionId)) next.delete(permissionId);
    else next.add(permissionId);
    replaceActivePermissions(next);
  };

  const toggleCategory = (items: Permission[]) => {
    if (!selectedRole || isLocked) return;
    const next = new Set(activePermissionIds);
    const allGranted = items.every((permission) => next.has(permission.id));
    items.forEach((permission) => {
      if (allGranted) next.delete(permission.id);
      else next.add(permission.id);
    });
    replaceActivePermissions(next);
  };

  const resetActiveRole = () => {
    if (!selectedRole) return;
    setPermissionOverrides((current) => {
      const next = { ...current };
      delete next[selectedRole.id];
      return next;
    });
    setMessage("已恢复到最近一次保存状态");
  };

  const toggleCategoryCollapsed = (category: string) => {
    setCollapsedCategories((current) => {
      const next = new Set(current);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });
  };

  const collapseAll = () => setCollapsedCategories(new Set(allCategoryEntries.map(([category]) => category)));
  const expandAll = () => setCollapsedCategories(new Set());

  const selectRole = (roleId: number) => {
    setSelectedRoleId(roleId);
    setMessage(null);
  };

  const requestSave = () => {
    if (!selectedRole || isLocked || !isDirty) return;
    setConfirmOpen(true);
  };

  // /roles is a super-admin-only workspace. Do not mount the matrix or fire its
  // queries while auth is unresolved or while a non-super-admin is being redirected.
  if (isBootstrapping || !isSuperAdmin) return null;

  return (
    <div>
      <Card className="overflow-hidden">
        <div className="border-b border-[var(--color-border)] px-5 py-4 sm:px-6">
          <div className="flex min-h-10 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]">
                <KeyRound className="h-4 w-4" />
              </div>
              <div>
                <h3 className="font-display text-xl font-bold text-[var(--ink)]">权限矩阵</h3>
                <p className="text-sm text-[var(--color-text-secondary)]">选择左侧角色，在右侧矩阵中按资源和操作集中授权。</p>
              </div>
            </div>
            {message ? (
              <div className="animate-drop-in rounded-lg border border-[var(--color-border)] bg-white/80 px-3 py-2 text-xs font-medium text-[var(--color-text-secondary)] shadow-sm" role="status">
                {message}
              </div>
            ) : null}
          </div>
        </div>

        <div className="grid min-h-[680px] xl:grid-cols-[236px_minmax(0,1fr)]">
          <aside className="border-b border-[var(--color-border)] bg-white/30 xl:border-b-0 xl:border-r">
            <div className="flex items-center justify-between gap-3 border-b border-[var(--color-border-light)] px-5 py-3.5">
              <span className="text-sm font-semibold text-[var(--ink)]">角色</span>
              <span className="text-xs text-[var(--color-text-hint)]">{roleItems.length} 个</span>
            </div>

            <div className="py-2">
              {roles.isLoading ? (
                <div className="space-y-2 px-3 py-3">
                  {[0, 1, 2].map((index) => (
                    <div key={index} className="h-[78px] animate-pulse rounded-lg bg-[var(--color-bg-input)]/65" />
                  ))}
                </div>
              ) : roles.isError ? (
                <div className="px-5 py-6 text-sm text-[var(--color-danger)]">角色加载失败，请刷新后重试。</div>
              ) : (
                <div className="divide-y divide-[var(--color-border-light)]/70">
                  {roleItems.map((role) => {
                    const active = role.id === activeRoleId;
                    const pendingOverride = permissionOverrides[role.id];
                    const permissionCount = pendingOverride?.length ?? role.permission_ids?.length ?? 0;
                    const roleDirty = Boolean(pendingOverride && !samePermissionSet(role.permission_ids ?? [], pendingOverride));
                    return (
                      <button
                        key={role.id}
                        type="button"
                        aria-pressed={active}
                        onClick={() => selectRole(role.id)}
                        className={cn(
                          "group relative w-full px-5 py-3.5 text-left transition-all duration-200 focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--color-primary)] active:bg-[var(--color-primary-light)]",
                          active ? "bg-[var(--color-primary-light)]/85" : "hover:bg-white/70",
                        )}
                      >
                        <span
                          className={cn(
                            "absolute inset-y-2 left-0 w-[3px] rounded-r-full bg-[var(--color-primary)] transition-all duration-200",
                            active ? "scale-y-100 opacity-100" : "scale-y-50 opacity-0",
                          )}
                        />
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className={cn("font-semibold transition-colors", active ? "text-[var(--color-primary-dark)]" : "text-[var(--ink)]")}>{role.display_name}</span>
                              {role.is_system ? <StatusBadge tone="neutral">系统</StatusBadge> : null}
                            </div>
                            <p className="mt-1 line-clamp-2 text-xs leading-5 text-[var(--color-text-secondary)]">{role.description || role.name}</p>
                            <div className="mt-1.5 flex items-center gap-1.5 text-xs">
                              <span className={cn("font-semibold tabular-nums", active ? "text-[var(--color-primary-dark)]" : "text-[var(--color-text-secondary)]")}>
                                {permissionCount}{totalPermissionCount > 0 ? ` / ${totalPermissionCount}` : ""} 项权限
                              </span>
                              {roleDirty ? <span className="font-medium text-[var(--color-warning)]">未保存</span> : null}
                            </div>
                          </div>
                          {role.name === "super_admin" ? <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-text-hint)]" /> : null}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </aside>

          <main className="min-w-0 bg-white/15">
            <div key={selectedRole?.id ?? "empty"} className="animate-fade-in">
              <div className="border-b border-[var(--color-border)] px-5 py-4 sm:px-6">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-display text-2xl font-bold text-[var(--ink)]">{selectedRole?.display_name ?? "未选择角色"}</h3>
                      {selectedRole?.is_system ? <StatusBadge tone="neutral">系统</StatusBadge> : null}
                      {isLocked ? <StatusBadge tone="warning">只读</StatusBadge> : null}
                      {isDirty ? (
                        <StatusBadge tone="primary">
                          待保存 {permissionChanges.added > 0 ? `+${permissionChanges.added}` : ""}
                          {permissionChanges.added > 0 && permissionChanges.removed > 0 ? " / " : ""}
                          {permissionChanges.removed > 0 ? `-${permissionChanges.removed}` : ""}
                        </StatusBadge>
                      ) : null}
                    </div>
                    <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
                      {selectedRole?.description || "请选择一个角色以查看权限"}
                      {selectedRole ? ` · ${activePermissionIds.size} / ${totalPermissionCount} 项权限已开启` : ""}
                    </p>
                    {isLocked ? <p className="mt-1.5 text-xs text-[var(--color-text-hint)]">超级管理员始终拥有全部权限，矩阵仅用于查看。</p> : null}
                  </div>

                  <div className="flex shrink-0 flex-wrap gap-2">
                    <Button
                      variant="secondary"
                      disabled={!selectedRole || !isDirty || saveMutation.isPending}
                      onClick={resetActiveRole}
                      className="active:scale-[0.98]"
                    >
                      <RotateCcw className="h-4 w-4" />
                      重置修改
                    </Button>
                    <Button
                      disabled={!selectedRole || isLocked || !isDirty || saveMutation.isPending}
                      onClick={requestSave}
                      title="保存权限（Ctrl / Cmd + S）"
                      className="active:scale-[0.98]"
                    >
                      <Save className={cn("h-4 w-4", saveMutation.isPending && "animate-pulse")} />
                      {saveMutation.isPending ? "保存中…" : "保存权限"}
                    </Button>
                  </div>
                </div>
              </div>

              <div className="border-b border-[var(--color-border)] px-5 py-3 sm:px-6">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                  <label className="relative block w-full lg:max-w-md">
                    <span className="sr-only">搜索权限</span>
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
                    <input
                      ref={searchInputRef}
                      value={searchQuery}
                      onChange={(event) => setSearchQuery(event.target.value)}
                      placeholder="搜索权限名称、资源代码或操作"
                      className="h-10 w-full rounded-lg border border-[var(--color-border)] bg-white/80 pl-9 pr-16 text-sm text-[var(--ink)] outline-none transition-all duration-200 placeholder:text-[var(--color-text-hint)] focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary-light)]"
                    />
                    {!searchQuery ? (
                      <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-[var(--color-border-light)] bg-[var(--color-bg-input)]/70 px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-text-hint)]">
                        /
                      </span>
                    ) : null}
                    {searchQuery ? (
                      <button
                        type="button"
                        aria-label="清空搜索"
                        onClick={() => setSearchQuery("")}
                        className="absolute right-2 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-[var(--color-text-hint)] transition hover:bg-[var(--color-bg-input)] hover:text-[var(--ink)]"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    ) : null}
                  </label>

                  <div className="flex flex-wrap items-center justify-end gap-2 text-sm">
                    <span className="mr-1 hidden whitespace-nowrap text-xs tabular-nums text-[var(--color-text-hint)] sm:inline">
                      {categoryMatrices.length} 个模块 · {visibleResourceCount} 个资源
                    </span>
                    <div
                      className={cn(
                        "flex h-9 items-center gap-2 rounded-lg border px-3 text-xs font-medium transition-all duration-150",
                        onlyGranted
                          ? "border-[var(--color-primary)]/25 bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]"
                          : "border-[var(--color-border)] bg-white/65 text-[var(--color-text-secondary)]",
                      )}
                    >
                      <Toggle checked={onlyGranted} onChange={() => setOnlyGranted((current) => !current)} size="sm" color="var(--color-primary)" />
                      <button type="button" onClick={() => setOnlyGranted((current) => !current)} className="whitespace-nowrap transition hover:text-[var(--ink)]">
                        仅显示已授权
                      </button>
                    </div>
                    <div className="flex h-9 overflow-hidden rounded-lg border border-[var(--color-border)] bg-white/65">
                      <button
                        type="button"
                        className="px-3 text-xs font-semibold text-[var(--color-primary-dark)] transition hover:bg-[var(--color-primary-light)]/65"
                        onClick={expandAll}
                      >
                        展开全部
                      </button>
                      <span className="w-px bg-[var(--color-border-light)]" aria-hidden="true" />
                      <button
                        type="button"
                        className="px-3 text-xs font-semibold text-[var(--color-primary-dark)] transition hover:bg-[var(--color-primary-light)]/65"
                        onClick={collapseAll}
                      >
                        收起全部
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <div className="space-y-2.5 p-4 sm:p-5">
                {permissions.isLoading ? (
                  <div className="space-y-3">
                    {[0, 1, 2].map((index) => (
                      <div key={index} className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-white/65">
                        <div className="h-14 animate-pulse bg-[var(--color-bg-input)]/60" />
                        <div className="space-y-px border-t border-[var(--color-border)] p-3">
                          <div className="h-9 animate-pulse rounded bg-[var(--color-bg-input)]/45" />
                          <div className="h-9 animate-pulse rounded bg-[var(--color-bg-input)]/45" />
                        </div>
                      </div>
                    ))}
                  </div>
                ) : permissions.isError ? (
                  <div className="rounded-xl border border-[var(--color-danger)]/40 bg-[var(--color-danger-light)] px-4 py-10 text-center text-sm text-[var(--color-danger)]">
                    权限加载失败，请确认后端 RBAC 接口可用。
                  </div>
                ) : categoryMatrices.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-[var(--color-border)] bg-white/45 px-4 py-12 text-center">
                    <p className="font-semibold text-[var(--ink)]">没有匹配的权限</p>
                    <p className="mt-1 text-sm text-[var(--color-text-secondary)]">尝试修改搜索条件或关闭“仅显示已授权”。</p>
                    {searchQuery ? (
                      <button type="button" className="mt-4 text-sm font-semibold text-[var(--color-primary-dark)] hover:underline" onClick={() => setSearchQuery("")}>
                        清空搜索
                      </button>
                    ) : null}
                  </div>
                ) : (
                  categoryMatrices.map(({ category, items, rows, actions }) => {
                    const collapsed = collapsedCategories.has(category);
                    const grantedCount = items.filter((permission) => activePermissionIds.has(permission.id)).length;
                    const categoryAdded = items.filter((permission) => activePermissionIds.has(permission.id) && !originalPermissionIds.has(permission.id)).length;
                    const categoryRemoved = items.filter((permission) => !activePermissionIds.has(permission.id) && originalPermissionIds.has(permission.id)).length;
                    const categoryDirty = categoryAdded > 0 || categoryRemoved > 0;
                    const allGranted = items.length > 0 && grantedCount === items.length;
                    const someGranted = grantedCount > 0 && !allGranted;
                    const matrixMinWidth = 420 + actions.length * 92;

                    return (
                      <section key={category} className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-white/80 shadow-[0_1px_0_rgba(15,23,42,0.02)] transition-[border-color,box-shadow] duration-200 hover:border-[var(--color-primary)]/25 hover:shadow-sm">
                        <div className="flex min-h-[52px] items-center gap-3 px-4 py-2">
                          <button
                            type="button"
                            onClick={() => toggleCategoryCollapsed(category)}
                            className="group flex min-w-0 flex-1 items-center gap-3 text-left focus-visible:outline-none"
                            aria-expanded={!collapsed}
                          >
                            <ChevronDown
                              className={cn(
                                "h-4 w-4 shrink-0 text-[var(--color-text-hint)] transition-transform duration-200 group-hover:text-[var(--color-primary-dark)]",
                                collapsed && "-rotate-90",
                              )}
                            />
                            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--color-primary-light)] text-[var(--color-primary-dark)] transition-transform duration-200 group-hover:scale-105">
                              <CategoryIcon category={category} />
                            </div>
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-2">
                                <h4 className="font-semibold text-[var(--ink)]">{categoryLabel(category)}</h4>
                                <span className="inline-flex h-5 items-center rounded-full border border-[var(--color-border-light)] bg-[var(--color-bg-input)]/55 px-2 font-mono text-[10px] tabular-nums text-[var(--color-text-secondary)]">
                                  {grantedCount}/{items.length}
                                </span>
                                {categoryDirty ? (
                                  <span className="animate-drop-in text-[10px] font-semibold tabular-nums text-[var(--color-warning)]">
                                    变更 {categoryAdded > 0 ? `+${categoryAdded}` : ""}{categoryAdded > 0 && categoryRemoved > 0 ? "/" : ""}{categoryRemoved > 0 ? `-${categoryRemoved}` : ""}
                                  </span>
                                ) : null}
                              </div>
                              <p className="mt-0.5 truncate text-xs text-[var(--color-text-secondary)]">{categoryDescription(category)}</p>
                            </div>
                          </button>

                          <div className={cn("flex shrink-0 items-center gap-2", isLocked && "opacity-55")}>
                            <CustomCheckbox
                              checked={allGranted}
                              indeterminate={someGranted}
                              disabled={!selectedRole || isLocked}
                              onCheckedChange={() => toggleCategory(items)}
                              aria-label={`${categoryLabel(category)}全选`}
                            />
                            <button
                              type="button"
                              disabled={!selectedRole || isLocked}
                              onClick={() => toggleCategory(items)}
                              className="text-xs font-semibold text-[var(--color-primary-dark)] transition hover:opacity-70 disabled:cursor-not-allowed"
                            >
                              {allGranted ? "取消全选" : "全选"}
                            </button>
                          </div>
                        </div>

                        <div
                          className={cn(
                            "grid transition-[grid-template-rows,opacity] duration-300 ease-out",
                            collapsed ? "grid-rows-[0fr] opacity-0" : "grid-rows-[1fr] opacity-100",
                          )}
                        >
                          <div className="min-h-0 overflow-hidden">
                            <div className="overflow-x-auto border-t border-[var(--color-border)] bg-white/60">
                              <table className="w-full border-separate border-spacing-0 text-sm" style={{ minWidth: `${matrixMinWidth}px` }}>
                                <colgroup>
                                  <col style={{ width: "230px" }} />
                                  <col style={{ width: "170px" }} />
                                  {actions.map((action) => (
                                    <col key={action} style={{ width: "92px" }} />
                                  ))}
                                </colgroup>
                                <thead>
                                  <tr className="text-left text-[11px] font-semibold text-[var(--color-text-hint)]">
                                    <th className="sticky left-0 z-20 border-b border-r border-[var(--color-border)] bg-[var(--color-bg-input)] px-4 py-2.5 shadow-[1px_0_0_var(--color-border)]">
                                      权限资源
                                    </th>
                                    <th className="sticky left-[230px] z-20 border-b border-r-2 border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2.5 shadow-[2px_0_3px_rgba(15,23,42,0.03)]">
                                      资源代码
                                    </th>
                                    {actions.map((action) => (
                                      <th
                                        key={action}
                                        className="border-b border-r border-[var(--color-border-light)] bg-[var(--color-bg-input)]/80 px-2 py-2.5 text-center whitespace-nowrap last:border-r-0"
                                      >
                                        <span className="inline-flex min-w-9 items-center justify-center rounded-md px-1.5 py-0.5 text-[var(--color-text-secondary)]">
                                          {actionLabel(action)}
                                        </span>
                                      </th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody>
                                  {rows.map((row, rowIndex) => {
                                    const rowGrantedCount = row.permissions.filter((permission) => activePermissionIds.has(permission.id)).length;
                                    const rowAllGranted = row.permissions.length > 0 && rowGrantedCount === row.permissions.length;
                                    return (
                                      <tr
                                        key={row.resource}
                                        className={cn(
                                          "group/row transition-colors duration-150",
                                          rowIndex > 0 && "[&>td]:border-t [&>td]:border-[var(--color-border-light)]",
                                        )}
                                      >
                                        <td className={cn(
                                          "sticky left-0 z-10 border-r border-[var(--color-border)] px-4 py-2.5 shadow-[1px_0_0_var(--color-border)] transition-colors duration-150 group-hover/row:bg-[var(--color-primary-light)]/45",
                                          rowIndex % 2 === 0 ? "bg-white" : "bg-[var(--color-bg-card)]",
                                        )}>
                                          <div className="flex min-w-0 items-center justify-between gap-3">
                                            <span className="min-w-0 truncate font-semibold text-[var(--ink)]">{row.label}</span>
                                            <span
                                              className={cn(
                                                "inline-flex h-6 min-w-9 shrink-0 items-center justify-center rounded-full border px-2 font-mono text-[10px] tabular-nums transition-colors",
                                                rowAllGranted
                                                  ? "border-[var(--color-primary)]/20 bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]"
                                                  : "border-[var(--color-border)] bg-[var(--color-bg-input)]/55 text-[var(--color-text-secondary)]",
                                              )}
                                            >
                                              {rowGrantedCount}/{row.permissions.length}
                                            </span>
                                          </div>
                                        </td>
                                        <td className={cn(
                                          "sticky left-[230px] z-10 border-r-2 border-[var(--color-border)] px-3 py-2.5 shadow-[2px_0_3px_rgba(15,23,42,0.03)] transition-colors duration-150 group-hover/row:bg-[var(--color-primary-light)]/45",
                                          rowIndex % 2 === 0 ? "bg-white" : "bg-[var(--color-bg-card)]",
                                        )}>
                                          <code className="inline-flex max-w-full truncate rounded-md border border-[var(--color-border-light)] bg-[var(--color-bg-input)]/60 px-2 py-1 font-mono text-[11px] font-medium tracking-[0.01em] text-[var(--color-text-secondary)]">
                                            {row.resource}
                                          </code>
                                        </td>
                                        {actions.map((action) => {
                                          const permission = row.byAction.get(action);
                                          if (!permission) {
                                            return (
                                              <td
                                                key={action}
                                                className={cn(
                                                  "border-r border-[var(--color-border-light)] px-2 py-3 text-center text-[var(--color-border)] last:border-r-0",
                                                  rowIndex % 2 === 0 ? "bg-[var(--color-bg-input)]/18" : "bg-[var(--color-bg-input)]/28",
                                                )}
                                                aria-hidden="true"
                                              >
                                                <span className="select-none text-xs opacity-70">—</span>
                                              </td>
                                            );
                                          }

                                          const granted = activePermissionIds.has(permission.id);
                                          const originallyGranted = originalPermissionIds.has(permission.id);
                                          const changeState = granted === originallyGranted ? null : granted ? "added" : "removed";
                                          const highRisk = HIGH_RISK_PERMISSION_NAMES.has(permission.name);
                                          const title = `${permission.description || permission.name} · ${permission.name}${highRisk ? " · 高风险权限" : ""}${changeState === "added" ? " · 待保存：新增" : changeState === "removed" ? " · 待保存：移除" : ""}`;
                                          return (
                                            <td
                                              key={action}
                                              onClick={() => {
                                                if (!selectedRole || isLocked) return;
                                                togglePermission(permission.id);
                                              }}
                                              className={cn(
                                                "relative border-r border-[var(--color-border-light)] px-2 py-2 text-center transition-[background-color,box-shadow] duration-150 last:border-r-0",
                                                rowIndex % 2 === 0 ? "bg-white/65" : "bg-[var(--color-bg-card)]/80",
                                                granted && !highRisk && "bg-[var(--color-primary-light)]/24",
                                                highRisk && "bg-[var(--color-warning-light)]/35",
                                                changeState === "added" && "shadow-[inset_0_0_0_1px_rgba(74,111,138,0.28)]",
                                                changeState === "removed" && "bg-[var(--color-warning-light)]/50 shadow-[inset_0_0_0_1px_rgba(196,154,107,0.35)]",
                                                !isLocked && "cursor-pointer hover:bg-[var(--color-primary-light)]/55 hover:shadow-[inset_0_0_0_1px_var(--color-border)]",
                                              )}
                                              title={title}
                                            >
                                              {changeState ? (
                                                <span
                                                  className={cn(
                                                    "pointer-events-none absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full animate-drop-in",
                                                    changeState === "added" ? "bg-[var(--color-primary)]" : "bg-[var(--color-warning)]",
                                                  )}
                                                  aria-hidden="true"
                                                />
                                              ) : null}
                                              <div
                                                className={cn(
                                                  "mx-auto flex h-8 min-w-11 items-center justify-center gap-1 rounded-lg border border-transparent px-2 transition-all duration-150",
                                                  granted && "border-[var(--color-primary)]/10 bg-white/55",
                                                  highRisk && "border-[var(--color-warning)]/15 bg-[var(--color-warning-light)]/55",
                                                  changeState === "removed" && "border-[var(--color-warning)]/20 bg-white/65",
                                                  !isLocked && "group-hover/row:border-[var(--color-border-light)] group-hover/row:bg-white/75",
                                                )}
                                              >
                                                <CustomCheckbox
                                                  checked={granted}
                                                  disabled={!selectedRole || isLocked}
                                                  onClick={(event) => event.stopPropagation()}
                                                  onCheckedChange={() => togglePermission(permission.id)}
                                                  aria-label={`${selectedRole?.display_name ?? "角色"}：${permission.description || permission.name}`}
                                                />
                                                {highRisk ? <AlertTriangle className="h-3 w-3 shrink-0 text-[var(--color-warning)]" aria-hidden="true" /> : null}
                                              </div>
                                            </td>
                                          );
                                        })}
                                      </tr>
                                    );
                                  })}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        </div>
                      </section>
                    );
                  })
                )}
              </div>
            </div>
          </main>
        </div>
      </Card>

      <ConfirmDialog
        open={confirmOpen}
        title="确认修改角色权限"
        description={`确认更新 ${selectedRole?.display_name ?? "当前角色"} 的权限？本次将新增 ${permissionChanges.added} 项、移除 ${permissionChanges.removed} 项。保存后会立即影响对应管理员的菜单与接口访问，并写入审计日志。`}
        confirmText="确认保存"
        loading={saveMutation.isPending}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => {
          if (!selectedRole) return;
          saveMutation.mutate({ roleId: selectedRole.id, permissionIds: Array.from(activePermissionIds).sort((a, b) => a - b) });
        }}
      />
    </div>
  );
}

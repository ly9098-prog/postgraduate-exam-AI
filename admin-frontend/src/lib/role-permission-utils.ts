/**
 * Pure helpers for roles page, extracted from roles/page.tsx.
 * Covers permission-change diff computation, category-entry sorting,
 * and permission matrix/label derivations.
 */

import type { Permission } from "@/lib/api/types";

export const CATEGORY_META: Record<string, { label: string; description: string }> = {
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

export const CATEGORY_ORDER = [
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

export const ACTION_LABELS: Record<string, string> = {
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

export const ACTION_ORDER = [
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

export const RESOURCE_LABELS: Record<string, string> = {
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

export const HIGH_RISK_PERMISSION_NAMES = new Set([
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

export type MatrixRow = {
  resource: string;
  label: string;
  permissions: Permission[];
  byAction: Map<string, Permission>;
};

export type CategoryMatrix = {
  category: string;
  items: Permission[];
  rows: MatrixRow[];
  actions: string[];
};

export function categoryLabel(category: string): string {
  return CATEGORY_META[category]?.label ?? category.replaceAll("_", " ");
}

export function categoryDescription(category: string): string {
  return CATEGORY_META[category]?.description ?? "该模块下的功能访问与操作权限";
}

export function resourceLabel(resource: string): string {
  return RESOURCE_LABELS[resource] ?? resource.replaceAll(/[-_]/g, " ");
}

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action.replaceAll(/[-_]/g, " ");
}

export function actionIndex(action: string): number {
  const index = ACTION_ORDER.indexOf(action);
  return index === -1 ? Number.MAX_SAFE_INTEGER : index;
}

export function samePermissionSet(left: Iterable<number>, right: Iterable<number>): boolean {
  const leftSet = left instanceof Set ? left : new Set(left);
  const rightSet = right instanceof Set ? right : new Set(right);
  if (leftSet.size !== rightSet.size) return false;
  for (const id of leftSet) {
    if (!rightSet.has(id)) return false;
  }
  return true;
}

export function buildMatrixRows(items: Permission[]): MatrixRow[] {
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

export function permissionMatches(permission: Permission, category: string, keyword: string): boolean {
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

export type PermissionChanges = { added: number; removed: number };

/**
 * Compute the diff between original and active permission sets.
 * Returns counts of added and removed permissions.
 */
export function computePermissionChanges(
  originalIds: Set<number>,
  activeIds: Set<number>,
): PermissionChanges {
  let added = 0;
  let removed = 0;
  activeIds.forEach((id) => {
    if (!originalIds.has(id)) added += 1;
  });
  originalIds.forEach((id) => {
    if (!activeIds.has(id)) removed += 1;
  });
  return { added, removed };
}

/**
 * Sort category entries by a predefined order, falling back to locale compare.
 * Categories not in the order list are placed after known ones, sorted alphabetically.
 * Generic over the item type so callers get typed arrays back.
 */
export function sortCategoryEntries<T>(
  entries: Array<[string, T[]]>,
  categoryOrder: string[],
): Array<[string, T[]]> {
  return entries.sort(([left], [right]) => {
    const leftIndex = categoryOrder.indexOf(left);
    const rightIndex = categoryOrder.indexOf(right);
    if (leftIndex === -1 && rightIndex === -1) return left.localeCompare(right);
    if (leftIndex === -1) return 1;
    if (rightIndex === -1) return -1;
    return leftIndex - rightIndex;
  });
}

/**
 * Total permission count across all category entries.
 */
export function computeTotalPermissionCount<T>(
  entries: Array<[string, T[]]>,
): number {
  return entries.reduce((total, [, items]) => total + items.length, 0);
}

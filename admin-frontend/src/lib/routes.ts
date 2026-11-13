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
  FlaskConical,
  GitCompareArrows,
  BarChart3,
  FileSearch,
  Network,
  Activity,
  ClipboardCheck,
  BookOpen,
} from "lucide-react";
import type { ComponentType } from "react";
import type { PermissionKey } from "@/lib/permissions/permissions";

export type AdminRoute = {
  href: string;
  label: string;
  description: string;
  permission?: PermissionKey;
  /** Restrict this route to the built-in super_admin role regardless of granted permissions. */
  superAdminOnly?: boolean;
  icon: ComponentType<{ className?: string }>;
  /**
   * Optional additional pathname prefixes that should keep this navigation item active.
   * This is useful for entry pages such as /imports/tasks whose feature owns the whole
   * /imports subtree.
   */
  activePrefixes?: string[];
};

export type AdminNavigationRoute = {
  type: "route";
  route: AdminRoute;
};

export type AdminNavigationGroup = {
  type: "group";
  key: string;
  label: string;
  description: string;
  icon: ComponentType<{ className?: string }>;
  children: AdminRoute[];
};

export type AdminNavigationItem = AdminNavigationRoute | AdminNavigationGroup;

function routeMatchesPath(pathname: string, route: AdminRoute): boolean {
  if (route.href === pathname || pathname.startsWith(route.href + "/")) {
    return true;
  }

  return Boolean(
    route.activePrefixes?.some(
      (prefix) => pathname === prefix || pathname.startsWith(prefix + "/"),
    ),
  );
}

/**
 * Determine which admin route is active based on the current pathname.
 *
 * Rules:
 * 1. Path must match the route itself, one of its sub-paths, or an explicit active prefix.
 * 2. Among candidates, pick the most specific route.
 * 3. This ensures /formulas/categories matches "公式分类" rather than "公式库".
 */
export function getActiveAdminRoute(
  pathname: string,
  routes: AdminRoute[],
): AdminRoute | null {
  const candidates = routes.filter((route) => routeMatchesPath(pathname, route));
  if (candidates.length === 0) return null;

  return candidates.reduce((a, b) => {
    const aSpecificity = Math.max(
      a.href.length,
      ...(a.activePrefixes?.map((prefix) => prefix.length) ?? [0]),
    );
    const bSpecificity = Math.max(
      b.href.length,
      ...(b.activePrefixes?.map((prefix) => prefix.length) ?? [0]),
    );
    return aSpecificity >= bSpecificity ? a : b;
  });
}

const dashboardRoute: AdminRoute = {
  href: "/dashboard",
  label: "总览",
  description: "指标与趋势",
  permission: "dashboard:read",
  icon: Gauge,
};

const appUsersRoute: AdminRoute = {
  href: "/app-users",
  label: "小程序用户",
  description: "封禁与资料",
  permission: "app-user:read",
  icon: Users,
};

const adminUsersRoute: AdminRoute = {
  href: "/admin-users",
  label: "管理员",
  description: "账号与角色",
  permission: "admin-user:read",
  icon: UserCog,
};


const subjectsRoute: AdminRoute = {
  href: "/subjects",
  label: "科目治理",
  description: "科目范围与启停",
  permission: "subject:read",
  icon: ListTree,
};

const questionsRoute: AdminRoute = {
  href: "/questions",
  label: "题库",
  description: "题目治理",
  permission: "question:read",
  icon: FileQuestion,
};

const questionReviewRoute: AdminRoute = {
  href: "/review",
  label: "审核工作台",
  description: "已入库题目重审与回滚",
  permission: "question:review",
  icon: ClipboardCheck,
};

const examsRoute: AdminRoute = {
  href: "/exams",
  label: "试卷管理",
  description: "真题选择题与模拟卷",
  permission: "question:read",
  icon: ClipboardCheck,
};

const importsRoute: AdminRoute = {
  href: "/imports/tasks",
  label: "题目导入管理",
  description: "导入与审核",
  permission: "import:read",
  icon: FileInput,
  activePrefixes: ["/imports"],
};

const rolesRoute: AdminRoute = {
  href: "/roles",
  label: "角色权限",
  description: "权限矩阵",
  permission: "role:read",
  superAdminOnly: true,
  icon: ShieldCheck,
};

const aiSettingsRoute: AdminRoute = {
  href: "/ai-settings",
  label: "AI 解析设置",
  description: "开关与额度",
  permission: "ai_setting:read",
  icon: SlidersHorizontal,
};

const auditLogsRoute: AdminRoute = {
  href: "/audit-logs",
  label: "审计日志",
  description: "操作追踪",
  permission: "audit:read",
  icon: History,
};

const systemTasksRoute: AdminRoute = {
  href: "/system/tasks",
  label: "任务诊断",
  description: "队列与链路",
  permission: "import:read",
  icon: Activity,
};

const formulasRoute: AdminRoute = {
  href: "/formulas",
  label: "公式库",
  description: "公式管理与审核",
  permission: "formula:read",
  icon: Sigma,
};

const formulaCategoriesRoute: AdminRoute = {
  href: "/formulas/categories",
  label: "公式分类",
  description: "分类树管理",
  permission: "formula-category:read",
  icon: ListTree,
};

const recommendationStrategiesRoute: AdminRoute = {
  href: "/recommendation/strategies",
  label: "推荐策略",
  description: "策略权重配置",
  permission: "recommendation:read",
  icon: FlaskConical,
};

const recommendationExperimentsRoute: AdminRoute = {
  href: "/recommendation/experiments",
  label: "推荐实验",
  description: "A/B 实验管理",
  permission: "recommendation:read",
  icon: GitCompareArrows,
};

const recommendationMetricsRoute: AdminRoute = {
  href: "/recommendation/metrics",
  label: "推荐指标",
  description: "每日聚合指标",
  permission: "recommendation:read",
  icon: BarChart3,
};

const recommendationReportsRoute: AdminRoute = {
  href: "/recommendation/reports",
  label: "推荐报表",
  description: "质量与健康报告",
  permission: "recommendation:read",
  icon: FileSearch,
};

const knowledgeGraphRoute: AdminRoute = {
  href: "/knowledge-graph",
  label: "知识图谱",
  description: "关系探索与诊断",
  permission: "knowledge:read",
  icon: Network,
};

const syllabusRoute: AdminRoute = {
  href: "/syllabus",
  label: "考纲版本",
  description: "考纲与知识点版本",
  permission: "knowledge:read",
  icon: BookOpen,
};

const coverageRoute: AdminRoute = {
  href: "/coverage",
  label: "题库覆盖",
  description: "覆盖率与质量治理",
  permission: "knowledge:read",
  icon: BarChart3,
};

/**
 * Flat route list kept for route matching and permission-aware consumers.
 */
export const adminRoutes: AdminRoute[] = [
  dashboardRoute,
  appUsersRoute,
  adminUsersRoute,
  subjectsRoute,
  questionsRoute,
  questionReviewRoute,
  examsRoute,
  importsRoute,
  rolesRoute,
  aiSettingsRoute,
  auditLogsRoute,
  systemTasksRoute,
  formulasRoute,
  formulaCategoriesRoute,
  recommendationStrategiesRoute,
  recommendationExperimentsRoute,
  recommendationMetricsRoute,
  recommendationReportsRoute,
  knowledgeGraphRoute,
  syllabusRoute,
  coverageRoute,
];

/**
 * Sidebar navigation hierarchy.
 *
 * Group routes by the administrator's primary workflow so the top-level sidebar
 * stays compact while preserving every existing URL and permission check:
 * - 角色管理: 小程序用户 + 管理员 + 角色权限
 * - 题目管理: 题库 + 导入 + 知识图谱
 * - 系统管理: AI 解析设置 + 审计日志 + 任务诊断
 * - 公式管理: 公式库 + 分类
 * - 推荐管理: 策略 + 实验 + 指标 + 报表
 */
export const adminNavigation: AdminNavigationItem[] = [
  { type: "route", route: dashboardRoute },
  {
    type: "group",
    key: "role-management",
    label: "角色管理",
    description: "用户、账号与权限",
    icon: UserCog,
    children: [appUsersRoute, adminUsersRoute, rolesRoute],
  },
  {
    type: "group",
    key: "question-management",
    label: "题目管理",
    description: "科目、题库、导入、知识图谱、考纲与覆盖率",
    icon: FileQuestion,
    children: [subjectsRoute, questionsRoute, questionReviewRoute, examsRoute, importsRoute, knowledgeGraphRoute, syllabusRoute, coverageRoute],
  },
  {
    type: "group",
    key: "system-management",
    label: "系统管理",
    description: "配置、审计与任务",
    icon: SlidersHorizontal,
    children: [aiSettingsRoute, auditLogsRoute, systemTasksRoute],
  },
  {
    type: "group",
    key: "formula-management",
    label: "公式管理",
    description: "公式与分类",
    icon: Sigma,
    children: [formulasRoute, formulaCategoriesRoute],
  },
  {
    type: "group",
    key: "recommendation-management",
    label: "推荐管理",
    description: "策略、实验与指标",
    icon: FlaskConical,
    children: [
      recommendationStrategiesRoute,
      recommendationExperimentsRoute,
      recommendationMetricsRoute,
      recommendationReportsRoute,
    ],
  },
];

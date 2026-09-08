"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Layers3, ListTree, LoaderCircle, RefreshCw, Search, ShieldCheck, X } from "lucide-react";
import {
  ManagementNotice,
  ManagementPage,
  ManagementPageHeader,
  ManagementPanel,
  ManagementProgress,
  ManagementSkeletonRows,
  MetricCard,
  MetricStrip,
  StatusBadge,
} from "@/components/admin/management-ui";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Toggle } from "@/components/ui/toggle";
import { apiRequest } from "@/lib/api/client";
import type {
  AdminSubjectListResponse,
  AdminSubjectNode,
  AdminSubjectUpdateRequest,
} from "@/lib/api/types";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";

type FlatSubject = AdminSubjectNode & { depth: number };

type PendingToggle = {
  subject: AdminSubjectNode;
  nextActive: boolean;
} | null;

type ActionNotice = {
  tone: "success" | "warning" | "danger";
  title: string;
  message: string;
} | null;

function flattenSubjects(items: AdminSubjectNode[], depth = 0): FlatSubject[] {
  return items.flatMap((item) => [
    { ...item, depth },
    ...flattenSubjects(item.children || [], depth + 1),
  ]);
}

function buildSubjectRelations(items: AdminSubjectNode[]) {
  const activeDescendantsById = new Map<number, AdminSubjectNode[]>();
  const inactiveAncestorsById = new Map<number, AdminSubjectNode[]>();

  function walk(item: AdminSubjectNode, ancestors: AdminSubjectNode[]): AdminSubjectNode[] {
    inactiveAncestorsById.set(item.id, ancestors.filter((ancestor) => !ancestor.is_active));

    const activeDescendants: AdminSubjectNode[] = [];
    for (const child of item.children || []) {
      if (child.is_active) activeDescendants.push(child);
      activeDescendants.push(...walk(child, [...ancestors, item]));
    }
    activeDescendantsById.set(item.id, activeDescendants);
    return activeDescendants;
  }

  for (const item of items) walk(item, []);

  return { activeDescendantsById, inactiveAncestorsById };
}

function summarizeSubjects(subjects: AdminSubjectNode[], max = 3) {
  const names = subjects.slice(0, max).map((subject) => subject.name);
  if (subjects.length <= max) return names.join("、");
  return `${names.join("、")} 等 ${subjects.length} 个科目`;
}

function scopeLabel(subject: AdminSubjectNode) {
  if (subject.is_product_root) return "产品根科目";
  if (subject.product_scope === "exam408") return "核心科目";
  return "扩展科目";
}

function scopeTone(subject: AdminSubjectNode): "accent" | "neutral" {
  return subject.product_scope === "exam408" ? "accent" : "neutral";
}

function updateSubjectTreeStatus(items: AdminSubjectNode[], subjectId: number, isActive: boolean): AdminSubjectNode[] {
  if (!isActive) {
    return items.map((item) => ({
      ...item,
      is_active: item.id === subjectId ? false : item.is_active,
      children: updateSubjectTreeStatus(item.children || [], subjectId, false),
    }));
  }

  function activatePath(item: AdminSubjectNode): [AdminSubjectNode, boolean] {
    const childResults = (item.children || []).map(activatePath);
    const containsTarget = item.id === subjectId || childResults.some(([, contains]) => contains);
    return [
      {
        ...item,
        is_active: containsTarget ? true : item.is_active,
        children: childResults.map(([child]) => child),
      },
      containsTarget,
    ];
  }

  return items.map((item) => activatePath(item)[0]);
}

export default function SubjectsPage() {
  const queryClient = useQueryClient();
  const permissions = useAuthStore((state) => state.permissions);
  const canWrite = hasPermission(permissions, "subject:write");
  const [pendingToggle, setPendingToggle] = useState<PendingToggle>(null);
  const [actionNotice, setActionNotice] = useState<ActionNotice>(null);
  const [blockedSubjectId, setBlockedSubjectId] = useState<number | null>(null);
  const [keyword, setKeyword] = useState("");

  const query = useQuery({
    queryKey: ["subjects", "include-inactive"],
    queryFn: () => apiRequest<AdminSubjectListResponse>("/subjects?include_inactive=true"),
  });

  const mutation = useMutation({
    mutationFn: async ({ subject, nextActive }: Exclude<PendingToggle, null>) => {
      const body: AdminSubjectUpdateRequest = { is_active: nextActive };
      if (subject.is_product_root && !nextActive) body.confirm_core_disable = true;
      return apiRequest<AdminSubjectNode>(`/subjects/${subject.id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
    },
    onMutate: async ({ subject, nextActive }) => {
      await queryClient.cancelQueries({ queryKey: ["subjects", "include-inactive"] });
      const previous = queryClient.getQueryData<AdminSubjectListResponse>(["subjects", "include-inactive"]);
      const inactiveAncestors = previous
        ? buildSubjectRelations(previous.items).inactiveAncestorsById.get(subject.id) || []
        : [];

      if (previous) {
        queryClient.setQueryData<AdminSubjectListResponse>(["subjects", "include-inactive"], {
          ...previous,
          items: updateSubjectTreeStatus(previous.items, subject.id, nextActive),
        });
      }
      return { previous, inactiveAncestors };
    },
    onError: (_error, variables, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["subjects", "include-inactive"], context.previous);
      }
      setPendingToggle(null);
      setActionNotice({
        tone: "danger",
        title: `未能${variables.nextActive ? "启用" : "停用"}「${variables.subject.name}」`,
        message: "界面状态已恢复，请刷新数据后重试；如果问题持续，请检查当前账号权限与接口状态。",
      });
    },
    onSuccess: (_data, variables, context) => {
      setPendingToggle(null);
      const autoEnabledAncestors = variables.nextActive ? context?.inactiveAncestors || [] : [];
      setActionNotice({
        tone: "success",
        title: `已${variables.nextActive ? "启用" : "停用"}「${variables.subject.name}」`,
        message:
          autoEnabledAncestors.length > 0
            ? `同时自动启用了上级科目：${summarizeSubjects(autoEnabledAncestors)}。`
            : variables.nextActive
              ? "科目已恢复到可用范围。"
              : "该节点已停用，历史题目与学习记录不会被删除。",
      });
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["subjects"] });
    },
  });

  const flat = useMemo(() => flattenSubjects(query.data?.items || []), [query.data]);
  const productRoot = flat.find((item) => item.is_product_root);
  const coreSubjects = flat.filter((item) => item.product_scope === "exam408" && !item.is_product_root);
  const activeCoreCount = coreSubjects.filter((item) => item.is_active).length;
  const inactiveSubjectCount = flat.filter((item) => !item.is_active).length;
  const scopeReady = Boolean(productRoot?.is_active) && activeCoreCount >= 4;
  const normalizedKeyword = keyword.trim().toLowerCase();
  const filteredFlat = useMemo(() => {
    if (!normalizedKeyword) return flat;
    return flat.filter((subject) => `${subject.name} ${subject.code} ${subject.path}`.toLowerCase().includes(normalizedKeyword));
  }, [flat, normalizedKeyword]);
  const { activeDescendantsById } = useMemo(() => buildSubjectRelations(query.data?.items || []), [query.data]);

  useEffect(() => {
    if (!actionNotice) return;

    const dismissDelay =
      actionNotice.tone === "danger"
        ? 6500
        : actionNotice.tone === "warning"
          ? 5200
          : 3600;
    const timer = window.setTimeout(() => setActionNotice(null), dismissDelay);
    return () => window.clearTimeout(timer);
  }, [actionNotice]);

  useEffect(() => {
    if (blockedSubjectId === null) return;
    const timer = window.setTimeout(() => setBlockedSubjectId(null), 1800);
    return () => window.clearTimeout(timer);
  }, [blockedSubjectId]);

  function requestToggle(subject: AdminSubjectNode) {
    if (!canWrite || mutation.isPending) return;
    const nextActive = !subject.is_active;
    const activeDescendants = activeDescendantsById.get(subject.id) || [];

    setActionNotice(null);

    if (!nextActive && activeDescendants.length > 0) {
      setBlockedSubjectId(subject.id);
      setActionNotice({
        tone: "warning",
        title: `暂时不能停用「${subject.name}」`,
        message: `请先停用其全部下级科目。当前仍有 ${activeDescendants.length} 个下级处于启用状态：${summarizeSubjects(activeDescendants)}。`,
      });
      return;
    }

    if (subject.is_product_root && !nextActive) {
      setPendingToggle({ subject, nextActive });
      return;
    }
    mutation.mutate({ subject, nextActive });
  }

  return (
    <ManagementPage>
      <ManagementPageHeader
        icon={<ListTree className="h-5 w-5" />}
        title="科目治理"
        description="维护产品科目树与启停边界。启停只影响当前产品入口和可选范围，不删除历史题目、练习记录与错题数据。"
        meta={
          <>
            <StatusBadge tone={scopeReady ? "success" : "warning"}>{scopeReady ? "产品范围完整" : "范围需要检查"}</StatusBadge>
            <span>{canWrite ? "可编辑启停状态" : "当前账号仅可查看"}</span>
          </>
        }
        actions={
          <Button variant="secondary" onClick={() => query.refetch()} disabled={query.isFetching}>
            <RefreshCw className={`h-4 w-4 ${query.isFetching ? "animate-spin" : ""}`} />
            刷新
          </Button>
        }
      />

      <MetricStrip className="sm:grid-cols-3">
        <MetricCard
          label="核心科目启用"
          value={`${activeCoreCount}/4`}
          hint="数据结构、组成原理、操作系统、计算机网络"
          tone={activeCoreCount === 4 ? "success" : "warning"}
          progress={(activeCoreCount / 4) * 100}
          icon={<ShieldCheck className="h-4 w-4" />}
        />
        <MetricCard
          label="产品根科目"
          value={productRoot?.is_active ? "启用" : "关闭"}
          hint={productRoot?.name ?? "未找到产品根科目"}
          tone={productRoot?.is_active ? "success" : "warning"}
          icon={<Layers3 className="h-4 w-4" />}
        />
        <MetricCard
          label="当前停用科目"
          value={inactiveSubjectCount}
          hint="可按业务需要重新启用，历史数据始终保留"
        />
      </MetricStrip>

      {!scopeReady && !query.isLoading ? (
        <ManagementNotice tone="warning" title="产品科目范围不完整">
          请确认根科目处于启用状态，并检查数据结构、计算机组成原理、操作系统、计算机网络四个核心科目是否全部启用。
        </ManagementNotice>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_332px] xl:items-start">
        <ManagementPanel
          variant="focus"
          title="科目目录"
          description={normalizedKeyword ? `正在显示 ${filteredFlat.length} / ${flat.length} 个匹配节点` : "按层级查看科目树。启用子科目会自动补齐上级状态；父科目只有在全部下级停用后才能关闭。"}
          actions={
            <label className="relative block w-full sm:w-72">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
              <Input
                className={`h-9 bg-white pl-9 ${keyword ? "pr-9" : "pr-3"}`}
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                placeholder="搜索科目、编码或路径"
                aria-label="搜索科目"
              />
              {keyword ? (
                <button
                  type="button"
                  onClick={() => setKeyword("")}
                  className="absolute right-2 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-md text-[var(--color-text-hint)] transition-colors hover:bg-[var(--mgmt-steel)] hover:text-[var(--ink)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] motion-reduce:transition-none"
                  aria-label="清空搜索"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </label>
          }
          contentClassName="p-0"
        >
          {query.isLoading ? (
            <ManagementSkeletonRows rows={6} />
          ) : query.isError ? (
            <div className="px-6 py-16 text-center text-sm text-red-600">科目加载失败，请刷新重试。</div>
          ) : filteredFlat.length === 0 ? (
            <div className="px-6 py-16 text-center text-sm text-[var(--color-text-secondary)]">没有匹配的科目。尝试缩短关键词或清空搜索。</div>
          ) : (
            <div role="tree" aria-label="科目目录">
              <div className="grid grid-cols-[minmax(0,1fr)_104px] border-b border-[var(--mgmt-line)] bg-[rgba(237,243,246,0.55)] px-5 py-2.5 text-[11px] font-semibold text-[var(--color-text-tertiary)] sm:grid-cols-[minmax(0,1fr)_130px_160px]">
                <span>科目与层级</span>
                <span className="hidden sm:block">范围</span>
                <span className="text-right">状态</span>
              </div>
              <div className="divide-y divide-[var(--mgmt-line)]">
                {filteredFlat.map((subject) => {
                  const editable = canWrite;
                  const isUpdating = mutation.isPending && mutation.variables?.subject.id === subject.id;
                  const activeDescendants = activeDescendantsById.get(subject.id) || [];
                  const hasActiveDescendants = subject.is_active && activeDescendants.length > 0;
                  const toggleHint = !editable
                    ? "当前账号没有科目写入权限"
                    : mutation.isPending && !isUpdating
                      ? "正在保存另一项科目变更，请稍候"
                      : hasActiveDescendants
                        ? `需先停用全部下级科目（当前 ${activeDescendants.length} 个下级在线）`
                        : subject.is_active
                          ? "停用该科目"
                          : "启用该科目";
                  return (
                    <div
                      key={subject.id}
                      role="treeitem"
                      aria-level={subject.depth + 1}
                      aria-label={`${subject.name}，${subject.is_active ? "已启用" : "已停用"}`}
                      className={`group grid grid-cols-[minmax(0,1fr)_104px] items-center gap-3 px-5 py-3.5 transition-[background-color,box-shadow,transform] duration-200 motion-reduce:transition-none sm:grid-cols-[minmax(0,1fr)_130px_160px] ${
                        blockedSubjectId === subject.id
                          ? "bg-amber-50/70 shadow-[inset_3px_0_0_rgba(217,119,6,0.72)]"
                          : subject.is_product_root
                            ? "bg-[rgba(237,243,246,0.48)]"
                            : "hover:bg-[rgba(237,243,246,0.36)]"
                      }`}
                    >
                      <div className="min-w-0" style={{ paddingLeft: `${subject.depth * 24}px` }}>
                        <div className="relative flex min-w-0 items-center gap-3">
                          {subject.depth > 0 ? (
                            <>
                              <span className="absolute -left-4 -top-5 bottom-1/2 w-px bg-[var(--mgmt-line)]" aria-hidden="true" />
                              <span className="absolute -left-4 top-1/2 h-px w-3 bg-[var(--mgmt-line)]" aria-hidden="true" />
                            </>
                          ) : null}
                          <span
                            className={`relative h-2.5 w-2.5 shrink-0 rounded-full border transition-[background-color,border-color,box-shadow] duration-200 ${
                              subject.is_active
                                ? "border-[var(--color-primary)] bg-[var(--color-primary)] shadow-[0_0_0_3px_rgba(74,111,138,0.10)]"
                                : "border-slate-300 bg-white"
                            }`}
                            aria-hidden="true"
                          />
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="truncate text-sm font-semibold leading-5 text-[var(--ink)]">{subject.name}</span>
                              {isUpdating ? <StatusBadge tone="accent"><LoaderCircle className="h-3 w-3 animate-spin" />更新中</StatusBadge> : !subject.is_active ? <StatusBadge tone="warning">已停用</StatusBadge> : null}
                            </div>
                            <p className="mt-1 truncate text-[11px] leading-4 text-[var(--color-text-tertiary)]" title={subject.path}>
                              <span>{subject.code}</span>
                              <span className="mx-1.5 text-slate-300">/</span>
                              L{subject.level} · 排序 {subject.sort_order} · {subject.path}
                            </p>
                          </div>
                        </div>
                      </div>
                      <div className="hidden sm:block">
                        <StatusBadge tone={scopeTone(subject)}>{scopeLabel(subject)}</StatusBadge>
                      </div>
                      <div className="flex items-center justify-end gap-3">
                        {hasActiveDescendants ? (
                          <span className="hidden whitespace-nowrap text-[10px] font-medium text-[var(--color-text-tertiary)] xl:inline">
                            {activeDescendants.length} 个下级在线
                          </span>
                        ) : null}
                        <div className="shrink-0" title={toggleHint}>
                          <Toggle
                            checked={subject.is_active}
                            disabled={!editable || mutation.isPending}
                            onChange={() => requestToggle(subject)}
                          />
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </ManagementPanel>

        <div className="space-y-5 xl:sticky xl:top-5">
          <ManagementPanel
            variant="quiet"
            title="范围健康度"
            description="核心科目全部在线时，产品范围才视为完整。"
            icon={<CircleCheck className="h-4 w-4" />}
          >
            <div className="flex items-end justify-between gap-4">
              <div>
                <p className="text-[28px] font-semibold leading-none tracking-[-0.04em] tabular-nums text-[var(--ink)]">{activeCoreCount}<span className="ml-1 text-sm font-medium text-[var(--color-text-tertiary)]">/ 4</span></p>
                <p className="mt-2 text-xs text-[var(--color-text-secondary)]">核心科目已启用</p>
              </div>
              <StatusBadge tone={scopeReady ? "success" : "warning"}>{scopeReady ? "完整" : "待修复"}</StatusBadge>
            </div>
            <ManagementProgress className="mt-4" value={activeCoreCount} max={4} tone={activeCoreCount === 4 ? "success" : "warning"} />
            <div className="mt-4 divide-y divide-[var(--mgmt-line)] border-y border-[var(--mgmt-line)]">
              {coreSubjects.slice(0, 4).map((subject) => (
                <div key={subject.id} className="flex items-center justify-between gap-3 py-2.5 text-sm">
                  <span className="min-w-0 truncate text-[var(--color-text-secondary)]">{subject.name}</span>
                  <StatusBadge tone={subject.is_active ? "success" : "warning"}>{subject.is_active ? "在线" : "停用"}</StatusBadge>
                </div>
              ))}
            </div>
          </ManagementPanel>

          <ManagementPanel title="治理边界" description="启停影响产品可见范围，但不改变历史数据归属。" icon={<ShieldCheck className="h-4 w-4" />}>
            <div className="space-y-4 text-sm leading-6 text-[var(--color-text-secondary)]">
              <div className="border-l-2 border-[var(--color-primary)] pl-3">
                <p className="font-semibold text-[var(--ink)]">根科目控制产品入口</p>
                <p className="mt-1">关闭根科目会整体隐藏相关刷题入口，因此需要二次确认。</p>
              </div>
              <div className="border-l-2 border-[var(--mgmt-line)] pl-3">
                <p className="font-semibold text-[var(--ink)]">父级停用受下级状态保护</p>
                <p className="mt-1">只要任意下级仍在线，父科目的停用操作就会被拦截；请从最末级开始逐层停用。</p>
              </div>
              <div className="border-l-2 border-[var(--mgmt-line)] pl-3">
                <p className="font-semibold text-[var(--ink)]">子科目启用会补齐上级状态</p>
                <p className="mt-1">重新启用任意子科目时，系统会自动启用其父级及更高层级，避免出现“子级在线、父级关闭”的不可达状态。</p>
              </div>
            </div>
          </ManagementPanel>

          <ManagementPanel variant="quiet" title="当前写入权限">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-sm font-semibold text-[var(--ink)]">{canWrite ? "允许变更" : "只读模式"}</p>
                <p className="mt-1 text-xs leading-5 text-[var(--color-text-secondary)]">
                  {canWrite ? "所有科目的启停操作都会立即写入，并在失败时自动回滚界面状态。" : "需要 subject:write 权限才能调整启停状态。"}
                </p>
              </div>
              <StatusBadge tone={canWrite ? "success" : "neutral"}>{canWrite ? "可写" : "只读"}</StatusBadge>
            </div>
          </ManagementPanel>
        </div>
      </div>

      {actionNotice ? (
        <div
          className="pointer-events-none fixed inset-x-4 bottom-5 z-[70] sm:left-auto sm:right-6 sm:w-[420px]"
          role={actionNotice.tone === "warning" || actionNotice.tone === "danger" ? "alert" : "status"}
          aria-live={actionNotice.tone === "warning" || actionNotice.tone === "danger" ? "assertive" : "polite"}
        >
          <div className="pointer-events-auto relative">
            <ManagementNotice
              tone={actionNotice.tone}
              title={actionNotice.title}
              className="pr-12 shadow-[0_18px_50px_rgba(15,23,42,0.16)] ring-1 ring-black/[0.03] backdrop-blur-sm"
            >
              {actionNotice.message}
            </ManagementNotice>
            <button
              type="button"
              onClick={() => setActionNotice(null)}
              className="absolute right-2.5 top-2.5 grid h-7 w-7 place-items-center rounded-lg text-current opacity-55 transition-[background-color,opacity,transform] duration-150 hover:bg-black/[0.06] hover:opacity-90 active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-current focus-visible:ring-offset-1 motion-reduce:transition-none"
              aria-label="关闭操作提示"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      ) : null}

      <ConfirmDialog
        open={Boolean(pendingToggle)}
        title="确认停用产品根科目？"
        description="停用后，相关刷题与主入口将整体隐藏。历史数据不会删除，可随时重新启用。"
        confirmText="确认停用"
        danger
        loading={mutation.isPending}
        onCancel={() => setPendingToggle(null)}
        onConfirm={() => pendingToggle && mutation.mutate(pendingToggle)}
      />
    </ManagementPage>
  );
}

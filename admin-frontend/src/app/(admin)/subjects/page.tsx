"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Layers3, ListTree, RefreshCw, ShieldCheck } from "lucide-react";
import {
  ManagementNotice,
  ManagementPage,
  ManagementPageHeader,
  ManagementPanel,
  MetricCard,
  MetricStrip,
  StatusBadge,
} from "@/components/admin/management-ui";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
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

function flattenSubjects(items: AdminSubjectNode[], depth = 0): FlatSubject[] {
  return items.flatMap((item) => [
    { ...item, depth },
    ...flattenSubjects(item.children || [], depth + 1),
  ]);
}

function scopeLabel(subject: AdminSubjectNode) {
  if (subject.is_product_root) return "产品根科目";
  if (subject.product_scope === "exam408") return "核心科目";
  return "保留科目";
}

function scopeTone(subject: AdminSubjectNode): "accent" | "neutral" {
  return subject.product_scope === "exam408" ? "accent" : "neutral";
}

export default function SubjectsPage() {
  const queryClient = useQueryClient();
  const permissions = useAuthStore((state) => state.permissions);
  const canWrite = hasPermission(permissions, "subject:write");
  const [pendingToggle, setPendingToggle] = useState<PendingToggle>(null);

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
    onSuccess: async () => {
      setPendingToggle(null);
      await queryClient.invalidateQueries({ queryKey: ["subjects"] });
    },
  });

  const flat = useMemo(() => flattenSubjects(query.data?.items || []), [query.data]);
  const root408 = flat.find((item) => item.is_product_root);
  const core408 = flat.filter((item) => item.product_scope === "exam408" && !item.is_product_root);
  const activeCoreCount = core408.filter((item) => item.is_active).length;
  const inactiveReservedCount = flat.filter(
    (item) => item.product_scope !== "exam408" && !item.is_active,
  ).length;
  const scopeReady = Boolean(root408?.is_active) && activeCoreCount >= 4;

  function requestToggle(subject: AdminSubjectNode) {
    if (!canWrite || mutation.isPending) return;
    const nextActive = !subject.is_active;
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
          icon={<ShieldCheck className="h-4 w-4" />}
        />
        <MetricCard
          label="产品根科目"
          value={root408?.is_active ? "启用" : "关闭"}
          hint={root408?.name ?? "未找到产品根科目"}
          tone={root408?.is_active ? "success" : "warning"}
          icon={<Layers3 className="h-4 w-4" />}
        />
        <MetricCard
          label="停用保留科目"
          value={inactiveReservedCount}
          hint="历史数据继续保留，不进入当前产品范围"
        />
      </MetricStrip>

      {!scopeReady && !query.isLoading ? (
        <ManagementNotice tone="warning" title="产品科目范围不完整">
          请确认根科目处于启用状态，并检查数据结构、计算机组成原理、操作系统、计算机网络四个核心科目是否全部启用。
        </ManagementNotice>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px] xl:items-start">
        <ManagementPanel
          variant="focus"
          title="科目目录"
          description="按层级查看产品科目树。核心范围支持启停，保留科目保持只读。"
          actions={<StatusBadge tone="neutral">{flat.length} 个节点</StatusBadge>}
          contentClassName="p-0"
        >
          {query.isLoading ? (
            <div className="px-6 py-16 text-center text-sm text-[var(--color-text-secondary)]">正在加载科目...</div>
          ) : query.isError ? (
            <div className="px-6 py-16 text-center text-sm text-red-600">科目加载失败，请刷新重试。</div>
          ) : flat.length === 0 ? (
            <div className="px-6 py-16 text-center text-sm text-[var(--color-text-secondary)]">暂无科目数据。</div>
          ) : (
            <div>
              <div className="grid grid-cols-[minmax(0,1fr)_104px] border-b border-[var(--mgmt-line)] bg-slate-50/55 px-5 py-2.5 text-[11px] font-semibold text-[var(--color-text-tertiary)] sm:grid-cols-[minmax(0,1fr)_130px_104px]">
                <span>科目与层级</span>
                <span className="hidden sm:block">范围</span>
                <span className="text-right">状态</span>
              </div>
              <div className="divide-y divide-[var(--mgmt-line)]">
                {flat.map((subject) => {
                  const editable = canWrite && subject.product_scope === "exam408";
                  return (
                    <div
                      key={subject.id}
                      className={`group grid grid-cols-[minmax(0,1fr)_104px] items-center gap-3 px-5 py-3.5 transition-colors sm:grid-cols-[minmax(0,1fr)_130px_104px] ${
                        subject.is_product_root ? "bg-[rgba(237,243,246,0.45)]" : "hover:bg-slate-50/55"
                      }`}
                    >
                      <div className="min-w-0" style={{ paddingLeft: `${subject.depth * 24}px` }}>
                        <div className="relative flex min-w-0 items-center gap-3">
                          {subject.depth > 0 ? (
                            <span className="absolute -left-4 top-1/2 h-px w-3 bg-[var(--mgmt-line)]" aria-hidden="true" />
                          ) : null}
                          <span
                            className={`h-2 w-2 shrink-0 rounded-full border ${
                              subject.is_active
                                ? "border-[var(--color-primary)] bg-[var(--color-primary)]"
                                : "border-slate-300 bg-white"
                            }`}
                            aria-hidden="true"
                          />
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="truncate text-sm font-semibold text-[var(--ink)]">{subject.name}</span>
                              {!subject.is_active ? <StatusBadge tone="warning">已停用</StatusBadge> : null}
                            </div>
                            <p className="mt-1 truncate text-[11px] leading-4 text-[var(--color-text-tertiary)]" title={subject.path}>
                              <span className="font-mono">{subject.code}</span>
                              <span className="mx-1.5 text-slate-300">/</span>
                              L{subject.level} · 排序 {subject.sort_order} · {subject.path}
                            </p>
                          </div>
                        </div>
                      </div>
                      <div className="hidden sm:block">
                        <StatusBadge tone={scopeTone(subject)}>{scopeLabel(subject)}</StatusBadge>
                      </div>
                      <div className="flex justify-end">
                        <Toggle
                          checked={subject.is_active}
                          disabled={!editable || mutation.isPending}
                          onChange={() => requestToggle(subject)}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </ManagementPanel>

        <div className="space-y-5 xl:sticky xl:top-5">
          <ManagementPanel title="治理边界" description="这些规则用于避免历史科目误进入当前产品范围。" icon={<ShieldCheck className="h-4 w-4" />}>
            <div className="space-y-4 text-sm leading-6 text-[var(--color-text-secondary)]">
              <div className="border-l-2 border-[var(--color-primary)] pl-3">
                <p className="font-semibold text-[var(--ink)]">根科目控制产品入口</p>
                <p className="mt-1">关闭根科目会整体隐藏相关刷题入口，因此需要二次确认。</p>
              </div>
              <div className="border-l-2 border-[var(--mgmt-line)] pl-3">
                <p className="font-semibold text-[var(--ink)]">核心科目可独立启停</p>
                <p className="mt-1">适用于临时下线、内容修订或灰度恢复，不影响已有学习记录。</p>
              </div>
              <div className="border-l-2 border-[var(--mgmt-line)] pl-3">
                <p className="font-semibold text-[var(--ink)]">保留科目不在此处恢复</p>
                <p className="mt-1">未来扩科应通过独立迁移重新纳入产品范围，避免误开放历史数据。</p>
              </div>
            </div>
          </ManagementPanel>

          <ManagementPanel variant="quiet" title="当前写入权限">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-sm font-semibold text-[var(--ink)]">{canWrite ? "允许变更" : "只读模式"}</p>
                <p className="mt-1 text-xs leading-5 text-[var(--color-text-secondary)]">
                  {canWrite ? "核心范围中的开关操作会立即写入。" : "需要 subject:write 权限才能调整启停状态。"}
                </p>
              </div>
              <StatusBadge tone={canWrite ? "success" : "neutral"}>{canWrite ? "可写" : "只读"}</StatusBadge>
            </div>
          </ManagementPanel>
        </div>
      </div>

      {mutation.isError ? (
        <ManagementNotice tone="danger" title="科目状态更新失败">
          请刷新数据后重试；如果问题持续，请检查当前账号权限与接口状态。
        </ManagementNotice>
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

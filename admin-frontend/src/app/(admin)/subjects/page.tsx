"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ListTree, RefreshCw, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
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
  if (subject.is_product_root) return "408 根科目";
  if (subject.product_scope === "408") return "408 核心";
  return "保留科目";
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
  const core408 = flat.filter((item) => item.product_scope === "408" && !item.is_product_root);
  const activeCoreCount = core408.filter((item) => item.is_active).length;
  const inactiveReservedCount = flat.filter(
    (item) => item.product_scope !== "408" && !item.is_active,
  ).length;

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
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-[var(--color-primary)]">408-BASE</p>
          <h1 className="font-display text-3xl font-bold text-[var(--ink)]">科目治理</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--color-text-secondary)]">
            当前产品只开放 408 根科目及四个核心科目。数学、英语、政治等历史科目保留在数据库中，可在这里启停，但不会作为小程序主学习入口。
          </p>
        </div>
        <Button variant="secondary" onClick={() => query.refetch()} disabled={query.isFetching}>
          <RefreshCw className={`mr-2 h-4 w-4 ${query.isFetching ? "animate-spin" : ""}`} />
          刷新
        </Button>
      </div>

      {(!root408 || !root408.is_active || activeCoreCount < 4) && !query.isLoading ? (
        <div className="flex gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
          <div>
            <p className="font-semibold">408 产品范围不完整</p>
            <p className="mt-1 leading-6">
              请确认 408 根科目处于启用状态，并检查数据结构、计算机组成原理、操作系统、计算机网络四个核心科目。
            </p>
          </div>
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="flex items-center gap-4">
            <div className="rounded-2xl bg-blue-50 p-3 text-blue-700"><ListTree className="h-5 w-5" /></div>
            <div><p className="text-2xl font-bold">{activeCoreCount}/4</p><p className="text-sm text-[var(--color-text-secondary)]">启用的 408 核心科目</p></div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-4">
            <div className="rounded-2xl bg-emerald-50 p-3 text-emerald-700"><ShieldCheck className="h-5 w-5" /></div>
            <div><p className="text-2xl font-bold">{root408?.is_active ? "正常" : "关闭"}</p><p className="text-sm text-[var(--color-text-secondary)]">408 根科目入口</p></div>
          </CardContent>
        </Card>
        <Card>
          <CardContent>
            <p className="text-2xl font-bold">{inactiveReservedCount}</p>
            <p className="text-sm text-[var(--color-text-secondary)]">已停用的保留科目</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="font-display text-xl font-bold text-[var(--ink)]">全部科目</h2>
              <p className="mt-1 text-sm text-[var(--color-text-secondary)]">启停不会删除历史题目、练习记录或错题数据。</p>
            </div>
            {!canWrite ? <span className="text-xs text-[var(--color-text-tertiary)]">当前账号仅可查看</span> : null}
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {query.isLoading ? (
            <div className="px-6 py-12 text-center text-sm text-[var(--color-text-secondary)]">正在加载科目...</div>
          ) : query.isError ? (
            <div className="px-6 py-12 text-center text-sm text-red-600">科目加载失败，请刷新重试。</div>
          ) : flat.length === 0 ? (
            <div className="px-6 py-12 text-center text-sm text-[var(--color-text-secondary)]">暂无科目数据。</div>
          ) : (
            <div className="divide-y divide-[var(--color-border)]">
              {flat.map((subject) => (
                <div key={subject.id} className="flex items-center gap-4 px-6 py-4">
                  <div className="min-w-0 flex-1" style={{ paddingLeft: `${subject.depth * 24}px` }}>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-[var(--ink)]">{subject.name}</span>
                      <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${subject.product_scope === "408" ? "bg-blue-50 text-blue-700" : "bg-slate-100 text-slate-600"}`}>
                        {scopeLabel(subject)}
                      </span>
                      {!subject.is_active ? <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-700">已停用</span> : null}
                    </div>
                    <p className="mt-1 truncate font-mono text-xs text-[var(--color-text-tertiary)]">{subject.code} · L{subject.level} · sort {subject.sort_order} · {subject.path}</p>
                  </div>
                  <Toggle
                    checked={subject.is_active}
                    disabled={!canWrite || mutation.isPending}
                    onChange={() => requestToggle(subject)}
                  />
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {mutation.isError ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          科目状态更新失败，请刷新后重试。
        </div>
      ) : null}

      <ConfirmDialog
        open={Boolean(pendingToggle)}
        title="确认停用 408 根科目？"
        description="停用后，小程序的 408 刷题与相关主入口将整体隐藏。历史数据不会删除，可随时重新启用。"
        confirmText="确认停用"
        danger
        loading={mutation.isPending}
        onCancel={() => setPendingToggle(null)}
        onConfirm={() => pendingToggle && mutation.mutate(pendingToggle)}
      />
    </div>
  );
}

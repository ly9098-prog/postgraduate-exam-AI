"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, CheckCircle2, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { DataTable } from "@/components/data-table/data-table";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { apiRequest, toQuery } from "@/lib/api/client";
import type { AppUser, PaginatedResponse } from "@/lib/api/types";

type ConfirmState = { id: number; banned: boolean; name: string } | null;

export default function AppUsersPage() {
  const queryClient = useQueryClient();
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [confirmState, setConfirmState] = useState<ConfirmState>(null);
  const [banReason, setBanReason] = useState("后台人工封禁");
  const [message, setMessage] = useState<string | null>(null);

  const users = useQuery({
    queryKey: ["app-users", page, keyword],
    queryFn: () => apiRequest<PaginatedResponse<AppUser>>(`/app-users${toQuery({ page, page_size: 20, keyword })}`),
  });

  const banMutation = useMutation({
    mutationFn: ({ id, banned }: { id: number; banned: boolean }) =>
      apiRequest(`/app-users/${id}/${banned ? "unban" : "ban"}`, {
        method: "POST",
        body: banned ? undefined : JSON.stringify({ reason: banReason }),
      }),
    onSuccess: (_result, variables) => {
      setMessage(variables.banned ? "解封成功。" : "封禁成功。");
      setConfirmState(null);
      queryClient.invalidateQueries({ queryKey: ["app-users"] });
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "操作失败，请稍后重试。");
    },
  });

  const columns = useMemo(
    () => [
      { header: "ID", accessorKey: "id" },
      {
        header: "用户",
        cell: ({ row }: { row: { original: AppUser } }) => (
          <div>
            <div className="font-semibold text-[var(--ink)]">{row.original.nickname || "未设置昵称"}</div>
            <div className="font-mono text-xs text-[var(--color-text-hint)]">{row.original.openid}</div>
          </div>
        ),
      },
      { header: "封禁原因", accessorKey: "banned_reason" },
      {
        header: "状态",
        cell: ({ row }) => <StatusBadge tone={row.original.is_banned ? "danger" : "success"}>{row.original.is_banned ? "已封禁" : "正常"}</StatusBadge>,
      },
      {
        header: "操作",
        cell: ({ row }: { row: { original: AppUser } }) => (
          <Button
            variant={row.original.is_banned ? "secondary" : "danger"}
            disabled={banMutation.isPending}
            onClick={() => setConfirmState({ id: row.original.id, banned: row.original.is_banned, name: row.original.nickname || row.original.openid })}
          >
            {row.original.is_banned ? <CheckCircle2 className="h-4 w-4" /> : <Ban className="h-4 w-4" />}
            {row.original.is_banned ? "解封" : "封禁"}
          </Button>
        ),
      },
    ],
    [banMutation.isPending],
  );

  return (
    <div className="space-y-6">
      <div>
        <p className="font-mono text-xs uppercase tracking-[0.3em] text-[var(--color-text-hint)]">App Users</p>
        <h2 className="mt-2 font-display text-4xl font-bold text-[var(--ink)]">小程序用户</h2>
      </div>
      <Card>
        <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="font-display text-2xl font-bold text-[var(--ink)]">用户列表</h3>
            <p className="mt-1 text-sm text-[var(--color-text-secondary)]">分页、搜索、封禁与解封操作。</p>
          </div>
          <label className="relative w-full max-w-sm">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
            <Input className="pl-9" placeholder="搜索 openid / 昵称" value={keyword} onChange={(event) => { setKeyword(event.target.value); setPage(1); }} />
          </label>
        </CardHeader>
        <CardContent>
          {message ? <p className="mb-4 rounded-2xl border border-[var(--color-border)] bg-white/70 px-4 py-3 text-sm text-[var(--color-text-secondary)]">{message}</p> : null}
          <DataTable data={users.data?.items ?? []} columns={columns} emptyText={users.isError ? "接口暂不可用" : "暂无用户"} />
          <div className="mt-4 flex items-center justify-between text-sm text-[var(--color-text-secondary)]">
            <span>共 {users.data?.total ?? 0} 条</span>
            <div className="flex gap-2">
              <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>上一页</Button>
              <Button variant="secondary" disabled={page >= (users.data?.total_pages ?? 1)} onClick={() => setPage((value) => value + 1)}>下一页</Button>
            </div>
          </div>
        </CardContent>
      </Card>
      <ConfirmDialog
        open={confirmState !== null}
        title={confirmState?.banned ? "确认解封用户" : "确认封禁用户"}
        description={`即将${confirmState?.banned ? "解封" : "封禁"} ${confirmState?.name ?? "该用户"}。`}
        confirmText={confirmState?.banned ? "解封" : "封禁"}
        danger={!confirmState?.banned}
        loading={banMutation.isPending}
        onCancel={() => setConfirmState(null)}
        onConfirm={() => {
          if (!confirmState) return;
          banMutation.mutate({ id: confirmState.id, banned: confirmState.banned });
        }}
      />
      {confirmState && !confirmState.banned ? (
        <div className="fixed inset-x-0 bottom-6 z-[60] mx-auto w-full max-w-md px-4">
          <textarea
            className="min-h-24 w-full rounded-2xl border border-[var(--color-border)] bg-white p-3 text-sm outline-none focus:border-[var(--color-primary)]"
            placeholder="请输入封禁原因"
            value={banReason}
            onChange={(event) => setBanReason(event.target.value)}
          />
        </div>
      ) : null}
    </div>
  );
}

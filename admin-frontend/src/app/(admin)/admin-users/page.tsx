"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Edit3, Plus, RefreshCw, Search, ShieldAlert, Trash2 } from "lucide-react";
import { useMemo, useState, useCallback } from "react";
import { DataTable } from "@/components/data-table/data-table";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { hasPermission, type PermissionKey } from "@/lib/permissions/permissions";
import { apiRequest, toQuery } from "@/lib/api/client";
import { useAuthStore } from "@/lib/auth/auth-store";
import type { AdminUserCreateRequest, AdminUserPatchRequest, AdminUserSummary, PaginatedResponse, Role } from "@/lib/api/types";

type TableColumn<TData> = {
  id?: string;
  header?: React.ReactNode | (() => React.ReactNode);
  accessorKey?: keyof TData | string;
  cell?: (context: { row: { original: TData } }) => React.ReactNode;
};

type ConfirmState = { action: "delete" | "force-logout" | "reset-password"; userId: number; userName: string } | null;
type FormState = { id?: number; username: string; password: string; display_name: string; email: string; role_id: string; is_active: boolean };

const emptyForm: FormState = { username: "", password: "", display_name: "", email: "", role_id: "", is_active: true };

const columnsDef = (
  onConfirm: (state: Exclude<ConfirmState, null>) => void,
  onEdit: (user: AdminUserSummary) => void,
  isSuperAdmin: (user: AdminUserSummary) => boolean | undefined,
): TableColumn<AdminUserSummary>[] => [
  { header: "ID", accessorKey: "id" },
  {
    header: "账号",
    cell: ({ row }) => (
      <div>
        <div className="font-semibold text-[var(--ink)]">{row.original.username}</div>
        <div className="text-xs text-[var(--color-text-hint)]">{row.original.email || "未设置邮箱"}</div>
      </div>
    ),
  },
  { header: "角色ID", accessorKey: "role_id" },
  {
    header: "状态",
    cell: ({ row }) => <StatusBadge tone={row.original.is_active ? "success" : "danger"}>{row.original.is_active ? "启用" : "停用"}</StatusBadge>,
  },
  {
    header: "操作",
    cell: ({ row }) => {
      const protectedRow = isSuperAdmin(row.original);
      return (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" disabled={protectedRow} onClick={() => onEdit(row.original)}>
            <Edit3 className="h-4 w-4" />
            编辑
          </Button>
          <Button variant="secondary" disabled={protectedRow} onClick={() => onConfirm({ action: "force-logout", userId: row.original.id, userName: row.original.username })}>
            <RefreshCw className="h-4 w-4" />
            强退
          </Button>
          <Button variant="secondary" disabled={protectedRow} onClick={() => onConfirm({ action: "reset-password", userId: row.original.id, userName: row.original.username })}>
            <ShieldAlert className="h-4 w-4" />
            重置密码
          </Button>
          <Button variant="danger" disabled={protectedRow} onClick={() => onConfirm({ action: "delete", userId: row.original.id, userName: row.original.username })}>
            <Trash2 className="h-4 w-4" />
            删除
          </Button>
        </div>
      );
    },
  },
];

export default function AdminUsersPage() {
  const queryClient = useQueryClient();
  const permissions = useAuthStore((state) => state.permissions);
  const role = useAuthStore((state) => state.role);
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [confirmState, setConfirmState] = useState<ConfirmState>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);

  const users = useQuery({
    queryKey: ["admin-users", page, keyword],
    queryFn: () => apiRequest<PaginatedResponse<AdminUserSummary>>(`/admin-users${toQuery({ page, page_size: 20, keyword })}`),
  });
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => apiRequest<{ items: Role[] }>("/roles") });
  const editableRoles = roles.data?.items?.filter((role) => role.name !== "super_admin") ?? [];

  const isSuperAdmin = useCallback((user: AdminUserSummary) => {
    const superAdminRole = roles.data?.items?.find((r) => r.name === "super_admin");
    return superAdminRole && user.role_id === superAdminRole.id;
  }, [roles.data]);

  const actionMutation = useMutation({
    mutationFn: async (state: Exclude<ConfirmState, null>) => {
      if (state.action === "force-logout") return apiRequest(`/admin-users/${state.userId}/force-logout`, { method: "POST" });
      if (state.action === "reset-password") return apiRequest(`/admin-users/${state.userId}/reset-password`, { method: "POST", body: JSON.stringify({ password: "ChangeMe!2026" }) });
      return apiRequest(`/admin-users/${state.userId}`, { method: "DELETE" });
    },
    onSuccess: (_result, variables) => {
      const labels: Record<string, string> = { "force-logout": "已强制登出", "reset-password": "密码已重置", delete: "用户已删除" };
      setMessage(`${variables.userName}：${labels[variables.action]}`);
      setConfirmState(null);
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : "操作失败，请稍后重试。"),
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!form.role_id) throw new Error("请选择角色");
      if (form.id) {
        const payload: AdminUserPatchRequest = { display_name: form.display_name || null, email: form.email || null, role_id: Number(form.role_id), is_active: form.is_active };
        return apiRequest(`/admin-users/${form.id}`, { method: "PATCH", body: JSON.stringify(payload) });
      }
      if (!form.username || !form.password) throw new Error("请输入用户名和初始密码");
      const payload: AdminUserCreateRequest = { username: form.username, password: form.password, display_name: form.display_name || null, email: form.email || null, role_id: Number(form.role_id), is_active: form.is_active };
      return apiRequest("/admin-users", { method: "POST", body: JSON.stringify(payload) });
    },
    onSuccess: () => {
      setMessage(form.id ? "管理员已更新" : "管理员已创建");
      setForm(emptyForm);
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : "保存失败，请稍后重试。"),
  });

  const startEdit = (user: AdminUserSummary) => setForm({ id: user.id, username: user.username, password: "", display_name: user.display_name ?? "", email: user.email ?? "", role_id: String(user.role_id), is_active: user.is_active });
  const columns = useMemo(() => columnsDef((state) => setConfirmState(state), startEdit, isSuperAdmin), [isSuperAdmin]);

  const canSubmitForm: PermissionKey = form.id ? "admin-user:update" : "admin-user:create";
  const canUseForm = role?.name === "super_admin" || hasPermission(permissions, canSubmitForm);

  const confirmDescription = confirmState
    ? {
        "force-logout": `确认强制登出 ${confirmState.userName}？当前会话将立即失效。`,
        "reset-password": `确认将 ${confirmState.userName} 的密码重置为 ChangeMe!2026？`,
        delete: `确认删除管理员 ${confirmState.userName}？此操作不可恢复。`,
      }[confirmState.action]
    : "";

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="font-mono text-xs uppercase tracking-[0.3em] text-[var(--color-text-hint)]">Admin Users</p>
          <h2 className="mt-2 font-display text-4xl font-bold text-[var(--ink)]">管理员</h2>
        </div>
        <Button onClick={() => setForm(emptyForm)}>
          <Plus className="h-4 w-4" />
          新建管理员
        </Button>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <Card>
          <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">账号列表</h3>
              <p className="mt-1 text-sm text-[var(--color-text-secondary)]">支持创建、编辑、强退、重置密码、super_admin 保护。</p>
            </div>
            <label className="relative w-full max-w-sm">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
              <Input className="pl-9" placeholder="搜索用户名 / 邮箱" value={keyword} onChange={(event) => { setKeyword(event.target.value); setPage(1); }} />
            </label>
          </CardHeader>
          <CardContent>
            {message ? <p className="mb-4 rounded-2xl border border-[var(--color-border)] bg-white/70 px-4 py-3 text-sm text-[var(--color-text-secondary)]">{message}</p> : null}
            {users.isError ? <p className="mb-4 rounded-2xl border border-[var(--color-danger)] bg-white/70 px-4 py-3 text-sm text-[var(--color-danger)]">{users.error instanceof Error ? users.error.message : "管理员列表接口暂不可用"}</p> : null}
            <DataTable data={users.data?.items ?? []} columns={columns} emptyText={users.isError ? "接口暂不可用" : "暂无管理员"} />
            <div className="mt-4 flex items-center justify-between text-sm text-[var(--color-text-secondary)]">
              <span>共 {users.data?.total ?? 0} 条</span>
              <div className="flex gap-2">
                <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>上一页</Button>
                <Button variant="secondary" disabled={page >= (users.data?.total_pages ?? 1)} onClick={() => setPage((value) => value + 1)}>下一页</Button>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="blueprint-panel">
          <CardContent className="relative z-10 space-y-4">
            {message ? <p className="rounded-2xl border border-[var(--color-border)] bg-white/70 px-4 py-3 text-sm text-[var(--color-text-secondary)]">{message}</p> : null}
            {canUseForm ? (
              <>
                <h3 className="font-display text-2xl font-bold text-[var(--ink)]">{form.id ? "编辑管理员" : "创建管理员"}</h3>
                <div className="grid gap-3">
                  <Input placeholder="用户名" value={form.username} disabled={Boolean(form.id)} onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))} />
                  {!form.id ? <Input placeholder="初始密码" type="password" value={form.password} onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))} /> : null}
                  <Input placeholder="显示名" value={form.display_name} onChange={(event) => setForm((current) => ({ ...current, display_name: event.target.value }))} />
                  <Input placeholder="邮箱" value={form.email} onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))} />
                  <select className="h-11 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm" value={form.role_id} onChange={(event) => setForm((current) => ({ ...current, role_id: event.target.value }))}>
                    <option value="">请选择角色</option>
                    {editableRoles.map((role) => <option key={role.id} value={role.id}>{role.display_name}</option>)}
                  </select>
                  <label className="flex items-center gap-2 text-sm text-[var(--color-text-secondary)]">
                    <input type="checkbox" checked={form.is_active} onChange={(event) => setForm((current) => ({ ...current, is_active: event.target.checked }))} />
                    启用账号
                  </label>
                  <div className="flex gap-2">
                    <Button disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}>{form.id ? "保存修改" : "创建"}</Button>
                    <Button variant="secondary" onClick={() => setForm(emptyForm)}>清空</Button>
                  </div>
                </div>
                <p className="text-sm leading-7 text-[var(--color-text-secondary)]">super_admin 受保护，前端不提供修改入口，后端仍保留强制校验。</p>
              </>
            ) : (
              <p className="rounded-2xl border border-[var(--color-border)] bg-white/70 px-4 py-3 text-sm text-[var(--color-text-secondary)]">当前账号没有{form.id ? "编辑管理员" : "创建管理员"}权限。</p>
            )}
          </CardContent>
        </Card>
      </div>

      <ConfirmDialog
        open={confirmState !== null}
        title="确认操作"
        description={confirmDescription}
        confirmText="确认"
        danger={confirmState?.action === "delete"}
        loading={actionMutation.isPending}
        onCancel={() => setConfirmState(null)}
        onConfirm={() => {
          if (!confirmState) return;
          actionMutation.mutate(confirmState);
        }}
      />
    </div>
  );
}

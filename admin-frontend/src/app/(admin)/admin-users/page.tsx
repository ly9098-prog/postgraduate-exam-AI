"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Edit3, Key, LogOut, Plus, RefreshCw, Search, ShieldAlert, Trash2, Users, X } from "lucide-react";
import { useMemo, useState, useCallback } from "react";
import { createPortal } from "react-dom";
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

type ConfirmState = { action: "delete" | "force-logout" | "reset-password"; userId: number; userName: string } | null;
type FormState = { id?: number; username: string; password: string; display_name: string; email: string; role_id: string; is_active: boolean };

const emptyForm: FormState = { username: "", password: "", display_name: "", email: "", role_id: "", is_active: true };

export default function AdminUsersPage() {
  const queryClient = useQueryClient();
  const permissions = useAuthStore((state) => state.permissions);
  const role = useAuthStore((state) => state.role);
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [confirmState, setConfirmState] = useState<ConfirmState>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [showForm, setShowForm] = useState(false);

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
      setShowForm(false);
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : "保存失败，请稍后重试。"),
  });

  const openCreateForm = () => {
    setForm(emptyForm);
    setShowForm(true);
  };

  const startEdit = (user: AdminUserSummary) => {
    setForm({ id: user.id, username: user.username, password: "", display_name: user.display_name ?? "", email: user.email ?? "", role_id: String(user.role_id), is_active: user.is_active });
    setShowForm(true);
  };

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
    <div className="space-y-8">
      {/* ===== Page Header ===== */}
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-4">
          <div className="rounded-2xl bg-gradient-to-br from-indigo-100 to-indigo-200 p-3.5 shadow-sm ring-1 ring-indigo-200">
            <Users className="h-6 w-6 text-indigo-700" />
          </div>
          <div>
            <h2 className="font-display text-2xl font-bold tracking-tight text-[var(--ink)]">管理员</h2>
            <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
              管理后台管理员账号，支持创建、编辑、强退、重置密码
            </p>
          </div>
        </div>
        <Button onClick={openCreateForm} className="h-9 gap-2 px-4 text-xs">
          <Plus className="h-4 w-4" />
          新建管理员
        </Button>
      </div>

      {/* ===== Message ===== */}
      {message ? (
        <div className="flex items-center gap-2.5 rounded-2xl border border-[var(--color-border)] bg-white/80 px-5 py-3.5 text-sm shadow-sm">
          {message.includes("失败") || message.includes("error") ? (
            <ShieldAlert className="h-4 w-4 shrink-0 text-red-500" />
          ) : (
            <RefreshCw className="h-4 w-4 shrink-0 text-green-500" />
          )}
          <span className="text-[var(--ink)]">{message}</span>
        </div>
      ) : null}

      {/* ===== Account List ===== */}
      <Card>
        <CardHeader className="flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="font-display text-lg font-bold text-[var(--ink)]">账号列表</h3>
            <p className="mt-0.5 text-sm text-[var(--color-text-secondary)]">{users.data?.total ?? 0} 个管理员账号</p>
          </div>
          <label className="relative w-full max-w-xs">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
            <Input className="h-9 pl-9 text-sm" placeholder="搜索用户名 / 邮箱" value={keyword} onChange={(event) => { setKeyword(event.target.value); setPage(1); }} />
          </label>
        </CardHeader>
        <CardContent>
          {users.isError ? (
            <div className="mb-4 flex items-center gap-2 rounded-xl border border-red-200 bg-red-50/70 px-4 py-3 text-sm text-red-700">
              <ShieldAlert className="h-4 w-4 shrink-0" />
              {users.error instanceof Error ? users.error.message : "管理员列表接口暂不可用"}
            </div>
          ) : null}

          <DataTable
            data={users.data?.items ?? []}
            columns={useMemo((): Array<{
              id?: string;
              header?: React.ReactNode | (() => React.ReactNode);
              cell?: (context: { row: { original: AdminUserSummary } }) => React.ReactNode;
            }> => [
              {
                id: "ID",
                header: () => <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--color-text-hint)]">ID</span>,
                cell: ({ row }) => <span className="font-mono text-xs tabular-nums text-[var(--color-text-secondary)]">{row.original.id}</span>,
              },
              {
                id: "account",
                header: () => <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--color-text-hint)]">账号</span>,
                cell: ({ row }) => (
                  <div className="flex items-center gap-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-indigo-100 to-indigo-200 text-xs font-bold text-indigo-700 ring-1 ring-indigo-200">
                      {row.original.username.charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <div className="text-sm font-semibold text-[var(--ink)]">{row.original.username}</div>
                      <div className="text-xs text-[var(--color-text-hint)]">{row.original.display_name || row.original.email || "—"}</div>
                    </div>
                  </div>
                ),
              },
              {
                id: "role",
                header: () => <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--color-text-hint)]">角色</span>,
                cell: ({ row }) => {
                  const userRole = roles.data?.items?.find((r) => r.id === row.original.role_id);
                  return (
                    <span className="text-sm text-[var(--color-text-secondary)]">
                      {userRole?.display_name || `#${row.original.role_id}`}
                    </span>
                  );
                },
              },
              {
                id: "status",
                header: () => <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--color-text-hint)]">状态</span>,
                cell: ({ row }) => (
                  <StatusBadge tone={row.original.is_active ? "success" : "danger"}>
                    {row.original.is_active ? "启用" : "停用"}
                  </StatusBadge>
                ),
              },
              {
                id: "actions",
                header: () => <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--color-text-hint)]">操作</span>,
                cell: ({ row }) => {
                  const protectedRow = isSuperAdmin(row.original);
                  return (
                    <div className="flex flex-nowrap gap-1.5">
                      <Button variant="ghost" disabled={protectedRow} onClick={() => startEdit(row.original)} className="h-8 px-2.5 text-xs">
                        <Edit3 className="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="ghost" disabled={protectedRow} onClick={() => setConfirmState({ action: "force-logout", userId: row.original.id, userName: row.original.username })} className="h-8 px-2.5 text-xs">
                        <LogOut className="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="ghost" disabled={protectedRow} onClick={() => setConfirmState({ action: "reset-password", userId: row.original.id, userName: row.original.username })} className="h-8 px-2.5 text-xs">
                        <Key className="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="danger" disabled={protectedRow} onClick={() => setConfirmState({ action: "delete", userId: row.original.id, userName: row.original.username })} className="h-8 px-2.5 text-xs">
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  );
                },
              },
            ], [isSuperAdmin, roles.data?.items])}
            emptyText={users.isError ? "接口暂不可用" : "暂无管理员"}
          />

          <div className="mt-4 flex items-center justify-between">
            <span className="text-xs text-[var(--color-text-hint)]">
              共 {users.data?.total ?? 0} 条，第 {page}/{users.data?.total_pages ?? 1} 页
            </span>
            <div className="flex gap-2">
              <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((value) => value - 1)} className="h-8 px-3 text-xs">
                上一页
              </Button>
              <Button variant="secondary" disabled={page >= (users.data?.total_pages ?? 1)} onClick={() => setPage((value) => value + 1)} className="h-8 px-3 text-xs">
                下一页
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ===== Create/Edit User Modal ===== */}
      {showForm ? createPortal(
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(16,24,40,0.42)] px-4" onClick={() => setShowForm(false)}>
          <div className="w-full max-w-md rounded-3xl border border-[var(--color-border)] bg-white p-6 shadow-[var(--shadow-floating)]" onClick={(e) => e.stopPropagation()}>
            <div className="mb-5 flex items-center justify-between">
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">
                {form.id ? "编辑管理员" : "创建管理员"}
              </h3>
              <Button variant="ghost" onClick={() => setShowForm(false)} className="h-8 w-8 p-0">
                <X className="h-4 w-4" />
              </Button>
            </div>
            {canUseForm ? (
              <div className="space-y-4">
                <div className="space-y-3">
                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">用户名</label>
                    <Input placeholder="登录用户名" value={form.username} disabled={Boolean(form.id)} onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))} />
                  </div>
                  {!form.id ? (
                    <div>
                      <label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">初始密码</label>
                      <Input placeholder="设置初始密码" type="password" value={form.password} onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))} />
                    </div>
                  ) : null}
                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">显示名</label>
                    <Input placeholder="可选" value={form.display_name} onChange={(event) => setForm((current) => ({ ...current, display_name: event.target.value }))} />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">邮箱</label>
                    <Input placeholder="可选" value={form.email} onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))} />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-[var(--color-text-secondary)]">角色</label>
                    <select className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200" value={form.role_id} onChange={(event) => setForm((current) => ({ ...current, role_id: event.target.value }))}>
                      <option value="">请选择角色</option>
                      {editableRoles.map((role) => <option key={role.id} value={role.id}>{role.display_name}</option>)}
                    </select>
                  </div>
                  <label className="flex items-center gap-2.5 rounded-xl border border-[var(--color-border)] bg-white/50 px-3 py-2.5 text-sm text-[var(--color-text-secondary)] transition hover:bg-white/80">
                    <input type="checkbox" checked={form.is_active} onChange={(event) => setForm((current) => ({ ...current, is_active: event.target.checked }))} className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
                    启用账号
                  </label>
                </div>
                <p className="text-xs leading-relaxed text-[var(--color-text-hint)]">
                  super_admin 受保护，前端不提供修改入口。
                </p>
                <div className="flex gap-2 pt-1">
                  <Button disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()} className="h-10 flex-1 text-sm">
                    {saveMutation.isPending ? "保存中..." : form.id ? "保存修改" : "创建"}
                  </Button>
                  <Button variant="secondary" onClick={() => { setForm(emptyForm); setShowForm(false); }} className="h-10 px-5 text-sm">
                    取消
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-2 rounded-xl border border-[var(--color-border)] bg-white/50 px-4 py-3 text-sm text-[var(--color-text-secondary)]">
                <ShieldAlert className="h-4 w-4 shrink-0" />
                当前账号没有{form.id ? "编辑管理员" : "创建管理员"}权限。
              </div>
            )}
          </div>
        </div>,
        document.body
      ) : null}

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

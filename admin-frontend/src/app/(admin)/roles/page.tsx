"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Columns3, KeyRound, Save } from "lucide-react";
import { useMemo, useState } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { apiRequest } from "@/lib/api/client";
import type { Permission, Role } from "@/lib/api/types";

export default function RolesPage() {
  const queryClient = useQueryClient();
  const [selectedRoleId, setSelectedRoleId] = useState<number | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const roles = useQuery({ queryKey: ["roles"], queryFn: () => apiRequest<{ items: Role[] }>("/roles") });
  const permissions = useQuery({ queryKey: ["permissions-by-category"], queryFn: async () => (await apiRequest<{ items: Record<string, Permission[]> }>("/permissions/by-category")).items });
  const roleItems = useMemo(() => roles.data?.items ?? [], [roles.data]);
  const activeRoleId = selectedRoleId ?? roleItems.find((role) => role.name !== "super_admin")?.id ?? roleItems[0]?.id ?? null;
  const selectedRole = useMemo(() => roleItems.find((role) => role.id === activeRoleId) ?? null, [roleItems, activeRoleId]);
  const selectedPermissionIds = useMemo(() => new Set(selectedRole?.permission_ids ?? []), [selectedRole]);
  const [permissionOverrides, setPermissionOverrides] = useState<Record<number, number[]>>({});
  const activePermissionIds = useMemo(
    () => new Set(activeRoleId && permissionOverrides[activeRoleId] ? permissionOverrides[activeRoleId] : Array.from(selectedPermissionIds)),
    [activeRoleId, permissionOverrides, selectedPermissionIds],
  );

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!selectedRole) throw new Error("请选择角色");
      return apiRequest(`/roles/${selectedRole.id}/permissions`, { method: "PUT", body: JSON.stringify({ permission_ids: Array.from(activePermissionIds) }) });
    },
    onSuccess: () => {
      setMessage("角色权限已更新");
      setConfirmOpen(false);
      queryClient.invalidateQueries({ queryKey: ["roles"] });
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : "保存失败，请稍后重试。"),
  });

  const togglePermission = (permissionId: number) => {
    if (selectedRole?.name === "super_admin") return;
    if (!selectedRole) return;
    setPermissionOverrides((current) => {
      const currentIds = activePermissionIds;
      const next = new Set(currentIds);
      if (next.has(permissionId)) next.delete(permissionId);
      else next.add(permissionId);
      return { ...current, [selectedRole.id]: Array.from(next) };
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <p className="font-mono text-xs uppercase tracking-[0.3em] text-[var(--color-text-hint)]">RBAC</p>
        <h2 className="mt-2 font-display text-4xl font-bold text-[var(--ink)]">角色权限</h2>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <Columns3 className="h-5 w-5 text-[var(--color-primary)]" />
            <div>
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">角色</h3>
              <p className="text-sm text-[var(--color-text-secondary)]">选择角色后编辑权限矩阵，super_admin 仅展示不可编辑。</p>
            </div>
          </div>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {roles.data?.items?.map((role) => (
            <button key={role.id} className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4 text-left disabled:opacity-80" onClick={() => setSelectedRoleId(role.id)}>
              <div className="flex items-center justify-between gap-3">
                <span className="font-semibold text-[var(--ink)]">{role.display_name}</span>
                <StatusBadge tone={activeRoleId === role.id ? "primary" : role.is_system ? "warning" : "neutral"}>{activeRoleId === role.id ? "当前" : role.is_system ? "系统" : "自定义"}</StatusBadge>
              </div>
              <p className="mt-2 text-sm text-[var(--color-text-secondary)]">{role.description || role.name}</p>
            </button>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-3">
            <KeyRound className="h-5 w-5 text-[var(--color-primary)]" />
            <div>
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">权限矩阵</h3>
              <p className="text-sm text-[var(--color-text-secondary)]">当前角色：{selectedRole?.display_name ?? "未选择"}</p>
            </div>
          </div>
          <Button disabled={!selectedRole || selectedRole.name === "super_admin" || saveMutation.isPending} onClick={() => setConfirmOpen(true)}>
            <Save className="h-4 w-4" />
            保存权限
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {message ? <p className="rounded-2xl border border-[var(--color-border)] bg-white/70 px-4 py-3 text-sm text-[var(--color-text-secondary)]">{message}</p> : null}
          {Object.entries(permissions.data ?? {}).map(([category, items]) => (
            <div key={category} className="rounded-3xl border border-[var(--color-border)] bg-white/70 p-4">
              <h4 className="mb-3 font-semibold text-[var(--ink)]">{category}</h4>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {items.map((permission) => (
                  <label key={permission.id} className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3">
                    <div className="flex items-start gap-2">
                      <input type="checkbox" checked={activePermissionIds.has(permission.id)} disabled={!selectedRole || selectedRole.name === "super_admin"} onChange={() => togglePermission(permission.id)} />
                      <div>
                        <div className="font-semibold text-[var(--ink)]">{permission.name}</div>
                        <div className="text-xs text-[var(--color-text-hint)]">{permission.resource}:{permission.action}</div>
                        <div className="mt-2 text-sm text-[var(--color-text-secondary)]">{permission.description || "—"}</div>
                      </div>
                    </div>
                  </label>
                ))}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={confirmOpen}
        title="确认修改角色权限"
        description={`确认更新 ${selectedRole?.display_name ?? "当前角色"} 的权限？该操作会影响对应管理员菜单与接口访问。`}
        confirmText="确认保存"
        loading={saveMutation.isPending}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => saveMutation.mutate()}
      />
    </div>
  );
}

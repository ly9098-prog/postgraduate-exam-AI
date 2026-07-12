"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Plus, Save, X, ChevronDown, ChevronRight, Pencil,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { FormulaCategoryDialog } from "@/components/formulas/formula-category-dialog";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import { apiRequest } from "@/lib/api/client";
import type { FormulaCategoryNode } from "@/components/formulas/formula-category-picker";

export default function FormulaCategoriesPage() {
  const queryClient = useQueryClient();
  const permissions = useAuthStore((state) => state.permissions);
  const canWrite = hasPermission(permissions, "formula-category:write");

  const [message, setMessage] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [dialogParent, setDialogParent] = useState<FormulaCategoryNode | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["admin-formula-categories"],
    queryFn: () => apiRequest<{ items: FormulaCategoryNode[] }>("/formulas/categories"),
  });

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: async ({ id, name }: { id: number; name: string }) =>
      apiRequest(`/formulas/categories/${id}`, {
        method: "PUT",
        body: JSON.stringify({ name }),
      }),
    onSuccess: () => {
      setMessage("已更新");
      setEditingId(null);
      queryClient.invalidateQueries({ queryKey: ["admin-formula-categories"] });
    },
    onError: (e) => setMessage(e instanceof Error ? e.message : "更新失败"),
  });

  const toggleExpand = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const openCreateDialog = (parent: FormulaCategoryNode | null) => {
    setDialogParent(parent);
    setShowCreateDialog(true);
  };

  const closeCreateDialog = () => {
    setShowCreateDialog(false);
    setDialogParent(null);
  };

  const renderTree = (cats: FormulaCategoryNode[], depth = 0) => {
    return cats.map((cat) => {
      const hasChildren = cat.children && cat.children.length > 0;
      const isExpanded = expanded.has(cat.id);
      const isEditing = editingId === cat.id;

      // Groups can't have children
      const canHaveChildren = cat.node_type !== "group";

      return (
        <div key={cat.id} className="space-y-2">
          <div
            className={`flex min-h-[3rem] items-center gap-3 rounded-xl border px-4 py-2.5 transition ${
              cat.is_active
                ? "bg-white/80 hover:bg-white hover:shadow-sm"
                : "bg-gray-50 opacity-60"
            }`}
            style={{ marginLeft: depth * 28 }}
          >
            {/* Expand toggle */}
            <button
              type="button"
              onClick={() => toggleExpand(cat.id)}
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded hover:bg-[var(--color-bg-input)]"
              aria-label={isExpanded ? "收起" : "展开"}
              title={isExpanded ? "收起" : "展开"}
            >
              {hasChildren ? (
                isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />
              ) : (
                <span className="w-4" />
              )}
            </button>

            {/* Node type badge */}
            <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase leading-none ${
              cat.node_type === "subject" ? "border-blue-200 bg-blue-50 text-blue-700" :
              cat.node_type === "chapter" ? "border-green-200 bg-green-50 text-green-700" :
              "border-gray-200 bg-gray-100 text-gray-600"
            }`}>
              {cat.node_type === "subject" ? "科目" : cat.node_type === "chapter" ? "章节" : "分组"}
            </span>

            {/* Code */}
            <span className="hidden font-mono text-xs text-[var(--color-text-hint)] sm:inline">{cat.code}</span>

            {/* Name or edit input */}
            {isEditing ? (
              <div className="flex flex-1 items-center gap-2">
                <Input
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="h-8 text-sm"
                />
                <Button size="sm" onClick={() => updateMutation.mutate({ id: cat.id, name: editName })}>
                  <Save className="h-3 w-3" />
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setEditingId(null)}>
                  <X className="h-3 w-3" />
                </Button>
              </div>
            ) : (
              <>
                <span className="min-w-0 flex-1 text-sm font-medium text-[var(--ink)] break-words">
                  {cat.name}
                </span>
                {canWrite && (
                  <div className="flex shrink-0 items-center gap-0.5">
                    <button
                      onClick={() => { setEditingId(cat.id); setEditName(cat.name); }}
                      className="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-[var(--color-bg-input)]"
                      aria-label="编辑名称"
                      title="编辑名称"
                    >
                      <Pencil className="h-3.5 w-3.5 text-[var(--color-text-hint)]" />
                    </button>
                    {/* Add child button (only for subject and chapter) */}
                    {canHaveChildren && (
                      <button
                        onClick={() => openCreateDialog(cat)}
                        className="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-[var(--color-bg-input)]"
                        aria-label={`添加子${
                          cat.node_type === "subject" ? "章节" : "分组"
                        }`}
                        title={`添加子${cat.node_type === "subject" ? "章节" : "分组"}`}
                      >
                        <Plus className="h-3.5 w-3.5 text-[var(--color-text-hint)]" />
                      </button>
                    )}
                  </div>
                )}
              </>
            )}
          </div>

          {/* Children */}
          {hasChildren && isExpanded && (
            <div className="ml-3 border-l border-[var(--color-border)] pl-4 space-y-2">
              {renderTree(cat.children, depth + 1)}
            </div>
          )}
        </div>
      );
    });
  };

  return (
    <div className="space-y-6 pb-24">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">公式分类管理</h3>
              <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
                科目 → 章节 → 分组 三级分类树，点击名称编辑
              </p>
            </div>
            {canWrite && (
              <Button variant="primary" onClick={() => openCreateDialog(null)}>
                <Plus className="h-4 w-4" /> 新建分类
              </Button>
            )}
          </div>
        </CardHeader>

        <CardContent className="space-y-6">
          {message ? (
            <div className="rounded-2xl border border-[var(--color-success)] bg-[var(--color-success-light)] px-4 py-3 text-sm font-medium">
              {message}
              <button className="ml-3" onClick={() => setMessage(null)}>✕</button>
            </div>
          ) : null}

          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }, (_, i) => (
                <div key={i} className="h-14 animate-pulse rounded-xl border bg-white/60" />
              ))}
            </div>
          ) : data?.items ? (
            <div className="space-y-2">{renderTree(data.items)}</div>
          ) : null}
        </CardContent>
      </Card>

      {/* Create dialog */}
      {showCreateDialog && (
        <FormulaCategoryDialog
          parentNode={dialogParent}
          onClose={closeCreateDialog}
        />
      )}
    </div>
  );
}

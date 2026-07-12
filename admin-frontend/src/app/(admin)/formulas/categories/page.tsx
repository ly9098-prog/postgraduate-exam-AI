"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Plus, Save, X, Trash2, ChevronDown, ChevronRight, Pencil,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import { apiRequest } from "@/lib/api/client";

type FormulaCategory = {
  id: number;
  parent_id: number | null;
  code: string;
  name: string;
  node_type: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
  children: FormulaCategory[];
};

export default function FormulaCategoriesPage() {
  const queryClient = useQueryClient();
  const permissions = useAuthStore((state) => state.permissions);
  const canWrite = hasPermission(permissions, "formula-category:write");

  const [message, setMessage] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);
  const [addParentId, setAddParentId] = useState<number | null>(null);
  const [addCode, setAddCode] = useState("");
  const [addName, setAddName] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["admin-formula-categories"],
    queryFn: () => apiRequest<{ items: FormulaCategory[] }>("/formulas/categories"),
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

  // Create mutation
  const createMutation = useMutation({
    mutationFn: async (data: { parent_id: number | null; code: string; name: string }) =>
      apiRequest("/formulas/categories", {
        method: "POST",
        body: JSON.stringify({
          parent_id: data.parent_id,
          code: data.code,
          name: data.name,
          node_type: "group",
          exam_scope: "math2",
        }),
      }),
    onSuccess: () => {
      setMessage("已创建");
      setShowAddForm(false);
      setAddCode("");
      setAddName("");
      setAddParentId(null);
      queryClient.invalidateQueries({ queryKey: ["admin-formula-categories"] });
    },
    onError: (e) => setMessage(e instanceof Error ? e.message : "创建失败"),
  });

  const toggleExpand = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const renderTree = (cats: FormulaCategory[], depth = 0) => {
    return cats.map((cat) => {
      const hasChildren = cat.children && cat.children.length > 0;
      const isExpanded = expanded.has(cat.id);
      const isEditing = editingId === cat.id;

      return (
        <div key={cat.id}>
          <div
            className={`flex items-center gap-3 rounded-xl border px-4 py-3 transition ${
              cat.is_active ? "bg-white/80" : "bg-gray-50 opacity-60"
            }`}
            style={{ marginLeft: depth * 24 }}
          >
            <button
              type="button"
              onClick={() => toggleExpand(cat.id)}
              className="h-6 w-6 shrink-0"
            >
              {hasChildren ? (
                isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />
              ) : null}
            </button>

            <span className={`rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase ${
              cat.node_type === "subject" ? "border-blue-200 bg-blue-50 text-blue-700" :
              cat.node_type === "chapter" ? "border-green-200 bg-green-50 text-green-700" :
              "border-gray-200 bg-gray-50 text-gray-600"
            }`}>
              {cat.node_type === "subject" ? "科目" : cat.node_type === "chapter" ? "章节" : "分组"}
            </span>

            <span className="font-mono text-xs text-[var(--color-text-hint)]">{cat.code}</span>

            {isEditing ? (
              <div className="flex flex-1 items-center gap-2">
                <Input value={editName} onChange={(e) => setEditName(e.target.value)} />
                <Button size="sm" onClick={() => updateMutation.mutate({ id: cat.id, name: editName })}>
                  <Save className="h-3 w-3" />
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setEditingId(null)}>
                  <X className="h-3 w-3" />
                </Button>
              </div>
            ) : (
              <>
                <span className="flex-1 text-sm font-medium text-[var(--ink)]">{cat.name}</span>
                {canWrite && (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => { setEditingId(cat.id); setEditName(cat.name); }}
                      className="h-7 w-7 rounded-lg hover:bg-[var(--color-bg-input)]"
                    >
                      <Pencil className="h-3.5 w-3.5 mx-auto text-[var(--color-text-hint)]" />
                    </button>
                    {cat.node_type === "group" && (
                      <button
                        onClick={() => {
                          setAddParentId(cat.parent_id);
                          setShowAddForm(true);
                        }}
                        className="h-7 w-7 rounded-lg hover:bg-[var(--color-bg-input)]"
                      >
                        <Plus className="h-3.5 w-3.5 mx-auto text-[var(--color-text-hint)]" />
                      </button>
                    )}
                  </div>
                )}
              </>
            )}
          </div>

          {hasChildren && isExpanded && renderTree(cat.children, depth + 1)}
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
            <div className="space-y-1">{renderTree(data.items)}</div>
          ) : null}

          {/* Add form */}
          {canWrite && (
            <div className="border-t pt-4">
              {showAddForm ? (
                <div className="rounded-xl border bg-white/80 p-4 space-y-3">
                  <p className="text-xs font-semibold text-[var(--color-text-secondary)]">
                    新建分类（父节点 ID: {addParentId ?? "无（顶级科目）"}）
                  </p>
                  <div className="grid gap-3 md:grid-cols-2">
                    <Input placeholder="编码（英文）" value={addCode} onChange={(e) => setAddCode(e.target.value)} />
                    <Input placeholder="名称" value={addName} onChange={(e) => setAddName(e.target.value)} />
                  </div>
                  <div className="flex justify-end gap-2">
                    <Button variant="secondary" size="sm" onClick={() => { setShowAddForm(false); setAddCode(""); setAddName(""); }}>
                      <X className="h-3 w-3" /> 取消
                    </Button>
                    <Button size="sm" onClick={() => createMutation.mutate({ parent_id: addParentId, code: addCode, name: addName })}>
                      <Save className="h-3 w-3" /> 创建
                    </Button>
                  </div>
                </div>
              ) : (
                <Button variant="secondary" onClick={() => setShowAddForm(true)}>
                  <Plus className="h-4 w-4" /> 新建分类
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

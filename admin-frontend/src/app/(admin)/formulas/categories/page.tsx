"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ChevronRight,
  Folder,
  FolderTree,
  GitBranch,
  Hash,
  Layers,
  ListTree,
  Plus,
  Save,
  Search,
  X,
  Loader2,
  FileText,
  ArrowRight,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { FormulaCategoryDialog } from "@/components/formulas/formula-category-dialog";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import { apiRequest } from "@/lib/api/client";
import {
  findNodeInTree,
  findParentNode,
  findPathToNode,
  countDescendants,
  filterCategoryTree,
} from "@/lib/category-tree-utils";
import type { FormulaCategoryNode } from "@/components/formulas/formula-category-picker";

const TYPE_LABEL: Record<string, string> = {
  subject: "科目",
  chapter: "章节",
  group: "分组",
};

type AdminFormulaCategoryNode = Omit<FormulaCategoryNode, "children"> & {
  description?: string | null;
  sort_order?: number;
  formula_count?: number;
  subtree_formula_count?: number;
  created_at?: string | null;
  updated_at?: string | null;
  children: AdminFormulaCategoryNode[];
};

type CategoryTab = "basic" | "children";

export default function FormulaCategoriesPage() {
  const queryClient = useQueryClient();
  const permissions = useAuthStore((state) => state.permissions);
  const canWrite = hasPermission(permissions, "formula-category:write");

  const [message, setMessage] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editSortOrder, setEditSortOrder] = useState("0");
  const [editActive, setEditActive] = useState(true);
  const [activeTab, setActiveTab] = useState<CategoryTab>("basic");
  const [search, setSearch] = useState("");
  const [dialogParent, setDialogParent] = useState<AdminFormulaCategoryNode | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["admin-formula-categories"],
    queryFn: () => apiRequest<{ items: AdminFormulaCategoryNode[] }>("/formulas/categories"),
    staleTime: 30_000,
  });

  const roots = useMemo(() => data?.items ?? [], [data?.items]);
  const visibleTree = useMemo(() => filterCategoryTree(roots, search), [roots, search]);
  const selectedNode = useMemo(() => findNodeInTree(roots, selectedId), [roots, selectedId]);
  const parentNode = useMemo(() => findParentNode(roots, selectedId), [roots, selectedId]);
  const selectedPath = useMemo(() => findPathToNode(roots, selectedId), [roots, selectedId]);
  const descendantCount = useMemo(() => countDescendants(selectedNode), [selectedNode]);

  useEffect(() => {
    if (!roots.length) {
      setSelectedId(null);
      return;
    }
    if (selectedId === null || !findNodeInTree(roots, selectedId)) {
      setSelectedId(roots[0].id);
    }
  }, [roots, selectedId]);

  useEffect(() => {
    if (!selectedNode) return;
    setEditName(selectedNode.name);
    setEditDescription(selectedNode.description ?? "");
    setEditSortOrder(String(selectedNode.sort_order ?? 0));
    setEditActive(selectedNode.is_active !== false);
    setExpanded((prev) => {
      const next = new Set(prev);
      selectedPath.forEach((node) => next.add(node.id));
      return next;
    });
  }, [selectedNode, selectedPath]);

  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => setMessage(null), 3500);
    return () => clearTimeout(timer);
  }, [message]);

  const updateMutation = useMutation({
    mutationFn: async ({ id, values }: { id: number; values: { name: string; description: string | null; sort_order: number; is_active: boolean } }) =>
      apiRequest(`/formulas/categories/${id}`, {
        method: "PUT",
        body: JSON.stringify(values),
      }),
    onSuccess: () => {
      setMessage("分类配置已保存");
      queryClient.invalidateQueries({ queryKey: ["admin-formula-categories"] });
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : "更新失败"),
  });

  const normalizedSortOrder = Number.isFinite(Number(editSortOrder)) ? Number(editSortOrder) : 0;
  const isDirty = Boolean(selectedNode) && (
    editName.trim() !== selectedNode!.name
    || editDescription.trim() !== (selectedNode!.description ?? "").trim()
    || normalizedSortOrder !== (selectedNode!.sort_order ?? 0)
    || editActive !== (selectedNode!.is_active !== false)
  );

  const resetEdits = () => {
    if (!selectedNode) return;
    setEditName(selectedNode.name);
    setEditDescription(selectedNode.description ?? "");
    setEditSortOrder(String(selectedNode.sort_order ?? 0));
    setEditActive(selectedNode.is_active !== false);
  };

  const toggleExpand = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectNode = (node: AdminFormulaCategoryNode) => {
    if (node.id === selectedId) return;
    if (isDirty && !confirm("当前分类有未保存的修改，确定切换到其他分类吗？")) return;
    setSelectedId(node.id);
    setActiveTab("basic");
  };

  const openCreateDialog = (parent: AdminFormulaCategoryNode | null) => {
    setDialogParent(parent);
    setShowCreateDialog(true);
  };

  const closeCreateDialog = () => {
    setShowCreateDialog(false);
    setDialogParent(null);
  };

  const saveChanges = () => {
    if (!selectedNode || !editName.trim() || !isDirty) return;
    updateMutation.mutate({
      id: selectedNode.id,
      values: {
        name: editName.trim(),
        description: editDescription.trim() || null,
        sort_order: normalizedSortOrder,
        is_active: editActive,
      },
    });
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "s") return;
      if (!canWrite || !selectedNode || !isDirty || updateMutation.isPending) return;
      event.preventDefault();
      saveChanges();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  const renderTree = (nodes: AdminFormulaCategoryNode[], depth = 0) =>
    nodes.map((node) => {
      const hasChildren = Boolean(node.children?.length);
      const isExpanded = search.trim() ? true : expanded.has(node.id);
      const isSelected = node.id === selectedId;

      return (
        <div key={node.id}>
          <div
            className={`group flex items-center gap-1 rounded-xl pr-2 transition-all duration-200 ${
              isSelected
                ? "bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]"
                : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-input)]"
            }`}
            style={{ paddingLeft: 4 + depth * 14 }}
          >
            <button
              type="button"
              onClick={() => hasChildren && toggleExpand(node.id)}
              className="flex h-9 w-6 shrink-0 items-center justify-center text-[var(--color-text-hint)]"
              aria-label={isExpanded ? "收起" : "展开"}
            >
              {hasChildren ? (
                <ChevronRight className={`h-3.5 w-3.5 transition-transform duration-200 ${isExpanded ? "rotate-90" : ""}`} />
              ) : (
                <span className="h-3.5 w-3.5" />
              )}
            </button>
            <button
              type="button"
              onClick={() => selectNode(node)}
              className="flex min-w-0 flex-1 items-center gap-2 py-2 text-left"
            >
              {node.node_type === "subject" ? (
                <FolderTree className="h-3.5 w-3.5 shrink-0 text-[var(--color-primary)]" />
              ) : (
                <Folder className="h-3.5 w-3.5 shrink-0 text-[var(--color-text-hint)]" />
              )}
              <span className={`truncate text-xs ${isSelected ? "font-bold" : "font-medium"}`}>{node.name}</span>
            </button>
            <span className="rounded-md border border-[var(--color-border)] bg-white/70 px-1.5 py-0.5 text-[9px] font-semibold text-[var(--color-text-hint)]">
              {TYPE_LABEL[node.node_type] || node.node_type}
            </span>
          </div>
          {hasChildren && isExpanded ? <div className="animate-fade-in">{renderTree(node.children, depth + 1)}</div> : null}
        </div>
      );
    });

  const childTypeLabel = selectedNode?.node_type === "subject" ? "章节" : selectedNode?.node_type === "chapter" ? "分组" : null;

  return (
    <div className="space-y-5 pb-24">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-[28px] font-bold leading-tight tracking-tight text-[var(--ink)]">公式分类管理</h1>
          <p className="mt-1.5 text-sm text-[var(--color-text-secondary)]">科目 → 章节 → 分组，使用结构化配置台维护分类体系</p>
        </div>
        {canWrite ? (
          <Button variant="primary" onClick={() => openCreateDialog(null)}>
            <Plus className="h-4 w-4" /> 新建分类
          </Button>
        ) : null}
      </div>

      {message ? (
        <div className="fixed right-6 top-24 z-50 flex animate-drop-in items-center gap-3 rounded-full border border-[var(--color-border)] bg-white/92 py-2 pl-5 pr-2 text-sm font-medium shadow-lg backdrop-blur-xl">
          {message}
          <button type="button" onClick={() => setMessage(null)} className="flex h-7 w-7 items-center justify-center rounded-full hover:bg-[var(--color-bg-input)]">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ) : null}

      <Card className="overflow-hidden">
        <div className="grid min-h-[690px] xl:grid-cols-[260px_minmax(440px,1fr)_250px]">
          {/* 分类树 */}
          <aside className="border-b border-[var(--color-border)] bg-[var(--porcelain)]/55 p-4 xl:border-b-0 xl:border-r">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.12em] text-[var(--color-text-hint)]">分类树</p>
                <p className="mt-1 text-[11px] text-[var(--color-text-hint)]">选择节点后在右侧配置</p>
              </div>
              <span className="rounded-lg border border-[var(--color-border)] bg-white px-2 py-1 text-[10px] text-[var(--color-text-hint)]">{roots.length} 科目</span>
            </div>

            <label className="relative mb-3 block">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--color-text-hint)]" />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索名称 / 编码"
                className="h-9 w-full rounded-xl border border-[var(--color-border)] bg-white/80 pl-8 pr-9 text-xs outline-none transition focus:border-[var(--color-primary)]"
              />
              {search ? (
                <button
                  type="button"
                  onClick={() => setSearch("")}
                  className="absolute right-1.5 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-md text-[var(--color-text-hint)] transition hover:bg-[var(--color-primary-light)] hover:text-[var(--ink)]"
                  aria-label="清空分类搜索"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </label>

            <div className="max-h-[570px] space-y-0.5 overflow-y-auto pr-1">
              {isLoading ? (
                <div className="space-y-2">
                  {Array.from({ length: 8 }, (_, index) => <div key={index} className="h-9 animate-pulse rounded-xl bg-white/75" />)}
                </div>
              ) : visibleTree.length ? (
                renderTree(visibleTree)
              ) : (
                <div className="py-12 text-center text-xs text-[var(--color-text-hint)]">无匹配分类</div>
              )}
            </div>

            {canWrite ? (
              <div className="mt-4 border-t border-[var(--color-border)] pt-3">
                <Button variant="secondary" size="sm" className="w-full" onClick={() => openCreateDialog(null)}>
                  <Plus className="h-3.5 w-3.5" /> 新建根分类
                </Button>
              </div>
            ) : null}
          </aside>

          {/* 中央配置区 */}
          <main className="min-w-0 border-b border-[var(--color-border)] p-5 xl:border-b-0 xl:border-r">
            {selectedNode ? (
              <div key={selectedNode.id} className="space-y-5 animate-fade-in">
                <div>
                  <div className="flex flex-wrap items-center gap-1 text-[11px] text-[var(--color-text-hint)]">
                    {selectedPath.map((node, index) => (
                      <span key={node.id} className="inline-flex items-center gap-1">
                        {index > 0 ? <ChevronRight className="h-3 w-3" /> : null}
                        <span className={index === selectedPath.length - 1 ? "font-semibold text-[var(--ink)]" : ""}>{node.name}</span>
                      </span>
                    ))}
                  </div>
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h2 className="text-xl font-bold text-[var(--ink)]">{selectedNode.name}</h2>
                      <p className="mt-1 font-mono text-xs text-[var(--color-text-hint)]">{selectedNode.code}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      {isDirty ? <span className="rounded-lg border border-amber-200 bg-amber-50 px-2 py-1 text-[10px] font-semibold text-amber-700">有未保存修改</span> : null}
                      <span className={`rounded-lg border px-2.5 py-1 text-xs font-semibold ${
                        selectedNode.node_type === "subject"
                          ? "border-blue-200 bg-blue-50 text-blue-700"
                          : selectedNode.node_type === "chapter"
                            ? "border-violet-200 bg-violet-50 text-violet-700"
                            : "border-emerald-200 bg-emerald-50 text-emerald-700"
                      }`}>
                        {TYPE_LABEL[selectedNode.node_type] || selectedNode.node_type}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="flex gap-1 border-b border-[var(--color-border)]">
                  <button
                    type="button"
                    onClick={() => setActiveTab("basic")}
                    className={`border-b-2 px-3 py-2 text-xs transition-colors ${activeTab === "basic" ? "border-[var(--color-primary)] font-bold text-[var(--color-primary-dark)]" : "border-transparent font-medium text-[var(--color-text-hint)] hover:text-[var(--ink)]"}`}
                  >
                    基础信息
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab("children")}
                    className={`border-b-2 px-3 py-2 text-xs transition-colors ${activeTab === "children" ? "border-[var(--color-primary)] font-bold text-[var(--color-primary-dark)]" : "border-transparent font-medium text-[var(--color-text-hint)] hover:text-[var(--ink)]"}`}
                  >
                    子项管理 {selectedNode.children?.length ? `(${selectedNode.children.length})` : ""}
                  </button>
                  <button type="button" className="px-3 py-2 text-xs font-medium text-[var(--color-text-hint)] opacity-55" disabled>关联设置</button>
                  <button type="button" className="px-3 py-2 text-xs font-medium text-[var(--color-text-hint)] opacity-55" disabled>操作日志</button>
                </div>

                {activeTab === "basic" ? (
                  <section key={`basic-${selectedNode.id}`} className="animate-fade-in rounded-2xl border border-[var(--color-border)] bg-white/82 p-5">
                    <div className="mb-5 flex items-center justify-between gap-3">
                      <div>
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-bold text-[var(--ink)]">基础信息</p>
                          {isDirty ? <span className="rounded-md bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">未保存</span> : null}
                        </div>
                        <p className="mt-1 text-[11px] text-[var(--color-text-hint)]">名称、说明、排序和状态可直接维护；编码与层级关系保持只读。</p>
                      </div>
                      <ListTree className="h-5 w-5 text-[var(--color-primary)]" />
                    </div>

                    <div className="grid gap-4 md:grid-cols-2">
                      <label className="space-y-1.5 md:col-span-2">
                        <span className="text-xs font-semibold text-[var(--color-text-secondary)]">名称 *</span>
                        <Input value={editName} onChange={(event) => setEditName(event.target.value)} disabled={!canWrite} />
                      </label>

                      <div className="space-y-1.5">
                        <span className="text-xs font-semibold text-[var(--color-text-secondary)]">编码</span>
                        <div className="flex h-11 items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 font-mono text-xs text-[var(--color-text-secondary)]">
                          <Hash className="h-3.5 w-3.5 text-[var(--color-text-hint)]" /> {selectedNode.code}
                        </div>
                      </div>

                      <div className="space-y-1.5">
                        <span className="text-xs font-semibold text-[var(--color-text-secondary)]">层级</span>
                        <div className="flex h-11 items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-xs text-[var(--color-text-secondary)]">
                          <Layers className="h-3.5 w-3.5 text-[var(--color-text-hint)]" /> {TYPE_LABEL[selectedNode.node_type] || selectedNode.node_type}
                        </div>
                      </div>

                      <div className="space-y-1.5">
                        <span className="text-xs font-semibold text-[var(--color-text-secondary)]">父级</span>
                        <div className="flex h-11 items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-xs text-[var(--color-text-secondary)]">
                          <GitBranch className="h-3.5 w-3.5 text-[var(--color-text-hint)]" /> {parentNode?.name || "根节点"}
                        </div>
                      </div>

                      <label className="space-y-1.5">
                        <span className="text-xs font-semibold text-[var(--color-text-secondary)]">排序</span>
                        <Input
                          type="number"
                          value={editSortOrder}
                          onChange={(event) => setEditSortOrder(event.target.value)}
                          disabled={!canWrite}
                        />
                      </label>

                      <div className="space-y-1.5">
                        <span className="text-xs font-semibold text-[var(--color-text-secondary)]">考试范围</span>
                        <div className="flex h-11 items-center rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 font-mono text-xs text-[var(--color-text-secondary)]">
                          {selectedNode.exam_scope || "—"}
                        </div>
                      </div>

                      <div className="space-y-1.5">
                        <span className="text-xs font-semibold text-[var(--color-text-secondary)]">状态</span>
                        <button
                          type="button"
                          aria-pressed={editActive}
                          disabled={!canWrite}
                          onClick={() => setEditActive((value) => !value)}
                          className="flex h-11 w-full items-center justify-between rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-xs transition hover:border-[var(--color-primary)] disabled:cursor-default"
                        >
                          <span className="flex items-center gap-2 text-[var(--color-text-secondary)]"><Activity className="h-3.5 w-3.5 text-[var(--color-text-hint)]" />当前节点状态</span>
                          <span className={`relative h-5 w-9 rounded-full transition-colors ${editActive ? "bg-[var(--color-primary)]" : "bg-gray-300"}`}>
                            <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${editActive ? "translate-x-[18px]" : "translate-x-0.5"}`} />
                          </span>
                        </button>
                      </div>

                      <label className="space-y-1.5 md:col-span-2">
                        <span className="text-xs font-semibold text-[var(--color-text-secondary)]">说明</span>
                        <textarea
                          value={editDescription}
                          onChange={(event) => setEditDescription(event.target.value)}
                          disabled={!canWrite}
                          rows={4}
                          placeholder="补充该分类的范围、使用约定或维护说明"
                          className="w-full resize-y rounded-xl border border-[var(--color-border)] bg-white px-3 py-2.5 text-sm leading-6 outline-none transition placeholder:text-[var(--color-text-hint)] focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary)]/10 disabled:bg-[var(--color-bg-input)]"
                        />
                      </label>
                    </div>

                    {canWrite ? (
                      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-[var(--color-border)] pt-4">
                        <span className="text-[10px] text-[var(--color-text-hint)]">快捷键 Ctrl / ⌘ + S 保存</span>
                        <div className="flex items-center gap-2">
                          <Button variant="secondary" onClick={resetEdits} disabled={!isDirty || updateMutation.isPending}>取消</Button>
                          <Button onClick={saveChanges} disabled={!editName.trim() || !isDirty || updateMutation.isPending}>
                            {updateMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                            {updateMutation.isPending ? "保存中..." : "保存"}
                          </Button>
                        </div>
                      </div>
                    ) : null}
                  </section>
                ) : (
                  <section key={`children-${selectedNode.id}`} className="animate-fade-in rounded-2xl border border-[var(--color-border)] bg-white/82 p-5">
                    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-bold text-[var(--ink)]">直属子项</p>
                        <p className="mt-1 text-[11px] text-[var(--color-text-hint)]">快速浏览并进入下一级分类，减少反复展开树节点。</p>
                      </div>
                      {canWrite && childTypeLabel ? (
                        <Button size="sm" variant="secondary" onClick={() => openCreateDialog(selectedNode)}>
                          <Plus className="h-3.5 w-3.5" /> 新增{childTypeLabel}
                        </Button>
                      ) : null}
                    </div>

                    {selectedNode.children?.length ? (
                      <div className="stagger-enter space-y-2">
                        {selectedNode.children.map((child) => (
                          <button
                            key={child.id}
                            type="button"
                            onClick={() => selectNode(child)}
                            className="group flex w-full items-center gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--porcelain)]/35 p-3 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-[var(--color-primary)]/45 hover:bg-white hover:shadow-sm"
                          >
                            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]">
                              <Folder className="h-4 w-4" />
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="flex flex-wrap items-center gap-2">
                                <span className="truncate text-sm font-semibold text-[var(--ink)]">{child.name}</span>
                                <span className="rounded-md border border-[var(--color-border)] bg-white px-1.5 py-0.5 text-[9px] text-[var(--color-text-hint)]">{TYPE_LABEL[child.node_type] || child.node_type}</span>
                              </span>
                              <span className="mt-1 block truncate font-mono text-[10px] text-[var(--color-text-hint)]">{child.code}</span>
                            </span>
                            <span className="text-right">
                              <span className="block text-sm font-bold tabular-nums text-[var(--ink)]">{child.subtree_formula_count ?? child.formula_count ?? 0}</span>
                              <span className="text-[9px] text-[var(--color-text-hint)]">公式</span>
                            </span>
                            <ArrowRight className="h-4 w-4 shrink-0 text-[var(--color-text-hint)] transition-transform group-hover:translate-x-0.5 group-hover:text-[var(--color-primary)]" />
                          </button>
                        ))}
                      </div>
                    ) : (
                      <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-[var(--color-border)] bg-[var(--porcelain)]/35 py-12 text-center">
                        <Folder className="h-8 w-8 text-[var(--color-text-hint)]" />
                        <p className="text-sm font-semibold text-[var(--color-text-secondary)]">当前节点没有子项</p>
                        {canWrite && childTypeLabel ? <Button size="sm" variant="secondary" onClick={() => openCreateDialog(selectedNode)}>新建{childTypeLabel}</Button> : null}
                      </div>
                    )}
                  </section>
                )}

                <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--porcelain)]/45 p-4">
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <div className="rounded-xl border border-[var(--color-border)] bg-white p-3">
                      <p className="text-[10px] uppercase tracking-[0.12em] text-[var(--color-text-hint)]">直属公式</p>
                      <p className="mt-1 text-xl font-bold tabular-nums text-[var(--ink)]">{selectedNode.formula_count ?? 0}</p>
                    </div>
                    <div className="rounded-xl border border-[var(--color-border)] bg-white p-3">
                      <p className="text-[10px] uppercase tracking-[0.12em] text-[var(--color-text-hint)]">含子分类公式</p>
                      <p className="mt-1 text-xl font-bold tabular-nums text-[var(--ink)]">{selectedNode.subtree_formula_count ?? selectedNode.formula_count ?? 0}</p>
                    </div>
                    <div className="rounded-xl border border-[var(--color-border)] bg-white p-3">
                      <p className="text-[10px] uppercase tracking-[0.12em] text-[var(--color-text-hint)]">全部后代</p>
                      <p className="mt-1 text-xl font-bold tabular-nums text-[var(--ink)]">{descendantCount}</p>
                    </div>
                    <div className="rounded-xl border border-[var(--color-border)] bg-white p-3">
                      <p className="text-[10px] uppercase tracking-[0.12em] text-[var(--color-text-hint)]">当前深度</p>
                      <p className="mt-1 text-xl font-bold tabular-nums text-[var(--ink)]">{selectedPath.length}</p>
                    </div>
                  </div>
                </section>
              </div>
            ) : (
              <div className="flex h-full min-h-64 flex-col items-center justify-center gap-2 text-center">
                <FolderTree className="h-10 w-10 text-[var(--color-text-hint)]" />
                <p className="text-sm font-semibold text-[var(--color-text-secondary)]">选择分类节点开始配置</p>
              </div>
            )}
          </main>

          {/* 快捷操作 */}
          <aside className="bg-white/65 p-4">
            <div className="sticky top-20 space-y-4">
              <section className="rounded-2xl border border-[var(--color-border)] bg-white p-4">
                <p className="text-xs font-bold uppercase tracking-[0.12em] text-[var(--color-text-hint)]">快捷操作</p>
                <div className="mt-3 space-y-2">
                  {canWrite && childTypeLabel && selectedNode ? (
                    <Button variant="secondary" size="sm" className="w-full justify-start" onClick={() => openCreateDialog(selectedNode)}>
                      <Plus className="h-3.5 w-3.5" /> 新增子{childTypeLabel}
                    </Button>
                  ) : null}
                  {canWrite && selectedNode ? (
                    <Button variant="secondary" size="sm" className="w-full justify-start" onClick={() => openCreateDialog(parentNode)}>
                      <Plus className="h-3.5 w-3.5" /> 同级新增
                    </Button>
                  ) : null}
                  {canWrite ? (
                    <Button variant="secondary" size="sm" className="w-full justify-start" onClick={() => openCreateDialog(null)}>
                      <FolderTree className="h-3.5 w-3.5" /> 新建根分类
                    </Button>
                  ) : null}
                </div>
              </section>

              {selectedNode ? (
                <section className="rounded-2xl border border-[var(--color-border)] bg-white p-4">
                  <p className="text-xs font-bold uppercase tracking-[0.12em] text-[var(--color-text-hint)]">节点概览</p>
                  <dl className="mt-3 space-y-3 text-xs">
                    <div className="flex items-center justify-between gap-3">
                      <dt className="text-[var(--color-text-hint)]">节点类型</dt>
                      <dd className="font-semibold text-[var(--ink)]">{TYPE_LABEL[selectedNode.node_type] || selectedNode.node_type}</dd>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <dt className="flex items-center gap-1.5 text-[var(--color-text-hint)]"><FileText className="h-3.5 w-3.5" />直属公式</dt>
                      <dd className="font-semibold tabular-nums text-[var(--ink)]">{selectedNode.formula_count ?? 0}</dd>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <dt className="text-[var(--color-text-hint)]">含子分类公式</dt>
                      <dd className="font-semibold tabular-nums text-[var(--ink)]">{selectedNode.subtree_formula_count ?? selectedNode.formula_count ?? 0}</dd>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <dt className="text-[var(--color-text-hint)]">直属子项</dt>
                      <dd className="font-semibold tabular-nums text-[var(--ink)]">{selectedNode.children?.length || 0}</dd>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <dt className="text-[var(--color-text-hint)]">状态</dt>
                      <dd className={selectedNode.is_active === false ? "font-semibold text-gray-500" : "font-semibold text-emerald-700"}>
                        {selectedNode.is_active === false ? "已停用" : "已启用"}
                      </dd>
                    </div>
                  </dl>
                </section>
              ) : null}

              <section className="rounded-2xl border border-dashed border-[var(--color-border)] bg-[var(--porcelain)]/45 p-4">
                <div className="flex items-start gap-3">
                  <ListTree className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-primary)]" />
                  <p className="text-[11px] leading-5 text-[var(--color-text-secondary)]">
                    配置台将树结构、节点属性和子项管理拆分为独立区域；父级节点的公式统计按整个子树聚合，与公式库页面的分类筛选口径保持一致。
                  </p>
                </div>
              </section>
            </div>
          </aside>
        </div>
      </Card>

      {showCreateDialog ? <FormulaCategoryDialog parentNode={dialogParent} onClose={closeCreateDialog} /> : null}
    </div>
  );
}

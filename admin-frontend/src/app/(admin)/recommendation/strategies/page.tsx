"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, RefreshCw, Save, Sparkles } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { DataTable } from "@/components/data-table/data-table";
import { apiRequest } from "@/lib/api/client";
import { getErrorMessage } from "@/lib/api/errors";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import type {
  RecommendationScene,
  RecommendationStrategy,
  SeedStrategiesResponse,
} from "@/lib/api/types";

const SCENE_LABELS: Record<string, string> = {
  practice_smart: "智能刷题",
  similar: "相似题",
  knowledge_path: "知识路径",
  wrong_variant: "错题变式",
};

function showToast(msg: string, error = false) {
  const el = document.createElement("div");
  el.className = `fixed left-1/2 top-4 z-[200] -translate-x-1/2 rounded-xl border px-5 py-3 text-sm font-semibold shadow-[var(--shadow-card)] animate-rise-in bg-white ${
    error ? "border-[var(--color-danger)]/30 text-[var(--color-danger)]" : "border-[var(--color-success)]/30 text-[var(--color-success)]"
  }`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2500);
}

export default function RecommendationStrategiesPage() {
  const permissions = useAuthStore((s) => s.permissions);
  const canWrite = hasPermission(permissions, "question:write");
  const queryClient = useQueryClient();

  const [editing, setEditing] = useState<RecommendationStrategy | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});

  const strategies = useQuery({
    queryKey: ["recommendation", "strategies"],
    queryFn: () => apiRequest<RecommendationStrategy[]>("/recommendation/strategies"),
  });

  const seedMutation = useMutation({
    mutationFn: () => apiRequest<SeedStrategiesResponse>("/recommendation/strategies/seed", { method: "POST" }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["recommendation", "strategies"] });
      showToast(`种子完成：新建 ${data.created} / 更新 ${data.updated} / 跳过 ${data.skipped}`);
    },
    onError: (e) => showToast(getErrorMessage(e), true),
  });

  const saveMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      apiRequest<RecommendationStrategy>("/recommendation/strategies", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["recommendation", "strategies"] });
      setEditing(null);
      showToast("策略已保存");
    },
    onError: (e) => showToast(getErrorMessage(e), true),
  });

  const startEdit = (s: RecommendationStrategy) => {
    setEditing(s);
    setForm({
      display_name: s.display_name,
      weight_vector_similarity: String(s.weight_vector_similarity),
      weight_knowledge_overlap: String(s.weight_knowledge_overlap),
      weight_difficulty_match: String(s.weight_difficulty_match),
      weight_mastery_gap: String(s.weight_mastery_gap),
      weight_path_priority: String(s.weight_path_priority),
      exploration_ratio: String(s.exploration_ratio),
    });
  };

  const submitEdit = () => {
    if (!editing) return;
    saveMutation.mutate({
      name: editing.name,
      display_name: form.display_name || editing.display_name,
      scene: editing.scene as RecommendationScene,
      is_active: editing.is_active,
      is_default: editing.is_default,
      weight_vector_similarity: Number(form.weight_vector_similarity),
      weight_knowledge_overlap: Number(form.weight_knowledge_overlap),
      weight_difficulty_match: Number(form.weight_difficulty_match),
      weight_mastery_gap: Number(form.weight_mastery_gap),
      weight_path_priority: Number(form.weight_path_priority),
      exploration_ratio: Number(form.exploration_ratio),
      config_json: editing.config_json,
    });
  };

  const setNum = (key: string, value: string) => setForm((prev) => ({ ...prev, [key]: value }));

  const rows = strategies.data ?? [];

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">推荐策略权重</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">
            每个场景下的权重向量，接入 smart 推荐打分；未配置时使用内置默认值
          </p>
        </div>
        {canWrite && (
          <Button variant="secondary" onClick={() => seedMutation.mutate()} disabled={seedMutation.isPending}>
            <Sparkles className="h-4 w-4" />
            {seedMutation.isPending ? "种子里…" : "种子默认策略"}
          </Button>
        )}
      </div>

      <DataTable<RecommendationStrategy>
        data={rows}
        emptyText="暂无策略配置，点击右上角「种子默认策略」初始化"
        columns={[
          { id: "name", header: "名称", accessorKey: "name" },
          {
            id: "scene",
            header: "场景",
            accessorKey: "scene",
            cell: ({ row }) => SCENE_LABELS[row.original.scene] ?? row.original.scene,
          },
          {
            id: "weights",
            header: "权重 (相似/重叠/难度/掌握/路径)",
            accessorKey: "name",
            cell: ({ row }) => (
              <span className="font-mono text-xs text-[var(--color-text-secondary)]">
                {row.original.weight_vector_similarity.toFixed(2)} / {row.original.weight_knowledge_overlap.toFixed(2)} /{" "}
                {row.original.weight_difficulty_match.toFixed(2)} / {row.original.weight_mastery_gap.toFixed(2)} /{" "}
                {row.original.weight_path_priority.toFixed(2)}
              </span>
            ),
          },
          {
            id: "explore",
            header: "探索率",
            accessorKey: "exploration_ratio",
            cell: ({ row }) => (row.original.exploration_ratio * 100).toFixed(0) + "%",
          },
          {
            id: "flags",
            header: "状态",
            accessorKey: "name",
            cell: ({ row }) => (
              <div className="flex gap-1.5">
                {row.original.is_default && (
                  <span className="rounded-full bg-[var(--color-primary-light)] px-2 py-0.5 text-[11px] text-[var(--color-primary-dark)]">默认</span>
                )}
                <span
                  className={`rounded-full px-2 py-0.5 text-[11px] ${
                    row.original.is_active ? "bg-[#e7f4e7] text-[#3a7d44]" : "bg-[#f6e7e7] text-[#a05656]"
                  }`}
                >
                  {row.original.is_active ? "启用" : "停用"}
                </span>
              </div>
            ),
          },
          {
            id: "action",
            header: "操作",
            accessorKey: "name",
            cell: ({ row }) =>
              canWrite ? (
                <Button variant="secondary" size="sm" onClick={() => startEdit(row.original)}>
                  编辑权重
                </Button>
              ) : (
                <span className="text-xs text-[var(--color-text-hint)]">无权限</span>
              ),
          },
        ]}
      />

      {editing && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <h2 className="text-sm font-bold text-[var(--color-text-primary)]">编辑策略「{editing.name}」</h2>
            <Button variant="ghost" size="sm" onClick={() => setEditing(null)}>
              关闭
            </Button>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
              <label className="text-xs font-semibold text-[var(--color-text-secondary)]">
                显示名
                <input
                  className="mt-1 w-full rounded-xl border border-[var(--color-border)] px-3 py-2 text-sm"
                  value={form.display_name ?? ""}
                  onChange={(e) => setNum("display_name", e.target.value)}
                />
              </label>
              {(
                [
                  ["weight_vector_similarity", "向量相似度"],
                  ["weight_knowledge_overlap", "知识重叠"],
                  ["weight_difficulty_match", "难度匹配"],
                  ["weight_mastery_gap", "掌握度差"],
                  ["weight_path_priority", "路径优先"],
                  ["exploration_ratio", "探索率"],
                ] as const
              ).map(([key, label]) => (
                <label key={key} className="text-xs font-semibold text-[var(--color-text-secondary)]">
                  {label} (0~1)
                  <input
                    type="number"
                    step="0.05"
                    min={0}
                    max={1}
                    className="mt-1 w-full rounded-xl border border-[var(--color-border)] px-3 py-2 text-sm"
                    value={form[key] ?? ""}
                    onChange={(e) => setNum(key, e.target.value)}
                  />
                </label>
              ))}
            </div>
            <div className="flex justify-end gap-2">
              <Button onClick={submitEdit} disabled={saveMutation.isPending}>
                <Save className="h-4 w-4" />
                {saveMutation.isPending ? "保存中…" : "保存"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {strategies.isFetching && (
        <div className="flex items-center gap-2 text-xs text-[var(--color-text-hint)]">
          <RefreshCw className="h-3.5 w-3.5 animate-spin" /> 加载中…
        </div>
      )}
    </div>
  );
}

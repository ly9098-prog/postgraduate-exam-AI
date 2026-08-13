"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Save, Sparkles } from "lucide-react";
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

const STRATEGY_TYPE_LABELS: Record<string, string> = {
  scored: "图谱综合推荐",
  hybrid_graph: "图谱综合推荐",
  weakness_vector: "薄弱向量",
  knowledge_path: "知识路径",
  similar_vector: "相似题向量",
  fallback_random: "随机兜底",
  fallback: "兜底",
};

const SCORED_WEIGHT_FIELDS = [
  ["due_weight", "复习到期"],
  ["weakness_weight", "薄弱知识"],
  ["wrong_weight", "历史错题"],
  ["new_question_weight", "新题探索"],
  ["diversity_weight", "知识多样性"],
  ["path_weight", "知识图谱/路径"],
] as const;

type ScoredWeightKey = (typeof SCORED_WEIGHT_FIELDS)[number][0];

const DEFAULT_SCORED_WEIGHTS: Record<ScoredWeightKey, number> = {
  due_weight: 1,
  weakness_weight: 1,
  wrong_weight: 1,
  new_question_weight: 1,
  diversity_weight: 1,
  path_weight: 1,
};

const DEFAULT_GRAPH_CONFIG = {
  weak_target_limit: 5,
  max_depth: 2,
  max_nodes: 24,
  prerequisite_mastery_threshold: 60,
  prerequisite_confidence_threshold: 0.3,
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function getStrategyType(strategy: RecommendationStrategy): string {
  const configured = asRecord(strategy.config_json).strategy_type;
  if (configured) return String(configured);
  const byName: Record<string, string> = {
    default_scored: "scored",
    default_weakness_vector: "weakness_vector",
    default_knowledge_path: "knowledge_path",
    default_similar_vector: "similar_vector",
    default_random: "fallback_random",
    default_fallback: "fallback",
  };
  return byName[strategy.name] ?? "";
}

function isScoredStrategy(strategy: RecommendationStrategy): boolean {
  return strategy.name === "default_scored" || ["scored", "hybrid_graph"].includes(getStrategyType(strategy));
}

function getScoredWeights(strategy: RecommendationStrategy): Record<ScoredWeightKey, number> {
  const scored = asRecord(asRecord(strategy.config_json).scored_weights);
  return Object.fromEntries(
    SCORED_WEIGHT_FIELDS.map(([key]) => {
      const value = Number(scored[key]);
      return [key, Number.isFinite(value) ? value : DEFAULT_SCORED_WEIGHTS[key]];
    }),
  ) as Record<ScoredWeightKey, number>;
}

function getGraphConfig(strategy: RecommendationStrategy) {
  const graph = asRecord(asRecord(strategy.config_json).graph);
  const num = (key: keyof typeof DEFAULT_GRAPH_CONFIG) => {
    const value = Number(graph[key]);
    return Number.isFinite(value) ? value : DEFAULT_GRAPH_CONFIG[key];
  };
  return {
    weak_target_limit: num("weak_target_limit"),
    max_depth: num("max_depth"),
    max_nodes: num("max_nodes"),
    prerequisite_mastery_threshold: num("prerequisite_mastery_threshold"),
    prerequisite_confidence_threshold: num("prerequisite_confidence_threshold"),
  };
}

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
      showToast("策略已保存，新权重会参与后续推荐请求");
    },
    onError: (e) => showToast(getErrorMessage(e), true),
  });

  const startEdit = (s: RecommendationStrategy) => {
    const scoredWeights = getScoredWeights(s);
    setEditing(s);
    setForm({
      display_name: s.display_name,
      weight_vector_similarity: String(s.weight_vector_similarity),
      weight_knowledge_overlap: String(s.weight_knowledge_overlap),
      weight_difficulty_match: String(s.weight_difficulty_match),
      weight_mastery_gap: String(s.weight_mastery_gap),
      weight_path_priority: String(s.weight_path_priority),
      exploration_ratio: String(s.exploration_ratio),
      ...Object.fromEntries(SCORED_WEIGHT_FIELDS.map(([key]) => [`scored_${key}`, String(scoredWeights[key])])),
    });
  };

  const submitEdit = () => {
    if (!editing) return;

    const parseNumber = (key: string, min: number, max: number) => {
      const raw = form[key]?.trim();
      if (!raw) return null;
      const value = Number(raw);
      return Number.isFinite(value) && value >= min && value <= max ? value : null;
    };

    const legacyKeys = [
      "weight_vector_similarity",
      "weight_knowledge_overlap",
      "weight_difficulty_match",
      "weight_mastery_gap",
      "weight_path_priority",
      "exploration_ratio",
    ];
    const legacyValues = Object.fromEntries(legacyKeys.map((key) => [key, parseNumber(key, 0, 1)]));
    if (Object.values(legacyValues).some((value) => value == null)) {
      showToast("请完整填写 0~1 范围内的策略权重", true);
      return;
    }

    let configJson = editing.config_json;
    if (isScoredStrategy(editing)) {
      const scoredValues = Object.fromEntries(
        SCORED_WEIGHT_FIELDS.map(([key]) => [key, parseNumber(`scored_${key}`, 0, 2)]),
      );
      if (Object.values(scoredValues).some((value) => value == null)) {
        showToast("综合推荐权重必须完整填写，范围为 0~2", true);
        return;
      }

      const baseConfig = asRecord(editing.config_json);
      const existingScored = asRecord(baseConfig.scored_weights);
      configJson = {
        ...baseConfig,
        strategy_type: "scored",
        scored_weights: {
          ...existingScored,
          ...scoredValues,
        },
      };
    }

    saveMutation.mutate({
      name: editing.name,
      display_name: form.display_name?.trim() || editing.display_name,
      scene: editing.scene as RecommendationScene,
      is_active: editing.is_active,
      is_default: editing.is_default,
      ...legacyValues,
      config_json: configJson,
    });
  };

  const setField = (key: string, value: string) => setForm((prev) => ({ ...prev, [key]: value }));

  const rows = strategies.data ?? [];
  const editingScored = editing ? isScoredStrategy(editing) : false;
  const graphConfig = editing ? getGraphConfig(editing) : DEFAULT_GRAPH_CONFIG;

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">推荐策略权重</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">
            智能刷题的 scored 策略使用“系统全局权重 × 用户自适应权重”；其他策略继续使用原有向量权重
          </p>
        </div>
        {canWrite && (
          <Button variant="secondary" onClick={() => seedMutation.mutate()} disabled={seedMutation.isPending}>
            <Sparkles className="h-4 w-4" />
            {seedMutation.isPending ? "种子中…" : "种子默认策略"}
          </Button>
        )}
      </div>

      <div className="rounded-xl border border-[var(--color-border)] bg-white/60 px-4 py-3 text-xs leading-5 text-[var(--color-text-secondary)]">
        <strong className="text-[var(--color-text-primary)]">智能刷题默认主策略：</strong> default_scored（图谱综合推荐）。
        A/B 实验运行时可按用户分组覆盖默认策略；系统权重 1.0 表示中性，用户级个性化微调仍由后端自动维护。
      </div>

      <DataTable<RecommendationStrategy>
        data={rows}
        emptyText="暂无策略配置，点击右上角「种子默认策略」初始化"
        columns={[
          { id: "name", header: "名称", accessorKey: "name" },
          {
            id: "type",
            header: "策略类型",
            accessorKey: "name",
            cell: ({ row }) => {
              const type = getStrategyType(row.original);
              return STRATEGY_TYPE_LABELS[type] ?? (type || "未标注");
            },
          },
          {
            id: "scene",
            header: "场景",
            accessorKey: "scene",
            cell: ({ row }) => SCENE_LABELS[row.original.scene] ?? row.original.scene,
          },
          {
            id: "weights",
            header: "核心权重",
            accessorKey: "name",
            cell: ({ row }) => {
              if (isScoredStrategy(row.original)) {
                const w = getScoredWeights(row.original);
                return (
                  <span className="font-mono text-xs text-[var(--color-text-secondary)]" title="复习 / 薄弱 / 错题 / 新题 / 多样性 / 图谱">
                    {w.due_weight.toFixed(2)} / {w.weakness_weight.toFixed(2)} / {w.wrong_weight.toFixed(2)} / {w.new_question_weight.toFixed(2)} / {w.diversity_weight.toFixed(2)} / {w.path_weight.toFixed(2)}
                  </span>
                );
              }
              return (
                <span className="font-mono text-xs text-[var(--color-text-secondary)]" title="相似 / 重叠 / 难度 / 掌握 / 路径">
                  {row.original.weight_vector_similarity.toFixed(2)} / {row.original.weight_knowledge_overlap.toFixed(2)} /{" "}
                  {row.original.weight_difficulty_match.toFixed(2)} / {row.original.weight_mastery_gap.toFixed(2)} /{" "}
                  {row.original.weight_path_priority.toFixed(2)}
                </span>
              );
            },
          },
          {
            id: "explore",
            header: "探索率",
            accessorKey: "exploration_ratio",
            cell: ({ row }) => isScoredStrategy(row.original) ? "—" : (row.original.exploration_ratio * 100).toFixed(0) + "%",
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
            <div>
              <h2 className="text-sm font-bold text-[var(--color-text-primary)]">编辑策略「{editing.name}」</h2>
              {editingScored && (
                <p className="mt-1 text-xs text-[var(--color-text-hint)]">
                  以下为系统级乘数，会与每个用户的自适应权重相乘后进入综合打分。
                </p>
              )}
            </div>
            <Button variant="ghost" size="sm" onClick={() => setEditing(null)}>
              关闭
            </Button>
          </CardHeader>
          <CardContent className="grid gap-5">
            <label className="max-w-md text-xs font-semibold text-[var(--color-text-secondary)]">
              显示名
              <input
                className="mt-1 w-full rounded-xl border border-[var(--color-border)] px-3 py-2 text-sm"
                value={form.display_name ?? ""}
                onChange={(e) => setField("display_name", e.target.value)}
              />
            </label>

            {editingScored ? (
              <>
                <div>
                  <div className="mb-2 text-xs font-bold text-[var(--color-text-primary)]">综合推荐系统权重</div>
                  <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
                    {SCORED_WEIGHT_FIELDS.map(([key, label]) => (
                      <label key={key} className="text-xs font-semibold text-[var(--color-text-secondary)]">
                        {label} (0~2，1 为中性)
                        <input
                          type="number"
                          step="0.05"
                          min={0}
                          max={2}
                          className="mt-1 w-full rounded-xl border border-[var(--color-border)] px-3 py-2 text-sm"
                          value={form[`scored_${key}`] ?? "1"}
                          onChange={(e) => setField(`scored_${key}`, e.target.value)}
                        />
                      </label>
                    ))}
                  </div>
                </div>

                <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/50 p-4">
                  <div className="text-xs font-bold text-[var(--color-text-primary)]">知识图谱运行参数（当前只读）</div>
                  <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-2 text-xs text-[var(--color-text-secondary)] md:grid-cols-5">
                    <span>薄弱目标上限：{graphConfig.weak_target_limit}</span>
                    <span>最大前置深度：{graphConfig.max_depth}</span>
                    <span>最大扩展节点：{graphConfig.max_nodes}</span>
                    <span>前置掌握阈值：{graphConfig.prerequisite_mastery_threshold}</span>
                    <span>前置置信阈值：{graphConfig.prerequisite_confidence_threshold}</span>
                  </div>
                  <p className="mt-2 text-[11px] text-[var(--color-text-hint)]">
                    这些参数用于 prerequisite gating 和候选扩展。当前不开放页面编辑，避免误配置导致推荐路径大幅漂移。
                  </p>
                </div>
              </>
            ) : (
              <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
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
                      onChange={(e) => setField(key, e.target.value)}
                    />
                  </label>
                ))}
              </div>
            )}

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

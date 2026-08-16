"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Play, Pause, Flag, ShieldCheck, GitCompareArrows, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { DataTable } from "@/components/data-table/data-table";
import { apiRequest, toQuery } from "@/lib/api/client";
import { getErrorMessage } from "@/lib/api/errors";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import { chinaDateString } from "@/lib/time";
import type { ExperimentCreate, RecommendationExperiment, VariantComparisonResponse } from "@/lib/api/types";

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  running: "运行中",
  paused: "已暂停",
  finished: "已结束",
};

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-[#eceff3] text-[#5b7b9a]",
  running: "bg-[#e7f4e7] text-[#3a7d44]",
  paused: "bg-[#f6e7e7] text-[#a05656]",
  finished: "bg-[#eceff3] text-[#8a8f98]",
};

// 分组 JSON 快捷填入模板（strategy 需为智能刷题引擎识别的值）
const VARIANT_PRESETS: { label: string; json: string }[] = [
  {
    label: "推荐：原薄弱 vs 图谱综合",
    json: `[{"key":"A","strategy":"weakness_vector","ratio":0.5},{"key":"B","strategy":"scored","ratio":0.5}]`,
  },
  {
    label: "对照：原薄弱 vs 纯路径",
    json: `[{"key":"A","strategy":"weakness_vector","ratio":0.5},{"key":"B","strategy":"path","ratio":0.5}]`,
  },
  {
    label: "A/B/C：薄弱/路径/图谱综合",
    json: `[{"key":"A","strategy":"weakness_vector","ratio":0.34},{"key":"B","strategy":"path","ratio":0.33},{"key":"C","strategy":"scored","ratio":0.33}]`,
  },
];

function showToast(msg: string, error = false) {
  const el = document.createElement("div");
  el.className = `fixed left-1/2 top-4 z-[200] -translate-x-1/2 rounded-xl border px-5 py-3 text-sm font-semibold shadow-[var(--shadow-card)] animate-rise-in bg-white ${
    error ? "border-[var(--color-danger)]/30 text-[var(--color-danger)]" : "border-[var(--color-success)]/30 text-[var(--color-success)]"
  }`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2500);
}

function todayISO(): string {
  return chinaDateString();
}

function daysAgoISO(days: number): string {
  return chinaDateString(-days);
}

export default function RecommendationExperimentsPage() {
  const permissions = useAuthStore((s) => s.permissions);
  const canWrite = hasPermission(permissions, "question:write");
  const queryClient = useQueryClient();

  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [scene, setScene] = useState("practice_smart");
  const [variantsText, setVariantsText] = useState("");
  const [compareId, setCompareId] = useState<number | null>(null);

  const experiments = useQuery({
    queryKey: ["recommendation", "experiments"],
    queryFn: () => apiRequest<RecommendationExperiment[]>("/recommendation/experiments"),
  });

  const compare = useQuery({
    queryKey: ["recommendation", "experiments", "compare", compareId],
    enabled: compareId != null,
    queryFn: () =>
      apiRequest<VariantComparisonResponse>(
        `/recommendation/experiments/${compareId}/compare${toQuery({ date_from: daysAgoISO(30), date_to: todayISO() })}`,
      ),
  });

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) =>
      apiRequest<RecommendationExperiment>(`/recommendation/experiments/${id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["recommendation", "experiments"] });
      showToast("实验状态已更新");
    },
    onError: (e) => showToast(getErrorMessage(e), true),
  });

  const safetyMutation = useMutation({
    mutationFn: (id: number) =>
      apiRequest<{ paused: boolean; reason: string | null }>(
        `/recommendation/experiments/${id}/safety-check${toQuery({ date_from: daysAgoISO(30), date_to: todayISO() })}`,
        { method: "POST" },
      ),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["recommendation", "experiments"] });
      showToast(data.paused ? `已自动暂停：${data.reason ?? "错误率过高"}` : "安全检查通过，未触发暂停");
    },
    onError: (e) => showToast(getErrorMessage(e), true),
  });

  const createMutation = useMutation({
    mutationFn: (payload: ExperimentCreate) =>
      apiRequest<RecommendationExperiment>("/recommendation/experiments", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["recommendation", "experiments"] });
      setCreateOpen(false);
      setName("");
      setVariantsText("");
      showToast("实验已创建");
    },
    onError: (e) => showToast(getErrorMessage(e), true),
  });

  const submitCreate = () => {
    if (!name.trim()) {
      showToast("请输入实验名称", true);
      return;
    }

    let raw: unknown;
    try {
      raw = JSON.parse(variantsText || "[]");
    } catch {
      showToast("分组 JSON 格式错误", true);
      return;
    }
    if (!Array.isArray(raw) || raw.length < 2) {
      showToast("分组必须是 JSON 数组，且至少需要 2 个分组", true);
      return;
    }

    const parsed = raw as ExperimentCreate["variants"];
    const validShape = parsed.every((variant) =>
      variant
      && typeof variant.key === "string"
      && variant.key.trim().length > 0
      && typeof variant.strategy === "string"
      && variant.strategy.trim().length > 0
      && typeof variant.ratio === "number"
      && Number.isFinite(variant.ratio)
      && variant.ratio >= 0
      && variant.ratio <= 1,
    );
    if (!validShape) {
      showToast("每个分组都需要有效的 key、strategy 和 0~1 ratio", true);
      return;
    }
    if (new Set(parsed.map((variant) => variant.key.trim())).size !== parsed.length) {
      showToast("分组 key 不能重复", true);
      return;
    }
    const ratioSum = parsed.reduce((sum, variant) => sum + variant.ratio, 0);
    if (Math.abs(ratioSum - 1) > 1e-6) {
      showToast(`分组 ratio 总和必须为 1，当前为 ${ratioSum.toFixed(4)}`, true);
      return;
    }

    createMutation.mutate({ name: name.trim(), scene, variants: parsed, traffic_ratio: 1.0 });
  };

  const rows = experiments.data ?? [];
  const compareRow = compare.data;

  const compareVariants = useMemo(() => {
    if (!compareRow) return [];
    return (compareRow.variants ?? []).map((v) => ({
      key: String(v.variant_key ?? "?"),
      exposure: Number(v.exposure_count ?? 0),
      answer: Number(v.answer_count ?? 0),
      accuracy: Number(v.accuracy ?? 0),
      completionRate: Number(v.completion_rate ?? 0),
      masteryDelta: v.avg_mastery_delta == null ? null : Number(v.avg_mastery_delta),
      ctr: Number(v.ctr ?? 0),
    }));
  }, [compareRow]);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">推荐 A/B 实验</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">
            创建实验并为用户稳定分组；建议以 weakness_vector 为 Control、scored（图谱综合推荐）为 Treatment
          </p>
        </div>
        {canWrite && (
          <Button onClick={() => setCreateOpen((v) => !v)}>
            <Plus className="h-4 w-4" />
            新建实验
          </Button>
        )}
      </div>

      {createOpen && (
        <Card>
          <CardHeader className="text-sm font-bold text-[var(--color-text-primary)]">新建实验</CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid grid-cols-2 gap-4">
              <label className="text-xs font-semibold text-[var(--color-text-secondary)]">
                实验名称
                <input
                  className="mt-1 w-full rounded-xl border border-[var(--color-border)] px-3 py-2 text-sm"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <label className="text-xs font-semibold text-[var(--color-text-secondary)]">
                场景
                <select
                  className="mt-1 w-full rounded-xl border border-[var(--color-border)] px-3 py-2 text-sm"
                  value={scene}
                  onChange={(e) => setScene(e.target.value)}
                >
                  <option value="practice_smart">智能刷题</option>
                  <option value="similar" disabled>相似题（暂未接入实验分流）</option>
                  <option value="knowledge_path" disabled>知识路径（暂未接入实验分流）</option>
                </select>
                <span className="mt-1 block text-[10px] font-normal text-[var(--color-text-hint)]">当前运行时仅智能刷题会解析 A/B 实验。</span>
              </label>
            </div>
            <label className="text-xs font-semibold text-[var(--color-text-secondary)]">
              分组 (JSON，示例 [{"{\"key\":\"A\",\"strategy\":\"weakness_vector\",\"ratio\":0.5},{\"key\":\"B\",\"strategy\":\"path\",\"ratio\":0.5}"}])
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <span className="text-xs text-[var(--color-text-hint)]">快捷填入：</span>
                {VARIANT_PRESETS.map((p) => (
                  <button
                    key={p.label}
                    type="button"
                    onClick={() => setVariantsText(p.json)}
                    className="rounded-full border border-[var(--color-border)] bg-white/70 px-2.5 py-1 text-xs text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary)] hover:text-[var(--color-primary-dark)]"
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <textarea
                rows={3}
                className="mt-1 w-full rounded-xl border border-[var(--color-border)] px-3 py-2 font-mono text-xs"
                value={variantsText}
                onChange={(e) => setVariantsText(e.target.value)}
                placeholder='[{"key":"A","strategy":"weakness_vector","ratio":0.5},{"key":"B","strategy":"scored","ratio":0.5}]'
              />
            </label>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setCreateOpen(false)}>
                取消
              </Button>
              <Button onClick={submitCreate} disabled={createMutation.isPending}>
                {createMutation.isPending ? "创建中…" : "创建"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <DataTable<RecommendationExperiment>
        data={rows}
        emptyText="暂无实验，点击右上角「新建实验」"
        columns={[
          { id: "name", header: "名称", accessorKey: "name" },
          { id: "scene", header: "场景", accessorKey: "scene" },
          {
            id: "status",
            header: "状态",
            accessorKey: "status",
            cell: ({ row }) => (
              <span className={`rounded-full px-2 py-0.5 text-[11px] ${STATUS_COLORS[row.original.status] ?? "bg-[#eceff3] text-[#5b7b9a]"}`}>
                {STATUS_LABELS[row.original.status] ?? row.original.status}
              </span>
            ),
          },
          {
            id: "variants",
            header: "分组",
            accessorKey: "variants",
            cell: ({ row }) => (
              <span className="font-mono text-xs text-[var(--color-text-secondary)]">
                {(row.original.variants ?? []).map((v) => `${v.key}:${Math.round((v.ratio ?? 0) * 100)}%`).join("  ")}
              </span>
            ),
          },
          {
            id: "action",
            header: "操作",
            accessorKey: "id",
            cell: ({ row }) => {
              const st = row.original.status;
              return (
                <div className="flex gap-1.5">
                  {canWrite && st === "draft" && (
                    <Button size="sm" onClick={() => statusMutation.mutate({ id: row.original.id, status: "running" })}>
                      <Play className="h-3.5 w-3.5" /> 启动
                    </Button>
                  )}
                  {canWrite && st === "running" && (
                    <>
                      <Button variant="secondary" size="sm" onClick={() => statusMutation.mutate({ id: row.original.id, status: "paused" })}>
                        <Pause className="h-3.5 w-3.5" /> 暂停
                      </Button>
                      <Button variant="secondary" size="sm" onClick={() => safetyMutation.mutate(row.original.id)} disabled={safetyMutation.isPending}>
                        <ShieldCheck className="h-3.5 w-3.5" /> 安全检查
                      </Button>
                    </>
                  )}
                  {canWrite && st === "paused" && (
                    <Button variant="secondary" size="sm" onClick={() => statusMutation.mutate({ id: row.original.id, status: "running" })}>
                      <Play className="h-3.5 w-3.5" /> 继续
                    </Button>
                  )}
                  {canWrite && st !== "finished" && (
                    <Button variant="secondary" size="sm" onClick={() => statusMutation.mutate({ id: row.original.id, status: "finished" })}>
                      <Flag className="h-3.5 w-3.5" /> 结束
                    </Button>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => setCompareId(row.original.id)}>
                    <GitCompareArrows className="h-3.5 w-3.5" /> 对比
                  </Button>
                </div>
              );
            },
          },
        ]}
      />

      {compareRow && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <h2 className="text-sm font-bold text-[var(--color-text-primary)]">分组对比（近 30 天）— {compareRow.experiment_name}</h2>
            <Button variant="ghost" size="sm" onClick={() => setCompareId(null)}>
              关闭
            </Button>
          </CardHeader>
          <CardContent>
            <DataTable<{ key: string; exposure: number; answer: number; accuracy: number; completionRate: number; masteryDelta: number | null; ctr: number }>
              data={compareVariants}
              emptyText="暂无该实验的推荐日志数据"
              columns={[
                { id: "key", header: "分组", accessorKey: "key" },
                { id: "exposure", header: "曝光", accessorKey: "exposure" },
                { id: "answer", header: "答题", accessorKey: "answer" },
                {
                  id: "accuracy",
                  header: "正确率",
                  accessorKey: "accuracy",
                  cell: ({ row }) => `${(row.original.accuracy * 100).toFixed(1)}%`,
                },
                {
                  id: "completionRate",
                  header: "完成率",
                  accessorKey: "completionRate",
                  cell: ({ row }) => `${(row.original.completionRate * 100).toFixed(1)}%`,
                },
                {
                  id: "masteryDelta",
                  header: "掌握度提升",
                  accessorKey: "masteryDelta",
                  cell: ({ row }) => row.original.masteryDelta == null ? "—" : `${row.original.masteryDelta >= 0 ? "+" : ""}${row.original.masteryDelta.toFixed(2)}`,
                },
                {
                  id: "ctr",
                  header: "点击率",
                  accessorKey: "ctr",
                  cell: ({ row }) => `${(row.original.ctr * 100).toFixed(1)}%`,
                },
              ]}
            />
          </CardContent>
        </Card>
      )}

      <div className="flex items-center gap-2 text-xs text-[var(--color-text-hint)]">
        <FlaskConical className="h-3.5 w-3.5" /> 实验通过稳定 hash 为用户分组，用户在同一实验中始终命中同一分组
      </div>
    </div>
  );
}

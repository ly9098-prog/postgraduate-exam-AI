"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Ban, Power, Save, Sparkles, SlidersHorizontal, CheckCircle2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Toggle } from "@/components/ui/toggle";
import { cn } from "@/lib/utils";
import { apiRequest, toQuery } from "@/lib/api/client";
import { getErrorMessage } from "@/lib/api/errors";
import { useAuthStore } from "@/lib/auth/auth-store";
import type { AISettings, AISettingsPatchRequest, AIStatsResponse, AdminAiConfigsResponse, AdminAiModelConfig } from "@/lib/api/types";
import { StatCards } from "./components/stat-cards";
import { TrendChart } from "./components/trend-chart";
import { ModelCards } from "./components/model-cards";
import { OcrAccordion } from "./components/ocr-accordion";
import { AiCompletionPreview } from "./components/ai-completion";
import { VectorConfigSection } from "./components/vector-config-section";

type Tab = "overview" | "models" | "ocr" | "completion" | "vector" | "system";

const TABS: { key: Tab; label: string; icon: string; color: string }[] = [
  { key: "overview", label: "总览", icon: "📊", color: "#5b7b9a" },
  { key: "models", label: "模型", icon: "🤖", color: "#6b9b6b" },
  { key: "ocr", label: "OCR", icon: "📝", color: "#c49a6b" },
  { key: "completion", label: "补全", icon: "✨", color: "#9a7aba" },
  { key: "vector", label: "向量", icon: "🔍", color: "#5b7b9a" },
  { key: "system", label: "系统", icon: "⚙️", color: "#c47a7a" },
];

export default function AISettingsPage() {
  const role = useAuthStore((s) => s.role);
  const isSuperAdmin = role?.name === "super_admin";
  const queryClient = useQueryClient();
  const [monthlyLimit, setMonthlyLimit] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>("overview");

  function showToast(msg: string) {
    const el = document.createElement("div");
    el.className = "fixed left-1/2 top-4 z-[200] -translate-x-1/2 rounded-xl border border-[var(--color-success)]/30 bg-white px-5 py-3 text-sm font-semibold text-[var(--color-success)] shadow-[var(--shadow-card)] animate-rise-in";
    el.innerHTML = `<svg class="-mt-0.5 mr-1.5 inline-block h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>${msg}`;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 2500);
  }

  const settings = useQuery({
    queryKey: ["ai-settings"],
    queryFn: async () => {
      const data = await apiRequest<AISettings>("/ai-settings");
      setEnabled(data.ai_parse_enabled);
      setMonthlyLimit(String(data.monthly_call_limit));
      return data;
    },
  });

  const stats = useQuery({
    queryKey: ["ai-settings", "stats"],
    queryFn: () => apiRequest<AIStatsResponse>(`/ai-settings/stats${toQuery({ days: 30 })}`),
  });

  const configs = useQuery({
    queryKey: ["ai-configs"],
    queryFn: () => apiRequest<AdminAiConfigsResponse>("/ai-configs"),
    select: (data) => data.configs,
  });

  const models = useQuery({
    queryKey: ["ai-models"],
    queryFn: () => apiRequest<AdminAiModelConfig[]>("/ai-models"),
  });

  const resolvedModels = useMemo(() => {
    const list = models.data ?? [];
    const isPaddleOcr = (provider: string) => { const p = provider.toLowerCase().replace(/_/g, "-"); return p === "paddle" || p.startsWith("paddleocr"); };
    const resolve = (featurePriority: string[], mode: "chat" | "paddle" = "chat"): string | null => {
      const candidates = list.filter((m) => {
        const features = m.features ?? (m.feature ? [m.feature] : []);
        const isEmbedding = features.includes("embedding");
        return m.is_enabled
          && !isEmbedding
          && (mode === "paddle" ? isPaddleOcr(m.provider) : !isPaddleOcr(m.provider));
      });
      for (const feature of featurePriority) {
        const featured = candidates.find((m) => (m.features ?? []).includes(feature));
        if (featured) return featured.display_name;
      }
      const untagged = candidates.find((m) => !m.features || m.features.length === 0);
      if (untagged) return untagged.display_name;
      return candidates[0]?.display_name ?? null;
    };
    return {
      ocr: resolve(["ocr_fix", "text_correction", "ocr"]),
      completion: resolve(["completion"]),
      analysis: resolve(["analysis"]),
      vision: resolve(["vision"], "paddle"),
    };
  }, [models.data]);

  const current = settings.data;
  const usageRate = useMemo(() => {
    if (!current || current.monthly_call_limit <= 0) return 0;
    return Math.min(Math.round((current.current_usage.call_count / current.monthly_call_limit) * 100), 100);
  }, [current]);

  const updateMutation = useMutation({
    mutationFn: (payload: AISettingsPatchRequest) =>
      apiRequest<AISettings>("/ai-settings", { method: "PATCH", body: JSON.stringify(payload) }),
    onSuccess: (data) => {
      setConfirmOpen(false);
      setEnabled(data.ai_parse_enabled);
      setMonthlyLimit(String(data.monthly_call_limit));
      queryClient.setQueryData(["ai-settings"], data);
      showToast("AI 解析设置已保存");
    },
    onError: (error) => showToast(getErrorMessage(error)),
  });

  const parsedLimit = Number(monthlyLimit);
  const hasChanges = current
    ? enabled !== current.ai_parse_enabled || parsedLimit !== current.monthly_call_limit
    : false;
  const canSave = hasChanges && Number.isInteger(parsedLimit) && parsedLimit >= 0 && !updateMutation.isPending;

  const save = () => {
    if (!current || !canSave) return;
    updateMutation.mutate({ ai_parse_enabled: enabled, monthly_call_limit: parsedLimit });
  };

  if (!isSuperAdmin) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[var(--color-danger-light)]">
          <Ban className="h-8 w-8 text-[var(--color-danger)]" />
        </div>
        <h3 className="text-xl font-semibold text-[var(--ink)]">权限不足</h3>
        <p className="max-w-sm text-sm text-[var(--color-text-secondary)]">仅超级管理员可访问 AI 解析设置页面</p>
      </div>
    );
  }

  const activeTabMeta = TABS.find((t) => t.key === activeTab)!;

  return (
    <div className="overflow-hidden rounded-2xl border border-[var(--color-border)]/80 bg-white/80 shadow-[var(--shadow-card)] animate-rise-in">
      {/* ── Header ── */}
      <div className="flex items-center justify-between border-b border-[var(--color-border)]/60 px-5 py-4">
        <div>
          <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.25em] text-[var(--color-text-hint)]">
            AI Operations Center
          </p>
          <h2 className="mt-1 font-display text-xl font-bold text-[var(--ink)]">AI 解析设置</h2>
          <p className="mt-0.5 text-sm text-[var(--color-text-secondary)]">
            管理 OCR 纠错、题目补全、AI 解析生成等能力
          </p>
        </div>
        <span
          className={cn(
            "rounded-full px-3 py-1 text-[11px] font-semibold",
            current?.ai_parse_enabled
              ? "bg-[var(--color-success-light)] text-[var(--color-success)]"
              : "bg-[var(--color-danger-light)] text-[var(--color-danger)]",
          )}
        >
          {current?.ai_parse_enabled ? "● 解析开启" : "● 全局关闭"}
        </span>
      </div>

      {/* ── Tab bar ── */}
      <div className="flex border-b border-[var(--color-border)]/60 bg-[var(--color-bg-input)]/30">
        {TABS.map((t) => {
          const active = activeTab === t.key;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setActiveTab(t.key)}
              className={cn(
                "flex flex-1 items-center justify-center gap-1.5 py-3 text-xs transition-all",
                active ? "font-semibold" : "font-medium text-[var(--color-text-hint)] hover:text-[var(--color-text-secondary)]",
              )}
              style={{
                color: active ? t.color : undefined,
                borderBottom: active ? `2px solid ${t.color}` : "2px solid transparent",
              }}
            >
              <span className="text-sm">{t.icon}</span>
              {t.label}
            </button>
          );
        })}
      </div>

      {/* ── Tab content ── */}
      <div className="p-5">
        {/* ═══ 总览 ═══ */}
        {activeTab === "overview" && (
          <div className="space-y-5 animate-rise-in">
            {stats.isError ? (
              <p className="rounded-xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-4 py-3 text-sm text-[var(--color-danger)]">
                {getErrorMessage(stats.error)}
              </p>
            ) : (
              <StatCards stats={stats.data} loading={stats.isLoading} />
            )}
            <TrendChart trends={stats.data?.daily_trends} loading={stats.isLoading} />
          </div>
        )}

        {/* ═══ 模型 ═══ */}
        {activeTab === "models" && (
          <div className="animate-rise-in">
            <ModelCards />
          </div>
        )}

        {/* ═══ OCR ═══ */}
        {activeTab === "ocr" && (
          <div className="animate-rise-in">
            {configs.isError && (
              <p className="mb-4 rounded-xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-4 py-3 text-sm text-[var(--color-danger)]">
                {getErrorMessage(configs.error)}
              </p>
            )}
            <OcrAccordion configs={configs.data} loading={configs.isLoading} modelName={resolvedModels.ocr} />
          </div>
        )}

        {/* ═══ 补全 ═══ */}
        {activeTab === "completion" && (
          <div className="animate-rise-in">
            {configs.isError && (
              <p className="mb-4 rounded-xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-4 py-3 text-sm text-[var(--color-danger)]">
                {getErrorMessage(configs.error)}
              </p>
            )}
            <AiCompletionPreview configs={configs.data} loading={configs.isLoading} modelName={resolvedModels.completion} />
          </div>
        )}

        {/* ═══ 向量 ═══ */}
        {activeTab === "vector" && (
          <div className="animate-rise-in">
            <VectorConfigSection />
          </div>
        )}

        {/* ═══ 系统 ═══ */}
        {activeTab === "system" && (
          <div className="space-y-4 animate-rise-in">
            {/* Section header */}
            <div className="flex items-center gap-2">
              <SlidersHorizontal className="h-4 w-4" style={{ color: activeTabMeta.color }} />
              <span className="text-sm font-semibold" style={{ color: activeTabMeta.color }}>
                全局 AI 解析开关与月度调用额度
              </span>
            </div>

            {/* Error */}
            {settings.isError && (
              <p className="rounded-lg border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-3 py-2 text-sm text-[var(--color-danger)]">
                {getErrorMessage(settings.error)}
              </p>
            )}

            {/* Warning */}
            <div className="flex items-start gap-2.5 rounded-lg border border-[var(--color-warning)]/25 bg-[var(--color-warning-light)] px-3 py-2.5">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--color-warning)]" />
              <p className="text-[11px] leading-5 text-[var(--color-text-secondary)]">
                全局关闭后所有管理员都不能新建 AI 解析任务，super_admin 也受影响；月度额度为全局 API
                调用量，super_admin 不受额度限制。
              </p>
            </div>

            {/* Toggle + limit */}
            <div className="grid gap-3 md:grid-cols-2">
              <div className="flex items-center justify-between gap-3 rounded-xl border border-[var(--color-border)]/60 bg-[var(--color-bg-input)] p-4">
                <div className="flex items-start gap-2.5">
                  <Power
                    className="mt-0.5 h-4 w-4"
                    style={{ color: enabled ? "var(--color-success)" : "var(--color-text-hint)" }}
                  />
                  <div>
                    <span className="text-sm font-semibold text-[var(--ink)]">全局 AI 解析</span>
                    <p className="mt-0.5 text-[11px] text-[var(--color-text-hint)]">关闭后拒绝创建新任务</p>
                  </div>
                </div>
                <Toggle
                  checked={enabled}
                  onChange={() => setEnabled(!enabled)}
                  disabled={!current || updateMutation.isPending}
                />
              </div>

              <div className="rounded-xl border border-[var(--color-border)]/60 bg-[var(--color-bg-input)] p-4">
                <span className="text-sm font-semibold text-[var(--ink)]">月度 API 调用额度</span>
                <p className="mt-0.5 text-[11px] text-[var(--color-text-hint)]">0 = 不限制；仅限制非 super_admin</p>
                <div className="relative mt-2">
                  <input
                    className="h-9 w-full rounded-lg border border-[var(--color-border)] bg-white pl-3 pr-10 text-sm outline-none transition-colors focus:border-[var(--color-primary)]"
                    min={0}
                    step={1}
                    type="number"
                    value={monthlyLimit}
                    onChange={(e) => setMonthlyLimit(e.target.value)}
                    disabled={!current || updateMutation.isPending}
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-[var(--color-text-hint)]">次</span>
                </div>
              </div>
            </div>

            {/* Usage progress */}
            <div className="rounded-xl border border-[var(--color-border)]/60 bg-white/70 p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-[var(--color-primary)]" />
                  <span className="text-sm font-semibold text-[var(--ink)]">本月使用进度</span>
                </div>
                <span className="text-sm tabular-nums text-[var(--color-text-secondary)]">
                  <span className="font-semibold text-[var(--ink)]">
                    {current?.current_usage.call_count.toLocaleString("zh-CN") ?? 0}
                  </span>
                  {" / "}
                  {current?.monthly_call_limit
                    ? current.monthly_call_limit.toLocaleString("zh-CN")
                    : "不限"}
                  <span className="ml-2">{usageRate}%</span>
                </span>
              </div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-[var(--color-primary-light)]">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-[var(--color-primary)] to-[var(--color-primary-dark)] transition-all duration-700"
                  style={{ width: `${usageRate}%` }}
                />
              </div>
            </div>

            <Button disabled={!canSave} onClick={() => setConfirmOpen(true)}>
              <Save className="h-4 w-4" />
              保存设置
            </Button>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title="确认修改 AI 解析设置"
        description="该操作会立即影响后台 AI 解析任务创建，并记录审计日志。确认保存当前设置？"
        confirmText="确认保存"
        danger={!enabled}
        loading={updateMutation.isPending}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={save}
      />
    </div>
  );
}

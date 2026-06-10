"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Save, SlidersHorizontal, Power, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { apiRequest, toQuery } from "@/lib/api/client";
import { getErrorMessage } from "@/lib/api/errors";
import type { AISettings, AISettingsPatchRequest, AIStatsResponse, AdminAiConfigsResponse } from "@/lib/api/types";
import { StatCards } from "./components/stat-cards";
import { TrendChart } from "./components/trend-chart";
import { ModelCards } from "./components/model-cards";
import { OcrAccordion } from "./components/ocr-accordion";
import { AiCompletionPreview } from "./components/ai-completion";

export default function AISettingsPage() {
  const queryClient = useQueryClient();
  const [monthlyLimit, setMonthlyLimit] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

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

  const current = settings.data;
  const usageRate = useMemo(() => {
    if (!current || current.monthly_call_limit <= 0) return 0;
    return Math.min(
      Math.round((current.current_usage.call_count / current.monthly_call_limit) * 100),
      100,
    );
  }, [current]);

  const updateMutation = useMutation({
    mutationFn: (payload: AISettingsPatchRequest) =>
      apiRequest<AISettings>("/ai-settings", {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
    onSuccess: (data) => {
      setMessage("AI 解析设置已更新");
      setConfirmOpen(false);
      setEnabled(data.ai_parse_enabled);
      setMonthlyLimit(String(data.monthly_call_limit));
      queryClient.setQueryData(["ai-settings"], data);
    },
    onError: (error) => setMessage(getErrorMessage(error)),
  });

  const parsedLimit = Number(monthlyLimit);
  const hasChanges = current
    ? enabled !== current.ai_parse_enabled || parsedLimit !== current.monthly_call_limit
    : false;
  const canSave =
    hasChanges &&
    Number.isInteger(parsedLimit) &&
    parsedLimit >= 0 &&
    !updateMutation.isPending;

  const save = () => {
    if (!current || !canSave) return;
    updateMutation.mutate({
      ai_parse_enabled: enabled,
      monthly_call_limit: parsedLimit,
    });
  };

  return (
    <div className="space-y-6 animate-rise-in">
      {/* ===== Header ===== */}
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div>
          <p className="font-mono text-xs uppercase tracking-[0.3em] text-[var(--color-text-hint)]">
            AI Operations Center
          </p>
          <h2 className="mt-2 font-display text-4xl font-bold text-[var(--ink)]">AI 解析设置</h2>
          <p className="mt-3 text-sm text-[var(--color-text-secondary)]">
            管理 OCR 纠错、题目补全、AI 解析生成等能力
          </p>
        </div>
        <StatusBadge tone={current?.ai_parse_enabled ? "success" : "danger"}>
          {current?.ai_parse_enabled ? "解析开启" : "全局关闭"}
        </StatusBadge>
      </div>

      {/* ===== Part 1: Data Overview ===== */}
      {stats.isError ? (
        <p className="rounded-xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-4 py-3 text-sm text-[var(--color-danger)]">
          {getErrorMessage(stats.error)}
        </p>
      ) : (
        <StatCards stats={stats.data} loading={stats.isLoading} />
      )}

      {/* ===== Part 2: AI Call Trend ===== */}
      <TrendChart trends={stats.data?.daily_trends} loading={stats.isLoading} />

      {/* ===== Part 3: Model Configuration ===== */}
      <ModelCards />

      {configs.isError ? (
        <p className="rounded-xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-4 py-3 text-sm text-[var(--color-danger)]">
          {getErrorMessage(configs.error)}
        </p>
      ) : (
        <>
          {/* ===== Part 4: OCR Correction Config ===== */}
          <OcrAccordion configs={configs.data} loading={configs.isLoading} />
          {/* ===== Part 5: AI Completion Config ===== */}
          <AiCompletionPreview configs={configs.data} loading={configs.isLoading} />
        </>
      )}

      {/* ===== System Configuration ===== */}
      <div className="rounded-2xl border border-[var(--color-border)]/80 bg-white/80 p-5 shadow-sm">
        <div className="mb-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="grid h-10 w-10 place-items-center rounded-xl border border-[var(--color-border)]/60 bg-white/60 shadow-sm">
                <SlidersHorizontal className="h-5 w-5 text-[var(--color-primary)]" />
              </div>
              <div>
                <h3 className="font-display text-xl font-bold text-[var(--ink)]">系统配置</h3>
                <p className="mt-0.5 text-sm text-[var(--color-text-secondary)]">
                  全局 AI 解析开关与月度调用额度管理
                </p>
              </div>
            </div>
            <Button disabled={!canSave} onClick={() => setConfirmOpen(true)}>
              <Save className="h-4 w-4" />
              保存设置
            </Button>
          </div>
        </div>

        {/* Messages */}
        {message ? (
          <p className="mb-4 rounded-xl border border-[var(--color-border)] bg-white/70 px-4 py-3 text-sm text-[var(--color-text-secondary)]">
            {message}
          </p>
        ) : null}
        {settings.isError ? (
          <p className="mb-4 rounded-xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-4 py-3 text-sm text-[var(--color-danger)]">
            {getErrorMessage(settings.error)}
          </p>
        ) : null}

        {/* Rules info */}
        <div className="mb-5 flex items-start gap-3 rounded-xl border border-[var(--color-warning)]/30 bg-[var(--color-warning-light)] px-4 py-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-warning)]" />
          <p className="text-xs leading-6 text-[var(--color-text-secondary)]">
            全局关闭后所有管理员都不能新建 AI 解析任务，super_admin 也受影响；月度额度为全局 API
            调用量，super_admin 不受额度限制。
          </p>
        </div>

        <div className="grid gap-5 md:grid-cols-2">
          {/* Toggle */}
          <label className="flex items-center justify-between gap-4 rounded-xl border border-[var(--color-border)]/60 bg-[var(--color-bg-input)] p-4">
            <div className="flex items-start gap-3">
              <Power
                className="mt-0.5 h-5 w-5"
                style={{ color: enabled ? "var(--color-success)" : "var(--color-text-hint)" }}
              />
              <div>
                <span className="text-sm font-semibold text-[var(--ink)]">全局 AI 解析</span>
                <p className="mt-0.5 text-xs text-[var(--color-text-hint)]">
                  关闭后拒绝创建新的 AI 解析任务
                </p>
              </div>
            </div>
            <button
              onClick={() => setEnabled(!enabled)}
              disabled={!current || updateMutation.isPending}
              className="relative h-6 w-11 rounded-full border border-[var(--color-border)] transition-colors"
              style={{
                backgroundColor: enabled
                  ? "var(--color-success)"
                  : "var(--color-bg-input)",
              }}
            >
              <span
                className="absolute left-0.5 top-0.5 h-[calc(100%-4px)] w-[calc(50%-2px)] rounded-full bg-white shadow-sm transition-transform"
                style={{ transform: enabled ? "translateX(100%)" : "translateX(0)" }}
              />
            </button>
          </label>

          {/* Monthly limit */}
          <label className="block rounded-xl border border-[var(--color-border)]/60 bg-[var(--color-bg-input)] p-4">
            <span className="text-sm font-semibold text-[var(--ink)]">月度 API 调用额度</span>
            <p className="mt-0.5 text-xs text-[var(--color-text-hint)]">
              填写 0 表示不限额度；额度只限制非 super_admin 的新解析任务
            </p>
            <div className="relative mt-2">
              <input
                className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-white pl-3 pr-12 text-sm outline-none transition-colors focus:border-[var(--color-primary)]"
                min={0}
                step={1}
                type="number"
                value={monthlyLimit}
                onChange={(event) => setMonthlyLimit(event.target.value)}
                disabled={!current || updateMutation.isPending}
              />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-[var(--color-text-hint)]">
                次
              </span>
            </div>
          </label>
        </div>

        {/* Usage progress */}
        <div className="mt-5 rounded-xl border border-[var(--color-border)]/60 bg-white/70 p-4">
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
          <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-[var(--color-primary-light)]">
            <div
              className="h-full rounded-full bg-gradient-to-r from-[var(--color-primary)] to-[var(--color-primary-dark)] transition-all duration-700"
              style={{ width: `${usageRate}%` }}
            />
          </div>
        </div>
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

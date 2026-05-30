"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Power, Save, SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { apiRequest } from "@/lib/api/client";
import { getErrorMessage } from "@/lib/api/errors";
import type { AISettings, AISettingsPatchRequest } from "@/lib/api/types";

function numberValue(value?: number | null) {
  if (value === undefined || value === null) return "不限";
  return value.toLocaleString("zh-CN");
}

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

  const current = settings.data;
  const usageRate = useMemo(() => {
    if (!current || current.monthly_call_limit <= 0) return 0;
    return Math.min(Math.round((current.current_usage.call_count / current.monthly_call_limit) * 100), 100);
  }, [current]);

  const updateMutation = useMutation({
    mutationFn: (payload: AISettingsPatchRequest) => apiRequest<AISettings>("/ai-settings", { method: "PATCH", body: JSON.stringify(payload) }),
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
  const hasChanges = current ? enabled !== current.ai_parse_enabled || parsedLimit !== current.monthly_call_limit : false;
  const canSave = hasChanges && Number.isInteger(parsedLimit) && parsedLimit >= 0 && !updateMutation.isPending;

  const save = () => {
    if (!current || !canSave) return;
    updateMutation.mutate({ ai_parse_enabled: enabled, monthly_call_limit: parsedLimit });
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div>
          <p className="font-mono text-xs uppercase tracking-[0.3em] text-[var(--color-text-hint)]">AI Settings</p>
          <h2 className="mt-2 font-display text-4xl font-bold text-[var(--ink)]">AI 解析设置</h2>
          <p className="mt-3 text-sm text-[var(--color-text-secondary)]">管理全局 AI 解析业务开关与月度 API 调用额度。</p>
        </div>
        <StatusBadge tone={current?.ai_parse_enabled ? "success" : "danger"}>{current?.ai_parse_enabled ? "解析开启" : "全局关闭"}</StatusBadge>
      </div>

      <Card className="blueprint-panel p-6">
        <div className="relative z-10 flex items-start gap-4">
          <AlertTriangle className="mt-1 h-6 w-6 text-[var(--color-warning)]" />
          <div>
            <h3 className="font-display text-2xl font-bold text-[var(--ink)]">生效规则</h3>
            <p className="mt-2 max-w-4xl text-sm leading-7 text-[var(--color-text-secondary)]">
              全局关闭后所有管理员都不能新建 AI 解析任务，super_admin 也受影响；月度额度为全局 API 调用量，super_admin 不受额度限制。
            </p>
          </div>
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card className="p-5">
          <p className="text-sm font-semibold text-[var(--color-text-secondary)]">当前月份</p>
          <p className="mt-4 font-display text-4xl font-bold text-[var(--ink)]">{current?.current_usage.year_month ?? "--"}</p>
        </Card>
        <Card className="p-5">
          <p className="text-sm font-semibold text-[var(--color-text-secondary)]">已调用</p>
          <p className="mt-4 font-display text-4xl font-bold text-[var(--ink)]">{numberValue(current?.current_usage.call_count)}</p>
        </Card>
        <Card className="p-5">
          <p className="text-sm font-semibold text-[var(--color-text-secondary)]">月度额度</p>
          <p className="mt-4 font-display text-4xl font-bold text-[var(--ink)]">{current?.monthly_call_limit === 0 ? "不限" : numberValue(current?.monthly_call_limit)}</p>
        </Card>
        <Card className="p-5">
          <p className="text-sm font-semibold text-[var(--color-text-secondary)]">剩余额度</p>
          <p className="mt-4 font-display text-4xl font-bold text-[var(--ink)]">{numberValue(current?.remaining_calls)}</p>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-3">
            <SlidersHorizontal className="h-5 w-5 text-[var(--color-primary)]" />
            <div>
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">全局配置</h3>
              <p className="text-sm text-[var(--color-text-secondary)]">修改会写入审计日志。</p>
            </div>
          </div>
          <Button disabled={!canSave} onClick={() => setConfirmOpen(true)}>
            <Save className="h-4 w-4" />
            保存设置
          </Button>
        </CardHeader>
        <CardContent className="space-y-5">
          {message ? <p className="rounded-2xl border border-[var(--color-border)] bg-white/70 px-4 py-3 text-sm text-[var(--color-text-secondary)]">{message}</p> : null}
          {settings.isError ? <p className="rounded-2xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-4 py-3 text-sm text-[var(--color-danger)]">{getErrorMessage(settings.error)}</p> : null}

          <label className="flex items-center justify-between gap-4 rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
            <span>
              <span className="flex items-center gap-2 font-semibold text-[var(--ink)]"><Power className="h-4 w-4" />全局 AI 解析</span>
              <span className="mt-1 block text-sm text-[var(--color-text-secondary)]">关闭后拒绝创建新的 AI 解析任务。</span>
            </span>
            <input className="h-5 w-5" type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} disabled={!current || updateMutation.isPending} />
          </label>

          <label className="block rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
            <span className="font-semibold text-[var(--ink)]">月度全局 API 调用额度</span>
            <span className="mt-1 block text-sm text-[var(--color-text-secondary)]">填写 0 表示不限额度；额度只限制非 super_admin 的新解析任务。</span>
            <input
              className="mt-3 h-11 w-full rounded-xl border border-[var(--color-border)] bg-white px-3 text-sm outline-none focus:border-[var(--color-primary)]"
              min={0}
              step={1}
              type="number"
              value={monthlyLimit}
              onChange={(event) => setMonthlyLimit(event.target.value)}
              disabled={!current || updateMutation.isPending}
            />
          </label>

          <div className="rounded-2xl border border-[var(--color-border)] bg-white/70 p-4">
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="font-semibold text-[var(--ink)]">本月使用进度</span>
              <span className="text-[var(--color-text-secondary)]">{usageRate}%</span>
            </div>
            <div className="mt-3 h-3 overflow-hidden rounded-full bg-[var(--color-primary-light)]">
              <div className="h-full rounded-full bg-[var(--color-primary)] transition-all" style={{ width: `${usageRate}%` }} />
            </div>
          </div>
        </CardContent>
      </Card>

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

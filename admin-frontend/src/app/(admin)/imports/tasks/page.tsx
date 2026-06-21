"use client";

import { useId, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, FileBox, FileText, FileUp, History, RefreshCw } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/status-badge";
import { apiRequest } from "@/lib/api/client";
import type { ImportPipelineStatusResponse, ImportPipelineUploadResponse } from "@/lib/api/types";

function renderJson(value: unknown) {
  if (value === undefined || value === null || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function statusTone(status: string) {
  if (["completed", "success", "finished"].includes(status)) return "success";
  if (["failed", "error"].includes(status)) return "danger";
  if (["running", "processing", "queued", "pending"].includes(status)) return "warning";
  return "neutral";
}

function isTerminalStatus(status?: string) {
  return Boolean(status && ["completed", "success", "finished", "failed", "error"].includes(status));
}

export default function ImportTasksPage() {
  const [file, setFile] = useState<File | null>(null);
  const [subject, setSubject] = useState("");
  const [importMode, setImportMode] = useState("auto");
  const [enableAiRepair, setEnableAiRepair] = useState(true);
  const [confidenceThreshold, setConfidenceThreshold] = useState("0.6");
  const [pageStart, setPageStart] = useState("");
  const [pageEnd, setPageEnd] = useState("");
  const [pipelineId, setPipelineId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const fileInputId = useId();
  const queryClient = useQueryClient();
  const wasNotTerminal = useRef(true);

  const statusQuery = useQuery({
    queryKey: ["import-pipeline", pipelineId],
    queryFn: () => apiRequest<ImportPipelineStatusResponse>(`/imports/pipelines/${pipelineId}`),
    enabled: pipelineId !== null,
    refetchInterval: (query) => (isTerminalStatus(query.state.data?.status) ? false : 2500),
    retry: false,
  });

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("请选择要导入的文件");
      const formData = new FormData();
      formData.set("file", file);
      if (subject) formData.set("subject", subject);
      formData.set("import_mode", importMode);
      formData.set("enable_ai_repair", String(enableAiRepair));
      formData.set("confidence_threshold", confidenceThreshold || "0.6");
      if (pageStart) formData.set("page_start", pageStart);
      if (pageEnd) formData.set("page_end", pageEnd);
      return apiRequest<ImportPipelineUploadResponse>("/imports/upload", { method: "POST", body: formData });
    },
    onSuccess: (result) => {
      setPipelineId(result.pipeline_id);
      setMessage(`导入任务已提交：${result.pipeline_id}`);
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "上传失败，请稍后重试。");
    },
  });

  const isPipelineRunning = pipelineId !== null && !(statusQuery.data && isTerminalStatus(statusQuery.data.status));
  const status = statusQuery.data;
  const progressItems = [
    ["当前状态", status?.status],
    ["当前阶段", status?.current_stage],
    ["OCR 进度", status?.ocr_progress],
    ["来源类型", status?.source_type],
    ["批次 ID", status?.batch_id],
    ["题目数量", status?.question_count],
  ];

  useEffect(() => {
    if (status && wasNotTerminal.current && isTerminalStatus(status.status)) {
      wasNotTerminal.current = false;
      queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
    }
  }, [status, queryClient]);

  return (
    <div className="space-y-6">
      {/* Empty-state message banner — only when there's a non-terminal message */}
      {message && !isPipelineRunning ? (
        <div className="flex items-center gap-2.5 rounded-2xl border border-[var(--color-border)] bg-white/80 px-4 py-3 text-sm text-[var(--color-text-secondary)] shadow-[var(--shadow-crisp)]">
          {uploadMutation.isSuccess ? <CheckCircle2 className="h-4 w-4 shrink-0 text-green-500" /> : <AlertCircle className="h-4 w-4 shrink-0 text-amber-500" />}
          {message}
        </div>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[1.25fr_0.75fr]">
        {/* ===== Left Column: Upload Form ===== */}
        <Card>
          <CardHeader>
            <div className="flex flex-col gap-1">
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">导入任务</h3>
              <p className="text-sm text-[var(--color-text-secondary)]">上传 PDF、图片、TXT 或 Excel，导入结果会进入待审核区。</p>
            </div>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* File & Subject */}
            <div>
              <div className="mb-3 flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded bg-[var(--color-primary-light)] text-[9px] font-bold text-[var(--color-primary-dark)]">1</span>
                <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--color-text-hint)]">文件与科目</span>
              </div>
              <label htmlFor={fileInputId}>
                <div className={`relative flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-5 transition ${
                  isPipelineRunning
                    ? "border-[var(--color-border)] bg-[var(--color-bg-input)] opacity-50"
                    : file
                      ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]"
                      : "border-[var(--color-border)] bg-white/50 hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)]"
                }`}>
                  <FileBox className={`mb-2 h-7 w-7 ${file ? "text-[var(--color-primary-dark)]" : "text-[var(--color-text-hint)]"}`} />
                  {file ? (
                    <div className="text-center">
                      <p className="text-sm font-semibold text-[var(--ink)]">{file.name}</p>
                      <p className="mt-0.5 text-xs text-[var(--color-text-hint)]">{(file.size / 1024 / 1024).toFixed(1)} MB · 已就绪</p>
                    </div>
                  ) : (
                    <div className="text-center">
                      <p className="text-sm font-semibold text-[var(--ink)]">点击选择文件</p>
                      <p className="mt-0.5 text-xs text-[var(--color-text-hint)]">PDF、JPG、PNG、WebP、TXT、Excel</p>
                    </div>
                  )}
                  <input id={fileInputId} type="file" accept=".pdf,.txt,.xlsx,.xls,.jpg,.jpeg,.png,.webp" disabled={isPipelineRunning} className="absolute inset-0 cursor-pointer opacity-0" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
                </div>
              </label>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <label className="space-y-1">
                  <span className="text-xs font-semibold text-[var(--color-text-secondary)]">科目</span>
                  <Input placeholder="如 math2 / exam408" value={subject} onChange={(event) => setSubject(event.target.value)} />
                </label>
                <label className="space-y-1">
                  <span className="text-xs font-semibold text-[var(--color-text-secondary)]">导入模式</span>
                  <select className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none transition focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.14)]" value={importMode} onChange={(event) => setImportMode(event.target.value)}>
                    <option value="auto">auto（自动检测）</option>
                    <option value="book">book（教辅）</option>
                    <option value="exam">exam（试卷）</option>
                  </select>
                </label>
              </div>
            </div>

            <hr className="border-[var(--color-border)]" />

            {/* Page Range */}
            <div>
              <div className="mb-3 flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded bg-[var(--color-primary-light)] text-[9px] font-bold text-[var(--color-primary-dark)]">2</span>
                <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--color-text-hint)]">页面范围</span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="space-y-1">
                  <span className="text-xs font-semibold text-[var(--color-text-secondary)]">起始页</span>
                  <Input type="number" min="1" placeholder="留空从第1页开始" value={pageStart} onChange={(event) => setPageStart(event.target.value)} />
                </label>
                <label className="space-y-1">
                  <span className="text-xs font-semibold text-[var(--color-text-secondary)]">结束页</span>
                  <Input type="number" min="1" placeholder="留空到最后一页" value={pageEnd} onChange={(event) => setPageEnd(event.target.value)} />
                </label>
              </div>
            </div>

            <hr className="border-[var(--color-border)]" />

            {/* AI Options */}
            <div>
              <div className="mb-3 flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded bg-[var(--color-primary-light)] text-[9px] font-bold text-[var(--color-primary-dark)]">3</span>
                <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--color-text-hint)]">AI 选项</span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="space-y-1">
                  <span className="text-xs font-semibold text-[var(--color-text-secondary)]">置信度阈值</span>
                  <Input type="number" step="0.1" min="0" max="1" value={confidenceThreshold} onChange={(event) => setConfidenceThreshold(event.target.value)} />
                </label>
                <label className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 text-sm text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] ${
                  enableAiRepair ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]" : "border-[var(--color-border)] bg-white/50"
                }`}>
                  <input type="checkbox" checked={enableAiRepair} onChange={(event) => setEnableAiRepair(event.target.checked)} disabled={isPipelineRunning} className="h-4 w-4 rounded border-[var(--color-border)] text-[var(--color-primary)] accent-[var(--color-primary)]" />
                  <div>
                    <span className="font-semibold text-[var(--ink)]">AI 修复</span>
                    <p className="text-[10px] text-[var(--color-text-hint)]">自动校正 OCR 偏差</p>
                  </div>
                </label>
              </div>
            </div>

            {/* Submit */}
            <div className="flex items-center justify-end gap-4 border-t border-[var(--color-border)] pt-5">
              <Button disabled={!file || uploadMutation.isPending || isPipelineRunning} onClick={() => uploadMutation.mutate()} className="h-11 px-5">
                <FileUp className="h-4 w-4" />
                {uploadMutation.isPending ? "上传中..." : isPipelineRunning ? "解析中..." : "开始导入"}
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* ===== Right Column: Contextual Panel ===== */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <h3 className="font-display text-xl font-bold text-[var(--ink)]">
                {pipelineId ? "导入进度" : "准备就绪"}
              </h3>
              <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">
                {pipelineId ? "实时追踪导入管线状态" : "配置左侧参数后提交文件"}
              </p>
            </div>
            {pipelineId ? (
              <Button variant="secondary" disabled={!pipelineId || statusQuery.isFetching} onClick={() => statusQuery.refetch()} className="shrink-0">
                <RefreshCw className={`h-3.5 w-3.5 ${statusQuery.isFetching ? "animate-spin" : ""}`} />
              </Button>
            ) : null}
          </CardHeader>
          <CardContent>
            {/* ——— No pipeline yet ——— */}
            {!pipelineId ? (
              <div className="flex flex-col items-center py-8 text-center">
                <FileUp className="mb-3 h-9 w-9 text-[var(--color-text-hint)]" />
                <p className="text-sm font-semibold text-[var(--color-text-secondary)]">等待文件提交</p>
                <p className="mt-1 max-w-xs text-xs leading-relaxed text-[var(--color-text-hint)]">
                  在左侧选择导入文件并配置参数，点击「开始导入」后将在此处实时追踪进度。
                </p>
              </div>
            ) : null}

            {/* ——— Pipeline submitted, fetching ——— */}
            {pipelineId && !status && !statusQuery.isError ? (
              <div className="flex items-center gap-3 rounded-2xl border border-[var(--color-border)] bg-white/70 px-4 py-6 text-sm text-[var(--color-text-secondary)]">
                <RefreshCw className="h-4 w-4 animate-spin" />
                正在获取导入进度...
              </div>
            ) : null}

            {/* ——— Active pipeline ——— */}
            {status ? (
              <div className="space-y-4">
                {/* Status badge row */}
                <div className="flex flex-wrap items-center gap-2">
                  {isPipelineRunning ? (
                    <span className="flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">
                      <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-amber-500" />
                      处理中
                    </span>
                  ) : (
                    <span className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${
                      ["failed", "error"].includes(status.status) ? "bg-red-50 text-red-700" : "bg-green-50 text-green-700"
                    }`}>
                      <span className={`inline-block h-2 w-2 rounded-full ${
                        ["failed", "error"].includes(status.status) ? "bg-red-500" : "bg-green-500"
                      }`} />
                      {status.status === "completed" || status.status === "success" || status.status === "finished" ? "已完成" : "失败"}
                    </span>
                  )}
                  {status.current_stage ? <span className="rounded-full bg-[var(--color-bg-input)] px-2.5 py-0.5 text-[10px] font-medium text-[var(--color-text-secondary)]">{status.current_stage}</span> : null}
                </div>

                {/* Progress bar */}
                {isPipelineRunning ? (
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between text-[10px] text-[var(--color-text-hint)]">
                      <span>解析进度</span>
                      <span>{status.ocr_progress || "0%"}</span>
                    </div>
                    <div className="overflow-hidden rounded-full bg-[var(--color-bg-input)]">
                      <div className="h-2.5 rounded-full bg-gradient-to-r from-[var(--color-primary)] to-[#7b9bbb] transition-all duration-700" style={{ width: status.ocr_progress || "0%" }} />
                    </div>
                  </div>
                ) : null}

                {/* Pipeline summary cards */}
                <div className="grid grid-cols-2 gap-2">
                  {progressItems.slice(0, 4).map(([label, value]) => (
                    <div key={String(label)} className="rounded-xl border border-[var(--color-border)] bg-white/70 p-3">
                      <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-[var(--color-text-hint)]">{label}</p>
                      <div className="mt-1.5 text-xs font-semibold text-[var(--ink)]">
                        {label === "当前状态" ? <StatusBadge tone={statusTone(String(value || ""))}>{String(value || "—")}</StatusBadge> : String(value || "—")}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Stats & Errors */}
                <div className="space-y-2">
                  <details className="group rounded-xl border border-[var(--color-border)] bg-white/70">
                    <summary className="flex cursor-pointer items-center justify-between px-3 py-2.5 text-xs font-semibold text-[var(--ink)]">
                      <span className="flex items-center gap-2">
                        <span>统计</span>
                        {status.stats && Object.keys(status.stats).length > 0 ? <span className="rounded-full bg-[var(--color-primary-light)] px-1.5 py-0.5 text-[9px] font-medium text-[var(--color-primary-dark)]">{Object.keys(status.stats).length}</span> : null}
                      </span>
                      <span className="text-[9px] text-[var(--color-text-hint)] transition group-open:rotate-180">▼</span>
                    </summary>
                    <pre className="max-h-48 overflow-auto border-t border-[var(--color-border)] px-3 py-2.5 whitespace-pre-wrap text-[10px] text-[var(--color-text-secondary)]">{renderJson(status.stats)}</pre>
                  </details>
                  <details className="group rounded-xl border border-[var(--color-border)] bg-white/70">
                    <summary className="flex cursor-pointer items-center justify-between px-3 py-2.5 text-xs font-semibold text-[var(--ink)]">
                      <span className="flex items-center gap-2">
                        <span>错误日志</span>
                        {Array.isArray(status.errors) && status.errors.length > 0 ? <span className="rounded-full bg-red-100 px-1.5 py-0.5 text-[9px] font-medium text-red-600">{status.errors.length}</span> : null}
                      </span>
                      <span className="text-[9px] text-[var(--color-text-hint)] transition group-open:rotate-180">▼</span>
                    </summary>
                    {Array.isArray(status.errors) && status.errors.length > 0 ? (
                      <pre className="max-h-48 overflow-auto border-t border-[var(--color-border)] px-3 py-2.5 whitespace-pre-wrap text-[10px] text-red-600">{status.errors.map((e) => `• ${e}`).join("\n")}</pre>
                    ) : (
                      <p className="border-t border-[var(--color-border)] px-3 py-2.5 text-[10px] text-[var(--color-text-hint)]">暂无错误</p>
                    )}
                  </details>
                </div>

                {/* Quick actions */}
                {status.batch_id ? (
                  <div className="flex flex-wrap gap-2 border-t border-[var(--color-border)] pt-3">
                    <a className="inline-flex h-8 items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-white/70 px-3 text-[10px] font-semibold text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)]" href={`/imports/history?batch_id=${encodeURIComponent(status.batch_id)}`}>
                      <History className="h-3 w-3" />
                      导入记录
                    </a>
                    <a className="inline-flex h-8 items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-white/70 px-3 text-[10px] font-semibold text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)]" href={`/imports/review?batch_id=${encodeURIComponent(status.batch_id)}`}>
                      <FileText className="h-3 w-3" />
                      待审核
                    </a>
                  </div>
                ) : null}

              {/* ——— Quality Report Dashboard ——— */}
              {status.quality_report && isTerminalStatus(status.status) ? (
                <div className="mt-4 space-y-3 rounded-xl border border-[var(--color-border)] bg-white/80 p-4">
                  <h4 className="font-display text-sm font-bold text-[var(--ink)]">导入质量概览</h4>
                  <div className="grid grid-cols-2 gap-2 text-[11px]">
                    <div className="rounded-lg bg-white/70 p-2.5">
                      <span className="text-[9px] uppercase tracking-wider text-[var(--color-text-hint)]">总题数</span>
                      <p className="mt-0.5 font-semibold text-[var(--ink)]">{status.quality_report.total_questions}</p>
                    </div>
                    {status.quality_report.low_risk !== undefined ? (
                      <div className="rounded-lg bg-green-50/70 p-2.5">
                        <span className="text-[9px] uppercase tracking-wider text-green-600">低风险</span>
                        <p className="mt-0.5 font-semibold text-green-700">{status.quality_report.low_risk}</p>
                      </div>
                    ) : null}
                    {status.quality_report.medium_risk !== undefined ? (
                      <div className="rounded-lg bg-amber-50/70 p-2.5">
                        <span className="text-[9px] uppercase tracking-wider text-amber-600">需检查</span>
                        <p className="mt-0.5 font-semibold text-amber-700">{status.quality_report.medium_risk}</p>
                      </div>
                    ) : null}
                    {status.quality_report.high_risk !== undefined ? (
                      <div className="rounded-lg bg-red-50/70 p-2.5">
                        <span className="text-[9px] uppercase tracking-wider text-red-600">高风险</span>
                        <p className="mt-0.5 font-semibold text-red-700">{status.quality_report.high_risk}</p>
                      </div>
                    ) : null}
                    {status.quality_report.ai_answer_count !== undefined ? (
                      <div className="rounded-lg bg-purple-50/70 p-2.5">
                        <span className="text-[9px] uppercase tracking-wider text-purple-600">AI 答案</span>
                        <p className="mt-0.5 font-semibold text-purple-700">{status.quality_report.ai_answer_count}</p>
                      </div>
                    ) : null}
                    {status.quality_report.math_image_count !== undefined ? (
                      <div className="rounded-lg bg-blue-50/70 p-2.5">
                        <span className="text-[9px] uppercase tracking-wider text-blue-600">公式截图</span>
                        <p className="mt-0.5 font-semibold text-blue-700">{status.quality_report.math_image_count}</p>
                      </div>
                    ) : null}
                    {status.quality_report.table_markdown_count !== undefined ? (
                      <div className="rounded-lg bg-cyan-50/70 p-2.5">
                        <span className="text-[9px] uppercase tracking-wider text-cyan-600">表格</span>
                        <p className="mt-0.5 font-semibold text-cyan-700">{status.quality_report.table_markdown_count}</p>
                      </div>
                    ) : null}
                  </div>
                  {status.quality_report.estimated_manual_check_rate !== undefined ? (
                    <div className="flex items-center gap-2 rounded-lg bg-[var(--color-bg-input)] px-2.5 py-2 text-[10px] text-[var(--color-text-secondary)]">
                      <span>人工检查率：{(status.quality_report.estimated_manual_check_rate * 100).toFixed(0)}%</span>
                      {status.quality_report.estimated_manual_check_rate > 0.4 ? (
                        <span className="ml-auto rounded-full bg-amber-100 px-1.5 py-0.5 text-[9px] text-amber-700">偏高</span>
                      ) : null}
                    </div>
                  ) : null}
                  {status.quality_report.performance_summary ? (
                    <details className="group rounded-lg border border-[var(--color-border)] bg-white/50">
                      <summary className="flex cursor-pointer items-center justify-between px-2.5 py-2 text-[10px] font-semibold text-[var(--color-text-secondary)]">
                        <span>性能概览</span>
                        <span className="text-[8px] text-[var(--color-text-hint)] transition group-open:rotate-180">▼</span>
                      </summary>
                      <div className="border-t border-[var(--color-border)] px-2.5 py-2 text-[10px] text-[var(--color-text-secondary)] space-y-1">
                        <div className="flex justify-between"><span>总耗时</span><span>{(status.quality_report.performance_summary.total_duration_ms / 1000).toFixed(1)}s</span></div>
                        <div className="flex justify-between"><span>AI 调用</span><span>{status.quality_report.performance_summary.total_ai_calls} 次</span></div>
                        <div className="flex justify-between"><span>Token 用量</span><span>{status.quality_report.performance_summary.total_tokens_used}</span></div>
                        <div className="flex justify-between"><span>OCR 缓存命中率</span><span>{(status.quality_report.performance_summary.cache_hit_rate * 100).toFixed(0)}%</span></div>
                        <div className="flex justify-between"><span>最慢阶段</span><span>{status.quality_report.performance_summary.slowest_stage} ({(status.quality_report.performance_summary.slowest_duration_ms / 1000).toFixed(1)}s)</span></div>
                      </div>
                    </details>
                  ) : null}
                  <div className="flex flex-wrap gap-2 pt-1">
                    {status.batch_id ? (
                      <a className="inline-flex h-7 items-center gap-1 rounded-lg border border-[var(--color-border)] bg-white/70 px-2.5 text-[10px] font-medium text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary)] hover:text-[var(--color-primary-dark)]" href={`/imports/review?batch_id=${encodeURIComponent(status.batch_id)}&risk_filter=high`}>
                        <AlertCircle className="h-3 w-3" />
                        查看高风险题
                      </a>
                    ) : null}
                  </div>
                </div>
              ) : null}
              </div>
            ) : null}

            {/* ——— Fetch error ——— */}
            {statusQuery.isError ? (
              <div className="flex items-center gap-2.5 rounded-2xl border border-[var(--color-danger)] bg-red-50/70 px-4 py-3 text-xs text-[var(--color-danger)]">
                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                无法获取导入进度，请刷新重试。
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

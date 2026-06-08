"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { FileUp, RefreshCw } from "lucide-react";
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

  const status = statusQuery.data;
  const progressItems = [
    ["当前状态", status?.status],
    ["当前阶段", status?.current_stage],
    ["OCR 进度", status?.ocr_progress],
    ["来源类型", status?.source_type],
    ["批次 ID", status?.batch_id],
    ["题目数量", status?.question_count],
  ];

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="font-display text-2xl font-bold text-[var(--ink)]">导入任务</h3>
            <p className="mt-1 text-sm text-[var(--color-text-secondary)]">上传 PDF、图片、TXT 或 Excel，导入结果会进入待审核区。</p>
          </div>
          <Button disabled={!file || uploadMutation.isPending} onClick={() => uploadMutation.mutate()}>
            <FileUp className="h-4 w-4" />
            {uploadMutation.isPending ? "上传中..." : "开始导入"}
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {message ? <p className="rounded-2xl border border-[var(--color-border)] bg-white/70 px-4 py-3 text-sm text-[var(--color-text-secondary)]">{message}</p> : null}
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <label className="space-y-1 xl:col-span-2">
              <span className="text-xs font-semibold text-[var(--color-text-secondary)]">导入文件</span>
              <Input type="file" accept=".pdf,.txt,.xlsx,.xls,.jpg,.jpeg,.png,.webp" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
            </label>
            <label className="space-y-1">
              <span className="text-xs font-semibold text-[var(--color-text-secondary)]">科目</span>
              <Input placeholder="如 math / 408 / english" value={subject} onChange={(event) => setSubject(event.target.value)} />
            </label>
            <label className="space-y-1">
              <span className="text-xs font-semibold text-[var(--color-text-secondary)]">导入模式</span>
              <select className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm" value={importMode} onChange={(event) => setImportMode(event.target.value)}>
                <option value="auto">auto</option>
                <option value="book">book</option>
                <option value="exam">exam</option>
              </select>
            </label>
            <label className="space-y-1">
              <span className="text-xs font-semibold text-[var(--color-text-secondary)]">起始页</span>
              <Input type="number" min="1" value={pageStart} onChange={(event) => setPageStart(event.target.value)} />
            </label>
            <label className="space-y-1">
              <span className="text-xs font-semibold text-[var(--color-text-secondary)]">结束页</span>
              <Input type="number" min="1" value={pageEnd} onChange={(event) => setPageEnd(event.target.value)} />
            </label>
            <label className="space-y-1">
              <span className="text-xs font-semibold text-[var(--color-text-secondary)]">置信度阈值</span>
              <Input type="number" step="0.1" min="0" max="1" value={confidenceThreshold} onChange={(event) => setConfidenceThreshold(event.target.value)} />
            </label>
            <label className="flex items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-secondary)]">
              <input type="checkbox" checked={enableAiRepair} onChange={(event) => setEnableAiRepair(event.target.checked)} />
              启用 AI 修复
            </label>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="font-display text-2xl font-bold text-[var(--ink)]">导入进度</h3>
            <p className="mt-1 text-sm text-[var(--color-text-secondary)]">任务提交后自动轮询 pipeline 状态。</p>
          </div>
          <Button variant="secondary" disabled={!pipelineId || statusQuery.isFetching} onClick={() => statusQuery.refetch()}>
            <RefreshCw className="h-4 w-4" />
            刷新
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {!pipelineId ? <p className="text-sm text-[var(--color-text-hint)]">暂无导入任务。</p> : null}
          {status ? (
            <>
              <div className="grid gap-3 md:grid-cols-3">
                {progressItems.map(([label, value]) => (
                  <div key={String(label)} className="rounded-2xl border border-[var(--color-border)] bg-white/70 p-4">
                    <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-[var(--color-text-hint)]">{label}</p>
                    <div className="mt-2 text-sm font-semibold text-[var(--ink)]">
                      {label === "当前状态" ? <StatusBadge tone={statusTone(String(value || ""))}>{String(value || "—")}</StatusBadge> : String(value || "—")}
                    </div>
                  </div>
                ))}
              </div>
              <div className="grid gap-4 lg:grid-cols-2">
                <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                  <p className="font-semibold text-[var(--ink)]">统计</p>
                  <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap text-xs text-[var(--color-text-secondary)]">{renderJson(status.stats)}</pre>
                </section>
                <section className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-4">
                  <p className="font-semibold text-[var(--ink)]">错误日志</p>
                  <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap text-xs text-[var(--color-text-secondary)]">{renderJson(status.errors)}</pre>
                </section>
              </div>
              {status.batch_id ? (
                <div className="flex flex-wrap gap-2">
                  <a className="text-sm font-semibold text-[var(--color-primary-dark)] underline" href={`/imports/history?batch_id=${encodeURIComponent(status.batch_id)}`}>查看导入记录</a>
                  <a className="text-sm font-semibold text-[var(--color-primary-dark)] underline" href={`/imports/review?batch_id=${encodeURIComponent(status.batch_id)}`}>进入待审核题目</a>
                </div>
              ) : null}
            </>
          ) : null}
          {statusQuery.isError ? <p className="text-sm text-[var(--color-danger)]">无法获取导入进度。</p> : null}
        </CardContent>
      </Card>
    </div>
  );
}

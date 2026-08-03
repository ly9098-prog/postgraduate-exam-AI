"use client";

import { useId, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, FileBox, FileText, FileUp, RefreshCw } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/status-badge";
import { apiRequest, toQuery } from "@/lib/api/client";
import type { ImportPipelineStatusResponse, ImportPipelineUploadResponse } from "@/lib/api/types";
import { parseProgressPercent, validatePageStart, validatePageEnd } from "@/lib/import-utils";

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

/* ─── Stage-bar: maps pipeline status → 4 discrete stages ─── */

function getStageStatuses(status?: ImportPipelineStatusResponse, isRunning?: boolean) {
  const stage = (status?.current_stage || "").toLowerCase();
  const st = status?.status || "";
  const term = isTerminalStatus(st);
  const fail = ["failed", "error"].includes(st);
  /* Backend pipeline stages → visual stage mapping:
   *   extract / normalize_text / split           → OCR 识别
   *   match / normalize_schema                    → AI 解析
   *   review                                      → 质量检查
   * "normalize" (without "schema") = text normalization (OCR phase)
   * "normalize" + "schema"         = schema normalization (AI phase)
   */
  const ocrDone = term
    || stage.includes("normalize")  /* normalize_text / normalize_schema */
    || stage.includes("split")
    || stage.includes("match")
    || stage.includes("review");
  const aiDone = term
    || stage.includes("match")
    || (stage.includes("normalize") && stage.includes("schema"))
    || stage.includes("review");
  const qualDone = term && !fail;
  return [
    { name: "上传文件", s: "done" as const },
    { name: "OCR 识别", s: ocrDone ? "done" as const : isRunning ? "active" as const : "pending" as const },
    { name: "AI 解析", s: aiDone ? (fail && !ocrDone ? "failed" as const : "done" as const) : ocrDone && isRunning ? "active" as const : "pending" as const },
    { name: "质量检查", s: qualDone ? (fail ? "failed" as const : "done" as const) : aiDone && isRunning ? "active" as const : "pending" as const },
  ];
}

type TabKey = "upload" | "progress" | "quality";


type CustomSelectOption = {
  value: string;
  label: string;
};

type CustomSelectProps = {
  value: string;
  onChange: (value: string) => void;
  options: CustomSelectOption[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
};

function CustomSelect({ value, onChange, options, placeholder = "请选择", disabled = false, className = "" }: CustomSelectProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const selectedOption = options.find((option) => option.value === value);

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [open]);

  return (
    <div ref={rootRef} className="relative w-full">
      <button
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={`${className} inline-flex items-center outline-none transition focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.14)] disabled:cursor-not-allowed disabled:opacity-60`}
        onClick={() => {
          if (!disabled) setOpen((current) => !current);
        }}
      >
        <span className={`min-w-0 flex-1 truncate text-left ${selectedOption ? "text-[var(--ink)]" : "text-[var(--color-text-hint)]"}`}>
          {selectedOption?.label || placeholder}
        </span>
        <span className={`ml-2 text-[10px] text-[var(--color-text-hint)] transition ${open ? "rotate-180" : ""}`}>▼</span>
      </button>

      {open ? (
        <div
          role="listbox"
          className="absolute left-0 right-0 top-full z-50 mt-1 max-h-40 overflow-auto rounded-xl border border-[var(--color-border)] bg-white py-1 text-sm shadow-[var(--shadow-floating)]"
        >
          {options.map((option) => {
            const active = option.value === value;
            return (
              <button
                key={option.value || "__empty__"}
                type="button"
                role="option"
                aria-selected={active}
                className={`flex w-full items-center px-3 py-2 text-left text-sm transition ${
                  active
                    ? "bg-[var(--color-primary-light)] font-semibold text-[var(--color-primary-dark)]"
                    : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-input)] hover:text-[var(--ink)]"
                }`}
                onClick={() => {
                  onChange(option.value);
                  setOpen(false);
                }}
              >
                <span className="min-w-0 flex-1 truncate">{option.label}</span>
                {active ? <span className="ml-2 text-xs text-[var(--color-primary)]">✓</span> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

export default function ImportTasksPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [subjectId, setSubjectId] = useState("");
  const [subjectOptions, setSubjectOptions] = useState<Array<{id: number; code: string; name: string}>>([]);
  useEffect(() => {
    apiRequest<Array<{id: number; code: string; name: string; path: string; level: number}>>("/imports/subject-options")
      .then(setSubjectOptions)
      .catch(() => {});
  }, []);
  const [importMode, setImportMode] = useState("auto");
  const [enableAiRepair, setEnableAiRepair] = useState(true);
  const [confidenceThreshold, setConfidenceThreshold] = useState("0.6");
  const [pageStart, setPageStart] = useState("");
  const [pageEnd, setPageEnd] = useState("");

  const isPdfFile = file?.name.toLowerCase().endsWith(".pdf") ?? false;
  const pageStartNum = pageStart ? Number(pageStart) : null;
  const pageEndNum = pageEnd ? Number(pageEnd) : null;
  const pageStartError = pageStartNum !== null && (!Number.isInteger(pageStartNum) || pageStartNum < 1) ? "起始页必须是 ≥ 1 的正整数" : null;
  const pageEndError = pageEndNum !== null && (!Number.isInteger(pageEndNum) || pageEndNum < 1) ? "结束页必须是 ≥ 1 的正整数" : null;
  const pageRangeError = pageStartNum !== null && pageEndNum !== null && pageStartNum > pageEndNum ? "起始页不能大于结束页" : null;
  const confidenceNum = Number(confidenceThreshold);
  const confidenceError = confidenceThreshold && (isNaN(confidenceNum) || confidenceNum < 0 || confidenceNum > 1) ? "阈值必须在 0-1 之间" : null;
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
      const query = toQuery({
        subject_id: subjectId ? Number(subjectId) : undefined,
        import_mode: importMode,
        enable_ai_repair: enableAiRepair,
        confidence_threshold: confidenceThreshold || undefined,
        page_start: pageStart || undefined,
        page_end: pageEnd || undefined,
      });
      const formData = new FormData();
      formData.set("file", file);
      return apiRequest<ImportPipelineUploadResponse>(`/imports/upload${query}`, { method: "POST", body: formData });
    },
    onSuccess: (result) => {
      setPipelineId(result.pipeline_id);
      setMessage(`导入任务已提交：${result.pipeline_id}`);
      setActiveTab("progress");
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

  /* Auto-switch to quality tab when pipeline completes */
  useEffect(() => {
    if (status && wasNotTerminal.current && isTerminalStatus(status.status)) {
      wasNotTerminal.current = false;
      queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
      if (status.quality_report) {
        requestAnimationFrame(() => setActiveTab("quality"));
      }
    }
  }, [status, queryClient, setActiveTab]);

  const stages = getStageStatuses(status, isPipelineRunning);

  const tabs: { key: TabKey; label: string; desc: string; badge?: string }[] = [
    { key: "upload", label: "上传", desc: "选择文件与配置" },
    { key: "progress", label: "进度", desc: "实时管线状态", badge: isPipelineRunning ? "处理中" : undefined },
    { key: "quality", label: "质量", desc: "报告与审核", badge: status?.quality_report ? "就绪" : undefined },
  ];

  return (
    <div className="space-y-6">
      {/* ── Message Banner ── */}
      {message && !isPipelineRunning ? (
        <div className="flex items-center gap-2.5 rounded-2xl border border-[var(--color-border)] bg-white/80 px-4 py-3 text-sm text-[var(--color-text-secondary)] shadow-[var(--shadow-crisp)]">
          {uploadMutation.isSuccess ? <CheckCircle2 className="h-4 w-4 shrink-0 text-green-500" /> : <AlertCircle className="h-4 w-4 shrink-0 text-amber-500" />}
          {message}
        </div>
      ) : null}

      {/* ── Tab Bar ── */}
      <div className="flex items-end gap-0 border-b-2 border-[var(--color-border)]">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`relative -mb-0.5 flex items-center gap-2 px-6 pb-3 pt-2 text-sm transition-colors ${
              activeTab === tab.key
                ? "border-b-2 border-[var(--color-primary)] font-bold text-[var(--ink)]"
                : "border-b-2 border-transparent text-[var(--color-text-hint)] hover:text-[var(--color-text-secondary)]"
            }`}
          >
            <span>{tab.label}</span>
            <span className="hidden text-xs font-normal sm:inline">{tab.desc}</span>
            {tab.badge ? (
              <span className={`rounded-full px-2 py-0.5 text-[9px] font-semibold ${
                tab.badge === "处理中" ? "bg-amber-50 text-amber-700" : "bg-green-50 text-green-700"
              }`}>{tab.badge}</span>
            ) : null}
          </button>
        ))}
      </div>

      {/* ═══════════════════════════════════════════════════
          TAB: Upload
          ═══════════════════════════════════════════════════ */}
      {activeTab === "upload" ? (
        <div className="grid gap-6 lg:grid-cols-2">
          {/* Left: File Selection */}
          <Card>
            <CardHeader>
              <div className="flex flex-col gap-1">
                <h3 className="font-display text-2xl font-bold text-[var(--ink)]">文件选择</h3>
                <p className="text-sm text-[var(--color-text-secondary)]">支持 PDF、图片、TXT、Excel</p>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <label htmlFor={fileInputId}>
                <div className={`paper-texture relative flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-10 transition-all duration-200 ${
                  isPipelineRunning
                    ? "border-[var(--color-border)] bg-[var(--color-bg-input)] opacity-50"
                    : file
                      ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]"
                      : "border-[var(--color-border)] bg-white/60 hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)]"
                }`}>
                  <div className={`mb-4 flex h-16 w-16 items-center justify-center rounded-2xl transition-all duration-200 ${file ? "bg-white shadow-sm scale-105" : "bg-[var(--color-primary-light)]"}`}>
                    <FileBox className={`h-8 w-8 ${file ? "text-[var(--color-primary-dark)]" : "text-[var(--color-primary)]"}`} />
                  </div>
                  {file ? (
                    <div className="text-center">
                      <p className="text-sm font-semibold text-[var(--ink)]">{file.name}</p>
                      <p className="mt-1 text-xs text-[var(--color-text-hint)]">{(file.size / 1024 / 1024).toFixed(1)} MB · 已就绪</p>
                    </div>
                  ) : (
                    <div className="text-center">
                      <p className="text-sm font-semibold text-[var(--ink)]">点击选择文件</p>
                      <p className="mt-1 text-xs text-[var(--color-text-hint)]">PDF、JPG、PNG、WebP、TXT、Excel</p>
                    </div>
                  )}
                  <input id={fileInputId} type="file" accept=".pdf,.txt,.xlsx,.xls,.jpg,.jpeg,.png,.webp" disabled={isPipelineRunning} className="absolute inset-0 cursor-pointer opacity-0" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
                </div>
              </label>
              <div className="space-y-1">
                <span className="text-[11px] font-medium text-[var(--color-text-secondary)]">科目</span>
                <CustomSelect
                  value={subjectId}
                  onChange={setSubjectId}
                  placeholder="选择科目（可选）"
                  disabled={isPipelineRunning}
                  options={[
                    { value: "", label: "选择科目（可选）" },
                    ...subjectOptions.map((subject) => ({ value: String(subject.id), label: subject.name })),
                  ]}
                  className="h-10 w-full justify-between rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm"
                />
              </div>
            </CardContent>
          </Card>

          {/* Right: Config */}
          <Card>
            <CardHeader>
              <div className="flex flex-col gap-1">
                <h3 className="font-display text-2xl font-bold text-[var(--ink)]">导入配置</h3>
                <p className="text-sm text-[var(--color-text-secondary)]">调整参数以控制导入行为</p>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="space-y-1">
                  <span className="text-[11px] font-medium text-[var(--color-text-secondary)]">导入模式</span>
                  <CustomSelect
                    value={importMode}
                    onChange={setImportMode}
                    disabled={isPipelineRunning}
                    options={[
                      { value: "auto", label: "auto（自动检测）" },
                      { value: "book", label: "book（教辅）" },
                      { value: "exam", label: "exam（试卷）" },
                    ]}
                    className="h-10 w-full justify-between rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm"
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-[11px] font-medium text-[var(--color-text-secondary)]">置信度阈值</span>
                  <Input type="number" step="0.1" min="0" max="1" disabled={isPipelineRunning} value={confidenceThreshold} onChange={(event) => setConfidenceThreshold(event.target.value)} />
                  {confidenceError ? <p className="mt-0.5 text-[10px] text-red-500">{confidenceError}</p> : null}
                </label>
              </div>
              {isPdfFile ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="space-y-1">
                    <span className="text-[11px] font-medium text-[var(--color-text-secondary)]">起始页</span>
                    <Input type="number" min="1" placeholder="留空从第1页" disabled={isPipelineRunning} value={pageStart} onChange={(event) => setPageStart(event.target.value)} />
                    {pageStartError ? <p className="mt-0.5 text-[10px] text-red-500">{pageStartError}</p> : null}
                  </label>
                  <label className="space-y-1">
                    <span className="text-[11px] font-medium text-[var(--color-text-secondary)]">结束页</span>
                    <Input type="number" min="1" placeholder="留空到最后" disabled={isPipelineRunning} value={pageEnd} onChange={(event) => setPageEnd(event.target.value)} />
                    {pageEndError ? <p className="mt-0.5 text-[10px] text-red-500">{pageEndError}</p> : null}
                  </label>
                  {pageRangeError ? <p className="col-span-2 -mt-2 text-[10px] text-red-500">{pageRangeError}</p> : null}
                </div>
              ) : null}
              <label className={`flex cursor-pointer items-center gap-2.5 rounded-xl border px-3 py-2.5 text-sm text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] ${
                enableAiRepair ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]" : "border-[var(--color-border)] bg-white/50"
              }`}>
                <input type="checkbox" checked={enableAiRepair} onChange={(event) => setEnableAiRepair(event.target.checked)} disabled={isPipelineRunning} className="h-4 w-4 rounded border-[var(--color-border)] text-[var(--color-primary)] accent-[var(--color-primary)]" />
                <div>
                  <span className="text-xs font-semibold text-[var(--ink)]">AI 修复</span>
                  <p className="text-[10px] text-[var(--color-text-hint)]">自动校正 OCR 偏差</p>
                </div>
              </label>


              {/* Submit */}
              <div className="flex items-center justify-end gap-4 border-t border-[var(--color-border)] pt-4">
                <Button disabled={!file || uploadMutation.isPending || isPipelineRunning} onClick={() => uploadMutation.mutate()} className="h-10 px-6 text-sm">
                  <FileUp className="h-4 w-4" />
                  {uploadMutation.isPending ? "上传中..." : isPipelineRunning ? "解析中..." : "开始导入"}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      ) : null}

      {/* ═══════════════════════════════════════════════════
          TAB: Progress
          ═══════════════════════════════════════════════════ */}
      {activeTab === "progress" ? (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">管线状态</h3>
              <p className="mt-0.5 text-sm text-[var(--color-text-secondary)]">实时追踪导入管线进度</p>
            </div>
            {pipelineId ? (
              <Button variant="secondary" disabled={!pipelineId || statusQuery.isFetching} onClick={() => statusQuery.refetch()} className="shrink-0">
                <RefreshCw className={`h-3.5 w-3.5 ${statusQuery.isFetching ? "animate-spin" : ""}`} />
              </Button>
            ) : null}
          </CardHeader>
          <CardContent>
            {/* No pipeline */}
            {!pipelineId ? (
              <div className="flex flex-col items-center py-16 text-center">
                <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-[var(--color-bg-input)]">
                  <FileUp className="h-7 w-7 text-[var(--color-text-hint)]" />
                </div>
                <p className="text-sm font-semibold text-[var(--color-text-secondary)]">暂无导入任务</p>
                <p className="mt-1.5 max-w-xs text-xs leading-relaxed text-[var(--color-text-hint)]">
                  在「上传」标签页选择文件并提交后，进度将在此处实时显示。
                </p>
                <Button variant="secondary" className="mt-4" onClick={() => setActiveTab("upload")}>
                  前往上传
                </Button>
              </div>
            ) : null}

            {/* Fetching first time */}
            {pipelineId && !status && !statusQuery.isError ? (
              <div className="flex items-center gap-3 rounded-2xl border border-[var(--color-border)] bg-white/70 px-4 py-6 text-sm text-[var(--color-text-secondary)]">
                <RefreshCw className="h-4 w-4 animate-spin" />
                正在获取导入进度...
              </div>
            ) : null}

            {/* Active pipeline */}
            {status ? (
              <div className="space-y-6">
                {/* Stage Bar */}
                <div className="rounded-2xl border border-[var(--color-border-light)] bg-white/60 p-6 backdrop-blur-sm">
                  <div className="flex items-start justify-between">
                    {stages.map((stg, i) => (
                      <div key={stg.name} className="flex flex-1 flex-col items-center gap-3 relative">
                        {/* Connector line to next stage */}
                        {i < stages.length - 1 && (
                          <div className="stage-connector">
                            <div className={`fill ${stg.s === "done" ? "w-full bg-[var(--color-success)]" : stg.s === "active" ? "w-1/3 bg-[var(--color-warning)]" : "w-0 bg-[var(--color-border)]"}`} />
                          </div>
                        )}
                        <div className={`relative flex h-10 w-10 items-center justify-center rounded-full text-sm font-bold transition-all duration-500 ease-out ${
                          stg.s === "done" ? "bg-[var(--color-success)] text-white shadow-[0_0_0_4px_rgba(91,140,91,0.15)] stage-circle-done"
                            : stg.s === "active" ? "bg-[var(--color-warning)] text-white shadow-[0_0_0_4px_rgba(196,154,107,0.2)] stage-circle-active"
                              : stg.s === "failed" ? "bg-[var(--color-danger)] text-white"
                                : "bg-white text-[var(--color-text-hint)] border-2 border-[var(--color-border)]"
                        }`}>
                          {stg.s === "done" ? (
                            <CheckCircle2 className="h-5 w-5" />
                          ) : stg.s === "failed" ? (
                            <span className="text-lg font-bold">!</span>
                          ) : (
                            <span className="text-sm font-bold">{i + 1}</span>
                          )}
                        </div>
                        <span className={`text-[11px] font-semibold text-center leading-tight px-1 ${
                          stg.s === "active" ? "text-[var(--color-warning)]"
                            : stg.s === "done" ? "text-[var(--color-success)]"
                              : stg.s === "failed" ? "text-[var(--color-danger)]"
                                : "text-[var(--color-text-hint)]"
                        }`}>{stg.name}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Status + Progress */}
                <div className="flex flex-wrap items-center gap-3">
                  {isPipelineRunning ? (
                    <span className="animate-rise-in flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700 transition-all duration-300">
                      <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-amber-500" />
                      处理中
                    </span>
                  ) : (
                    <span className={`animate-rise-in flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold transition-all duration-300 ${
                      ["failed", "error"].includes(status.status) ? "bg-red-50 text-red-700" : "bg-green-50 text-green-700"
                    }`}>
                      <span className={`inline-block h-2 w-2 rounded-full transition-colors duration-300 ${
                        ["failed", "error"].includes(status.status) ? "bg-red-500" : "bg-green-500"
                      }`} />
                      {status.status === "completed" || status.status === "success" || status.status === "finished" ? "已完成" : "失败"}
                    </span>
                  )}
                  {status.current_stage ? <span className="animate-rise-in rounded-full bg-[var(--color-bg-input)] px-2.5 py-0.5 text-[10px] font-medium text-[var(--color-text-secondary)] transition-all duration-300">{status.current_stage}</span> : null}
                  {pipelineId ? <span className="ml-auto font-mono text-[10px] text-[var(--color-text-hint)]">{pipelineId}</span> : null}
                </div>

                {/* Progress bar */}
                {isPipelineRunning ? (
                  <div className="metric-card space-y-2">
                    <div className="flex items-center justify-between text-xs text-[var(--color-text-hint)]">
                      <span>解析进度</span>
                      <span className="font-bold text-[var(--ink)]">{status.ocr_progress || "0%"}</span>
                    </div>
                    <div className="overflow-hidden rounded-full bg-[var(--color-bg-input)]">
                      <div className="h-2.5 rounded-full bg-gradient-to-r from-[var(--color-primary)] to-[#7b9bbb] transition-all duration-1000 ease-out" style={{ width: `${parseProgressPercent(status.ocr_progress)}%` }} />
                    </div>
                  </div>
                ) : null}

                {/* Pipeline summary cards */}
                <div className="stagger-enter grid grid-cols-3 gap-3 lg:grid-cols-6">
                  {progressItems.map(([label, value]) => (
                    <div key={String(label)} className="metric-card !p-3">
                      <p className="font-mono text-[8px] uppercase tracking-[0.2em] text-[var(--color-text-hint)]">{label}</p>
                      <div className="mt-1.5 truncate text-sm font-semibold text-[var(--ink)]">
                        {label === "当前状态" ? <StatusBadge tone={statusTone(String(value || ""))}>{String(value || "—")}</StatusBadge> : String(value || "—")}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Page Range Info */}
                {status.page_range ? (
                  <div className="rounded-xl border border-[var(--color-border)] bg-white/70 p-4">
                    <p className="font-mono text-[8px] uppercase tracking-[0.2em] text-[var(--color-text-hint)]">页码范围</p>
                    <div className="mt-2 flex flex-wrap gap-4 text-sm">
                      <span>有效范围: <strong>{status.page_range.effective_start} - {status.page_range.effective_end}</strong></span>
                      <span>总页数: <strong>{status.page_range.total_pages}</strong></span>
                      <span>选中页数: <strong>{status.page_range.selected_page_count}</strong></span>
                      {status.page_range.requested_start != null ? <span>请求起始: <strong>{status.page_range.requested_start}</strong></span> : null}
                      {status.page_range.requested_end != null ? <span>请求结束: <strong>{status.page_range.requested_end}</strong></span> : null}
                    </div>
                  </div>
                ) : null}

                {/* Stats & Errors */}
                <div className="grid gap-3 sm:grid-cols-2">
                  <details className="group rounded-xl border border-[var(--color-border)] bg-white/70">
                    <summary className="flex cursor-pointer items-center justify-between px-4 py-3 text-xs font-semibold text-[var(--ink)]">
                      <span className="flex items-center gap-2">
                        <span>统计</span>
                        {status.stats && Object.keys(status.stats).length > 0 ? <span className="rounded-full bg-[var(--color-primary-light)] px-1.5 py-0.5 text-[9px] font-medium text-[var(--color-primary-dark)]">{Object.keys(status.stats).length}</span> : null}
                      </span>
                      <span className="text-[9px] text-[var(--color-text-hint)] transition group-open:rotate-180">▼</span>
                    </summary>
                    <pre className="max-h-48 overflow-auto border-t border-[var(--color-border)] px-4 py-3 whitespace-pre-wrap text-[10px] text-[var(--color-text-secondary)]">{renderJson(status.stats)}</pre>
                  </details>
                  <details className="group rounded-xl border border-[var(--color-border)] bg-white/70">
                    <summary className="flex cursor-pointer items-center justify-between px-4 py-3 text-xs font-semibold text-[var(--ink)]">
                      <span className="flex items-center gap-2">
                        <span>错误日志</span>
                        {Array.isArray(status.errors) && status.errors.length > 0 ? <span className="rounded-full bg-red-100 px-1.5 py-0.5 text-[9px] font-medium text-red-600">{status.errors.length}</span> : null}
                      </span>
                      <span className="text-[9px] text-[var(--color-text-hint)] transition group-open:rotate-180">▼</span>
                    </summary>
                    {Array.isArray(status.errors) && status.errors.length > 0 ? (
                      <pre className="max-h-48 overflow-auto border-t border-[var(--color-border)] px-4 py-3 whitespace-pre-wrap text-[10px] text-red-600">{status.errors.map((e) => `• ${e}`).join("\n")}</pre>
                    ) : (
                      <p className="border-t border-[var(--color-border)] px-4 py-3 text-[10px] text-[var(--color-text-hint)]">暂无错误</p>
                    )}
                  </details>
                </div>

                {/* Quick actions */}
                {status.batch_id ? (
                  <div className="flex flex-wrap gap-2 border-t border-[var(--color-border)] pt-4">
                    <a className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-white/70 px-4 text-xs font-semibold text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)]" href={`/imports/review?batch_id=${encodeURIComponent(status.batch_id)}`}>
                      <FileText className="h-3.5 w-3.5" />
                      待审核
                    </a>
                    <Button variant="secondary" className="h-9" onClick={() => setActiveTab("quality")}>
                      查看质量报告
                    </Button>
                  </div>
                ) : null}
              </div>
            ) : null}

            {/* Fetch error */}
            {statusQuery.isError ? (
              <div className="flex items-center gap-2.5 rounded-2xl border border-[var(--color-danger)] bg-red-50/70 px-4 py-3 text-xs text-[var(--color-danger)]">
                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                无法获取导入进度，请刷新重试。
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {/* ═══════════════════════════════════════════════════
          TAB: Quality
          ═══════════════════════════════════════════════════ */}
      {activeTab === "quality" ? (
        <Card>
          <CardHeader>
            <div className="flex flex-col gap-1">
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">质量报告</h3>
              <p className="text-sm text-[var(--color-text-secondary)]">
                {status?.quality_report ? `批次 ${status.batch_id || "—"} · 共 ${status.quality_report.total_questions ?? "—"} 题` : "导入完成后将在此处展示质量分析"}
              </p>
            </div>
          </CardHeader>
          <CardContent>
            {/* No quality report yet */}
            {!status?.quality_report ? (
              <div className="flex flex-col items-center py-16 text-center">
                <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-[var(--color-bg-input)]">
                  <FileText className="h-7 w-7 text-[var(--color-text-hint)]" />
                </div>
                <p className="text-sm font-semibold text-[var(--color-text-secondary)]">暂无质量报告</p>
                <p className="mt-1.5 max-w-xs text-xs leading-relaxed text-[var(--color-text-hint)]">
                  {pipelineId ? "导入任务完成后将自动生成质量分析报告。" : "提交导入任务后，质量报告将在此处展示。"}
                </p>
                {!pipelineId ? (
                  <Button variant="secondary" className="mt-4" onClick={() => setActiveTab("upload")}>
                    前往上传
                  </Button>
                ) : null}
              </div>
            ) : null}

            {/* Quality Report Content */}
            {status?.quality_report ? (
              <div className="space-y-6">
                {/* Main stats */}
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <div className="metric-card text-center">
                    <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-[var(--color-text-hint)]">总题数</p>
                    <p className="mt-2 font-display text-4xl font-bold text-[var(--ink)]">{status.quality_report.total_questions}</p>
                  </div>
                  {status.quality_report.low_risk !== undefined ? (
                    <div className="metric-card text-center border-green-200/60 bg-green-50/50">
                      <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-green-600">低风险</p>
                      <p className="mt-2 font-display text-4xl font-bold text-green-700">{status.quality_report.low_risk}</p>
                    </div>
                  ) : null}
                  {status.quality_report.medium_risk !== undefined ? (
                    <div className="metric-card text-center border-amber-200/60 bg-amber-50/50">
                      <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-amber-600">需检查</p>
                      <p className="mt-2 font-display text-4xl font-bold text-amber-700">{status.quality_report.medium_risk}</p>
                    </div>
                  ) : null}
                  {status.quality_report.high_risk !== undefined ? (
                    <div className="metric-card text-center border-red-200/60 bg-red-50/50">
                      <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-red-600">高风险</p>
                      <p className="mt-2 font-display text-4xl font-bold text-red-700">{status.quality_report.high_risk}</p>
                    </div>
                  ) : null}
                </div>

                {/* Secondary stats */}
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {status.quality_report.ai_answer_count !== undefined ? (
                    <div className="rounded-xl bg-purple-50/70 p-3.5 text-center">
                      <p className="text-[9px] uppercase tracking-wider text-purple-600">AI 答案</p>
                      <p className="mt-1 font-display text-xl font-bold text-purple-700">{status.quality_report.ai_answer_count}</p>
                    </div>
                  ) : null}
                  {status.quality_report.math_image_count !== undefined ? (
                    <div className="rounded-xl bg-blue-50/70 p-3.5 text-center">
                      <p className="text-[9px] uppercase tracking-wider text-blue-600">公式截图</p>
                      <p className="mt-1 font-display text-xl font-bold text-blue-700">{status.quality_report.math_image_count}</p>
                    </div>
                  ) : null}
                  {status.quality_report.table_markdown_count !== undefined ? (
                    <div className="rounded-xl bg-cyan-50/70 p-3.5 text-center">
                      <p className="text-[9px] uppercase tracking-wider text-cyan-600">表格</p>
                      <p className="mt-1 font-display text-xl font-bold text-cyan-700">{status.quality_report.table_markdown_count}</p>
                    </div>
                  ) : null}
                  {status.quality_report.estimated_manual_check_rate !== undefined ? (
                    <div className="rounded-xl bg-[var(--color-bg-input)] p-3.5 text-center">
                      <p className="text-[9px] uppercase tracking-wider text-[var(--color-text-hint)]">人工检查率</p>
                      <p className={`mt-1 font-display text-xl font-bold ${(status.quality_report.estimated_manual_check_rate > 0.4) ? "text-amber-700" : "text-[var(--ink)]"}`}>
                        {(status.quality_report.estimated_manual_check_rate * 100).toFixed(0)}%
                      </p>
                    </div>
                  ) : null}
                </div>

                {/* Performance Summary */}
                {status.quality_report.performance_summary ? (
                  <details className="group rounded-2xl border border-[var(--color-border)] bg-white/70">
                    <summary className="flex cursor-pointer items-center justify-between px-5 py-4 text-sm font-semibold text-[var(--ink)]">
                      <span>性能概览</span>
                      <span className="text-[10px] text-[var(--color-text-hint)] transition group-open:rotate-180">▼</span>
                    </summary>
                    <div className="grid grid-cols-2 gap-x-8 gap-y-3 border-t border-[var(--color-border)] px-5 py-4 text-xs text-[var(--color-text-secondary)] sm:grid-cols-3">
                      <div className="flex justify-between"><span>总耗时</span><span className="font-semibold text-[var(--ink)]">{(status.quality_report.performance_summary.total_duration_ms / 1000).toFixed(1)}s</span></div>
                      <div className="flex justify-between"><span>AI 调用</span><span className="font-semibold text-[var(--ink)]">{status.quality_report.performance_summary.total_ai_calls} 次</span></div>
                      <div className="flex justify-between"><span>Token 用量</span><span className="font-semibold text-[var(--ink)]">{status.quality_report.performance_summary.total_tokens_used}</span></div>
                      <div className="flex justify-between"><span>OCR 缓存命中率</span><span className="font-semibold text-[var(--ink)]">{(status.quality_report.performance_summary.cache_hit_rate * 100).toFixed(0)}%</span></div>
                      <div className="flex justify-between"><span>最慢阶段</span><span className="font-semibold text-[var(--ink)]">{status.quality_report.performance_summary.slowest_stage} ({(status.quality_report.performance_summary.slowest_duration_ms / 1000).toFixed(1)}s)</span></div>
                    </div>
                  </details>
                ) : null}

                {/* Actions */}
                <div className="flex flex-wrap gap-3 border-t border-[var(--color-border)] pt-4">
                  {status.batch_id ? (
                    <>
                      <a className="inline-flex h-10 items-center gap-2 rounded-xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-4 text-xs font-semibold text-[var(--color-danger)] transition hover:bg-red-100" href={`/imports/review?batch_id=${encodeURIComponent(status.batch_id)}&risk_filter=high`}>
                        <AlertCircle className="h-3.5 w-3.5" />
                        查看高风险题
                      </a>
                      <a className="inline-flex h-10 items-center gap-2 rounded-xl border border-[var(--color-border)] bg-white/70 px-4 text-xs font-semibold text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)]" href={`/imports/review?batch_id=${encodeURIComponent(status.batch_id)}`}>
                        <FileText className="h-3.5 w-3.5" />
                        进入审核区
                      </a>
                    </>
                  ) : null}
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

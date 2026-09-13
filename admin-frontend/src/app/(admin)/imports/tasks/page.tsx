"use client";

import { useId, useEffect, useRef, useState, type DragEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, ChevronDown, FileBox, FileText, FileUp, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CustomSelect } from "@/components/ui/custom-select";
import { StatusBadge } from "@/components/status-badge";
import { apiRequest, toQuery } from "@/lib/api/client";
import type { ImportPipelineStatusResponse, ImportPipelineUploadResponse, QuestionCsvImportResponse } from "@/lib/api/types";
import { parseProgressPercent } from "@/lib/import-utils";
import { cn } from "@/lib/utils";
import { ImportMetric, ImportPanelHeader, ImportProgressBar, ImportWorkspaceHeader } from "../components/import-workspace";
import { ImportToast } from "../components/import-toast";

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


export default function ImportTasksPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
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
  const isCsvFile = file?.name.toLowerCase().endsWith(".csv") ?? false;
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

  const handleFileDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (!isPipelineRunning) setDragActive(true);
  };
  const handleFileDragLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragActive(false);
  };
  const handleFileDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragActive(false);
    if (isPipelineRunning) return;
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) setFile(dropped);
  };

  const statusQuery = useQuery({
    queryKey: ["import-pipeline", pipelineId],
    queryFn: () => apiRequest<ImportPipelineStatusResponse>(`/imports/pipelines/${pipelineId}`),
    enabled: pipelineId !== null,
    refetchInterval: (query) => (isTerminalStatus(query.state.data?.status) ? false : 2500),
    retry: false,
  });

  const uploadMutation = useMutation({
    mutationFn: async (): Promise<
      | { kind: "pipeline"; data: ImportPipelineUploadResponse }
      | { kind: "csv"; data: QuestionCsvImportResponse }
    > => {
      if (!file) throw new Error("请选择要导入的文件");
      const formData = new FormData();
      formData.set("file", file);

      if (file.name.toLowerCase().endsWith(".csv")) {
        const data = await apiRequest<QuestionCsvImportResponse>("/imports/questions-csv", {
          method: "POST",
          body: formData,
          timeoutMs: 120_000,
          exposeErrorDetail: true,
        });
        return { kind: "csv", data };
      }

      const query = toQuery({
        subject_id: subjectId ? Number(subjectId) : undefined,
        import_mode: importMode,
        enable_ai_repair: enableAiRepair,
        confidence_threshold: confidenceThreshold || undefined,
        image_fast_mode: true,
        page_start: pageStart || undefined,
        page_end: pageEnd || undefined,
      });
      const data = await apiRequest<ImportPipelineUploadResponse>(`/imports/upload${query}`, { method: "POST", body: formData });
      return { kind: "pipeline", data };
    },
    onSuccess: (result) => {
      if (result.kind === "csv") {
        setPipelineId(null);
        setMessage(`CSV 导入完成：共 ${result.data.total_rows} 行，新增 ${result.data.inserted_count} 题，跳过 ${result.data.skipped_count} 题。`);
        setActiveTab("upload");
        queryClient.invalidateQueries({ queryKey: ["questions"] });
        return;
      }
      setPipelineId(result.data.pipeline_id);
      setMessage(`导入任务已提交：${result.data.pipeline_id}`);
      setActiveTab("progress");
    },
    onError: (error) => {
      const detail = error instanceof Error ? error.message : "上传失败，请稍后重试。";
      setMessage(isCsvFile ? `CSV 导入失败：${detail}` : detail);
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
  const lastReachedStage = stages.reduce((last, stage, index) => stage.s !== "pending" ? index : last, 0);
  const stageRailProgress = stages.length > 1 ? (lastReachedStage / (stages.length - 1)) * 100 : 0;

  const tabs: { key: TabKey; label: string; desc: string; badge?: string }[] = [
    { key: "upload", label: "上传", desc: "选择文件与配置" },
    { key: "progress", label: "进度", desc: "实时管线状态", badge: isPipelineRunning ? "处理中" : undefined },
    { key: "quality", label: "质量", desc: "报告与审核", badge: status?.quality_report ? "就绪" : undefined },
  ];

  return (
    <div className="space-y-6 pb-4">
      <ImportWorkspaceHeader
        icon={FileUp}
        title="导入任务"
        description="支持 PDF、文档、表格、图片解析导入，也支持 questions CSV 直接导入题库。"
        meta={
          pipelineId ? (
            <div className="inline-flex h-9 items-center gap-2 rounded-full border border-[var(--color-border)] bg-white/70 px-3 text-xs text-[var(--color-text-secondary)]">
              <span className={cn("h-1.5 w-1.5 rounded-full", isPipelineRunning ? "import-status-active bg-[var(--color-warning)]" : status && ["failed", "error"].includes(status.status) ? "bg-[var(--color-danger)]" : "bg-[var(--color-success)]")} aria-hidden="true" />
              {isPipelineRunning ? "任务处理中" : status ? (["failed", "error"].includes(status.status) ? "任务失败" : "任务完成") : "任务已提交"}
            </div>
          ) : (
            <div className="inline-flex h-9 items-center rounded-full border border-[var(--color-border)] bg-white/70 px-3 text-xs text-[var(--color-text-secondary)]">支持 CSV / PDF / 图片 / TXT / Excel</div>
          )
        }
      />

      <ImportToast
        message={message}
        tone={uploadMutation.isError ? "error" : "success"}
        onDismiss={() => setMessage(null)}
      />

      <nav aria-label="导入任务步骤" className="grid grid-cols-3 overflow-hidden rounded-2xl border border-[var(--color-border-light)] bg-[rgba(239,235,229,0.42)] p-1.5 import-enter" style={{ animationDelay: "45ms" }}>
        {tabs.map((tab) => {
          const active = activeTab === tab.key;
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              aria-current={active ? "step" : undefined}
              className={cn(
                "relative flex min-h-14 min-w-0 items-center justify-center gap-2 rounded-xl px-3 text-left import-interactive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]",
                active ? "bg-white text-[var(--ink)] shadow-[0_2px_10px_rgba(27,39,51,0.06)]" : "text-[var(--color-text-hint)] hover:bg-white/55 hover:text-[var(--color-text-secondary)]",
              )}
            >
              <span className="min-w-0">
                <span className="block text-xs font-semibold sm:text-sm">{tab.label}</span>
                <span className="mt-0.5 hidden text-[10px] font-normal text-[var(--color-text-hint)] sm:block">{tab.desc}</span>
              </span>
              {tab.badge ? (
                <span className={cn(
                  "shrink-0 rounded-full border px-2 py-0.5 text-[9px] font-semibold",
                  tab.badge === "处理中"
                    ? "border-[rgba(196,154,107,0.3)] bg-[var(--color-warning-light)] text-[var(--color-text-primary)]"
                    : "border-[rgba(91,140,91,0.25)] bg-[var(--color-success-light)] text-[var(--color-success)]",
                )}>{tab.badge}</span>
              ) : null}
              <span aria-hidden="true" className={cn("absolute bottom-1.5 left-1/2 h-0.5 w-8 -translate-x-1/2 rounded-full bg-[var(--color-primary)] transition-[transform,opacity] duration-200", active ? "scale-x-100 opacity-100" : "scale-x-50 opacity-0")} />
            </button>
          );
        })}
      </nav>

      {activeTab === "upload" ? (
        <section className="overflow-hidden rounded-2xl border border-[var(--color-border-light)] bg-[rgba(254,252,249,0.82)] shadow-[var(--shadow-card)] import-panel-swap">
          <ImportPanelHeader title="新建导入任务" description="上传来源与解析配置在同一工作台完成；任务运行期间配置将锁定。" />
          <div className="grid lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
            <div className="border-b border-[var(--color-border-light)] p-4 sm:p-5 lg:border-b-0 lg:border-r">
              <label htmlFor={fileInputId} className="block">
                <div
                  onDragOver={handleFileDragOver}
                  onDragLeave={handleFileDragLeave}
                  onDrop={handleFileDrop}
                  className={cn(
                  "relative flex min-h-[260px] cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed px-6 py-8 text-center transition-[border-color,background-color,box-shadow] import-interactive",
                  (dragActive || file) && "import-drop-active",
                  isPipelineRunning
                    ? "cursor-not-allowed border-[var(--color-border)] bg-[var(--color-bg-input)] opacity-60"
                    : dragActive || file
                      ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] shadow-[inset_0_0_0_1px_rgba(74,111,138,0.08)]"
                      : "border-[var(--color-border)] bg-white/60 hover:border-[var(--color-primary)] hover:bg-white",
                )}>
                  <div className="grid h-14 w-14 place-items-center rounded-2xl border border-[rgba(74,111,138,0.16)] bg-white/80 text-[var(--color-primary-dark)] import-drop-icon">
                    <FileBox className="h-6 w-6" strokeWidth={1.6} aria-hidden="true" />
                  </div>
                  {file ? (
                    <div className="mt-4 max-w-full import-feedback-in">
                      <p className="max-w-md truncate text-sm font-semibold text-[var(--ink)]" title={file.name}>{file.name}</p>
                      <p className="mt-1 text-xs text-[var(--color-text-hint)]">{(file.size / 1024 / 1024).toFixed(1)} MB · 已就绪</p>
                    </div>
                  ) : (
                    <div className="mt-4">
                      <p className="text-sm font-semibold text-[var(--ink)]">选择导入文件</p>
                      <p className="mt-1.5 text-xs leading-5 text-[var(--color-text-hint)]">CSV、PDF、JPG、PNG、WebP、TXT、XLSX、XLS</p>
                    </div>
                  )}
                  <input id={fileInputId} type="file" accept=".csv,.pdf,.txt,.xlsx,.xls,.jpg,.jpeg,.png,.webp" disabled={isPipelineRunning} className="absolute inset-0 cursor-pointer opacity-0 disabled:cursor-not-allowed" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
                </div>
              </label>

              {!isCsvFile ? (
                <div className="mt-4 space-y-1.5">
                  <span className="text-xs font-semibold text-[var(--color-text-secondary)]">科目</span>
                  <CustomSelect
                    value={subjectId}
                    onChange={setSubjectId}
                    placeholder="选择科目（可选）"
                    disabled={isPipelineRunning}
                    options={[{ value: "", label: "未指定科目" }, ...subjectOptions.map((subject) => ({ value: String(subject.id), label: subject.name }))]}
                    className="h-11 w-full justify-between rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm"
                  />
                </div>
              ) : (
                <div className="mt-4 rounded-xl border border-[rgba(74,111,138,0.16)] bg-white/55 px-3.5 py-3 text-xs leading-5 text-[var(--color-text-secondary)]">
                  CSV 将逐行读取 <span className="font-mono font-semibold text-[var(--ink)]">subject_id</span>，支持同一文件包含多个科目，无需额外选择或覆盖科目。
                </div>
              )}
            </div>

            <div className="flex flex-col p-4 sm:p-5">
              {isCsvFile ? (
                <div className="rounded-xl border border-[rgba(74,111,138,0.22)] bg-[var(--color-primary-light)] p-4 import-panel-swap">
                  <div className="flex items-start gap-3">
                    <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-[rgba(74,111,138,0.18)] bg-white/80 text-[var(--color-primary-dark)]">
                      <FileText className="h-5 w-5" aria-hidden="true" />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-[var(--ink)]">questions CSV 直接导入</p>
                      <p className="mt-1 text-[11px] leading-5 text-[var(--color-text-secondary)]">CSV 会逐行使用各自的 subject_id 直接写入正式题库，支持多科目混合导入，不经过 OCR / AI 审核管线。源文件中的 id 与 current_version_id 不复用，目标库会自动生成主键和题目版本；相同 sync_uuid 会自动跳过。</p>
                    </div>
                  </div>
                </div>
              ) : null}

              {!isCsvFile ? (
                <>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="space-y-1.5">
                  <span className="text-xs font-semibold text-[var(--color-text-secondary)]">导入模式</span>
                  <CustomSelect
                    value={importMode}
                    onChange={setImportMode}
                    disabled={isPipelineRunning}
                    options={[
                      { value: "auto", label: "自动检测" },
                      { value: "book", label: "教辅模式" },
                      { value: "exam", label: "试卷模式" },
                    ]}
                    className="h-11 w-full justify-between rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm"
                  />
                </label>
                <label className="space-y-1.5">
                  <span className="text-xs font-semibold text-[var(--color-text-secondary)]">置信度阈值</span>
                  <Input type="number" step="0.1" min="0" max="1" disabled={isPipelineRunning} value={confidenceThreshold} onChange={(event) => setConfidenceThreshold(event.target.value)} className="h-11" aria-invalid={Boolean(confidenceError)} aria-describedby={confidenceError ? "confidence-error" : undefined} />
                  {confidenceError ? <p id="confidence-error" className="text-[11px] text-[var(--color-danger)]">{confidenceError}</p> : <p className="text-[11px] text-[var(--color-text-hint)]">0–1，越高越保守</p>}
                </label>
              </div>

              {isPdfFile ? (
                <div className="mt-4 grid gap-4 rounded-xl border border-[var(--color-border-light)] bg-white/55 p-4 sm:grid-cols-2 import-panel-swap">
                  <label className="space-y-1.5">
                    <span className="text-xs font-semibold text-[var(--color-text-secondary)]">起始页</span>
                    <Input type="number" min="1" placeholder="默认第 1 页" disabled={isPipelineRunning} value={pageStart} onChange={(event) => setPageStart(event.target.value)} className="h-11" aria-invalid={Boolean(pageStartError || pageRangeError)} />
                    {pageStartError ? <p className="text-[11px] text-[var(--color-danger)]">{pageStartError}</p> : null}
                  </label>
                  <label className="space-y-1.5">
                    <span className="text-xs font-semibold text-[var(--color-text-secondary)]">结束页</span>
                    <Input type="number" min="1" placeholder="默认最后一页" disabled={isPipelineRunning} value={pageEnd} onChange={(event) => setPageEnd(event.target.value)} className="h-11" aria-invalid={Boolean(pageEndError || pageRangeError)} />
                    {pageEndError ? <p className="text-[11px] text-[var(--color-danger)]">{pageEndError}</p> : null}
                  </label>
                  {pageRangeError ? <p className="sm:col-span-2 text-[11px] text-[var(--color-danger)]">{pageRangeError}</p> : null}
                </div>
              ) : null}

              <label className={cn(
                "mt-4 flex min-h-14 cursor-pointer items-center gap-3 rounded-xl border px-3.5 py-3 import-interactive",
                enableAiRepair ? "border-[rgba(74,111,138,0.3)] bg-[var(--color-primary-light)]" : "border-[var(--color-border)] bg-white/55 hover:border-[var(--color-primary)]",
              )}>
                <input type="checkbox" checked={enableAiRepair} onChange={(event) => setEnableAiRepair(event.target.checked)} disabled={isPipelineRunning} className="h-4 w-4 rounded border-[var(--color-border)] accent-[var(--color-primary)]" />
                <span>
                  <span className="block text-xs font-semibold text-[var(--ink)]">启用 AI 修复</span>
                  <span className="mt-0.5 block text-[11px] leading-5 text-[var(--color-text-hint)]">自动校正 OCR 偏差与结构异常</span>
                </span>
              </label>
                </>
              ) : null}

              <div className={cn("mt-auto flex items-center justify-between gap-4 border-t border-[var(--color-border-light)] pt-5", isCsvFile && "mt-5")}>
                <p className="text-[11px] leading-5 text-[var(--color-text-hint)]">{isCsvFile ? "CSV 导入成功后可直接在题库管理中查看；重复 sync_uuid 不会重复写入。" : "提交后自动切换至进度页，完成后可查看质量报告。"}</p>
                <Button
                  disabled={!file || uploadMutation.isPending || isPipelineRunning || (!isCsvFile && Boolean(confidenceError || pageStartError || pageEndError || pageRangeError))}
                  onClick={() => uploadMutation.mutate()}
                  className="h-11 min-w-32 import-interactive group"
                >
                  <FileUp className="h-4 w-4 transition-transform duration-200 group-hover:-translate-y-0.5 motion-reduce:transform-none" aria-hidden="true" />
                  {uploadMutation.isPending ? "导入中" : isPipelineRunning ? "解析中" : isCsvFile ? "导入 CSV" : "开始导入"}
                </Button>
              </div>
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === "progress" ? (
        <section className="overflow-hidden rounded-2xl border border-[var(--color-border-light)] bg-[rgba(254,252,249,0.82)] shadow-[var(--shadow-card)] import-panel-swap">
          <ImportPanelHeader
            title="管线状态"
            description="跟踪上传、OCR、AI 解析和质量检查；运行中每 2.5 秒自动刷新。"
            trailing={pipelineId ? (
              <Button variant="secondary" disabled={statusQuery.isFetching} onClick={() => statusQuery.refetch()} className="h-11 w-11 p-0" aria-label="刷新导入进度" title="刷新进度">
                <RefreshCw className={cn("h-4 w-4", statusQuery.isFetching && "animate-spin motion-reduce:animate-none")} aria-hidden="true" />
              </Button>
            ) : null}
          />

          {!pipelineId ? (
            <div className="flex min-h-[430px] items-center justify-center px-6 py-14">
              <div className="max-w-sm text-center import-panel-swap">
                <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] text-[var(--color-primary-dark)] import-soft-pop"><FileUp className="h-6 w-6" strokeWidth={1.6} aria-hidden="true" /></div>
                <p className="mt-4 text-sm font-semibold text-[var(--ink)]">暂无导入任务</p>
                <p className="mt-1.5 text-xs leading-5 text-[var(--color-text-hint)]">先在上传页选择文件并提交，任务状态会在这里持续更新。</p>
                <Button variant="secondary" className="mt-5 h-11 import-interactive" onClick={() => setActiveTab("upload")}>前往上传</Button>
              </div>
            </div>
          ) : null}

          {pipelineId && !status && !statusQuery.isError ? (
            <div className="flex min-h-[320px] items-center justify-center gap-3 px-6 py-14 text-sm text-[var(--color-text-secondary)]">
              <RefreshCw className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />正在获取导入进度
            </div>
          ) : null}

          {status ? (
            <div className="import-panel-swap">
              <div className="border-b border-[var(--color-border-light)] px-4 py-6 sm:px-6">
                <div className="relative grid grid-cols-4 gap-2">
                  <div className="absolute left-[12.5%] right-[12.5%] top-5 h-px overflow-hidden bg-[var(--color-border)]" aria-hidden="true">
                    <span className="absolute inset-0 origin-left bg-[var(--color-primary)] import-progress-fill" style={{ transform: `scaleX(${stageRailProgress / 100})` }} />
                  </div>
                  {stages.map((stg, i) => (
                    <div key={stg.name} className="relative z-10 flex min-w-0 flex-col items-center text-center">
                      <div className={cn(
                        "grid h-10 w-10 place-items-center rounded-full border-2 bg-white text-xs font-semibold import-interactive",
                        stg.s === "done" && "border-[var(--color-success)] bg-[var(--color-success)] text-white",
                        stg.s === "active" && "border-[var(--color-warning)] bg-[var(--color-warning)] text-white import-status-active",
                        stg.s === "failed" && "border-[var(--color-danger)] bg-[var(--color-danger)] text-white",
                        stg.s === "pending" && "border-[var(--color-border)] text-[var(--color-text-hint)]",
                      )}>
                        {stg.s === "done" ? <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> : stg.s === "failed" ? <AlertCircle className="h-4 w-4" aria-hidden="true" /> : i + 1}
                      </div>
                      <span className={cn(
                        "mt-2 text-[10px] font-semibold sm:text-[11px]",
                        stg.s === "done" ? "text-[var(--color-success)]" : stg.s === "active" ? "text-[var(--color-text-primary)]" : stg.s === "failed" ? "text-[var(--color-danger)]" : "text-[var(--color-text-hint)]",
                      )}>{stg.name}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 divide-x divide-y divide-[var(--color-border-light)] border-b border-[var(--color-border-light)] bg-white/55 sm:grid-cols-3 xl:grid-cols-6 xl:divide-y-0">
                {progressItems.map(([label, value]) => (
                  <ImportMetric
                    key={String(label)}
                    label={String(label)}
                    value={label === "当前状态" ? <StatusBadge tone={statusTone(String(value || ""))}>{String(value || "—")}</StatusBadge> : String(value || "—")}
                    tone={label === "题目数量" ? "primary" : "neutral"}
                  />
                ))}
              </div>

              <div className="space-y-5 p-4 sm:p-5">
                <div className="rounded-xl border border-[var(--color-border-light)] bg-white/60 px-4 py-3.5">
                  <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
                    <div className="flex items-center gap-2">
                      <span className={cn("h-1.5 w-1.5 rounded-full", isPipelineRunning ? "import-status-active bg-[var(--color-warning)]" : ["failed", "error"].includes(status.status) ? "bg-[var(--color-danger)]" : "bg-[var(--color-success)]")} aria-hidden="true" />
                      <span className="font-semibold text-[var(--color-text-secondary)]">{status.current_stage || "等待阶段信息"}</span>
                    </div>
                    <span className="font-mono text-[10px] text-[var(--color-text-hint)]">{pipelineId}</span>
                  </div>
                  <div className="mt-3 flex items-center justify-between text-xs">
                    <span className="text-[var(--color-text-hint)]">解析进度</span>
                    <span className="font-mono font-semibold tabular-nums text-[var(--ink)]">{status.ocr_progress || "0%"}</span>
                  </div>
                  <ImportProgressBar
                    value={parseProgressPercent(status.ocr_progress)}
                    label="解析进度"
                    active={isPipelineRunning}
                    tone={["failed", "error"].includes(status.status) ? "danger" : isTerminalStatus(status.status) ? "success" : "primary"}
                    className="mt-2"
                  />
                </div>

                {status.page_range ? (
                  <div className="grid gap-3 rounded-xl border border-[var(--color-border-light)] bg-white/60 p-4 sm:grid-cols-3 import-panel-swap">
                    <div><p className="text-[10px] font-medium text-[var(--color-text-hint)]">有效范围</p><p className="mt-1 text-sm font-semibold text-[var(--ink)]">{status.page_range.effective_start} – {status.page_range.effective_end}</p></div>
                    <div><p className="text-[10px] font-medium text-[var(--color-text-hint)]">总页数</p><p className="mt-1 text-sm font-semibold text-[var(--ink)]">{status.page_range.total_pages}</p></div>
                    <div><p className="text-[10px] font-medium text-[var(--color-text-hint)]">选中页数</p><p className="mt-1 text-sm font-semibold text-[var(--ink)]">{status.page_range.selected_page_count}</p></div>
                  </div>
                ) : null}

                <div className="grid gap-3 sm:grid-cols-2">
                  <details className="group overflow-hidden rounded-xl border border-[var(--color-border-light)] bg-white/60">
                    <summary className="flex min-h-12 cursor-pointer items-center justify-between px-4 text-xs font-semibold text-[var(--ink)] import-interactive hover:bg-white/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--color-primary)]">
                      <span>统计数据</span><ChevronDown className="h-4 w-4 text-[var(--color-text-hint)] import-chevron group-open:rotate-180" aria-hidden="true" />
                    </summary>
                    <pre className="max-h-48 overflow-auto border-t import-details-body border-[var(--color-border-light)] px-4 py-3 whitespace-pre-wrap text-[10px] leading-5 text-[var(--color-text-secondary)]">{renderJson(status.stats)}</pre>
                  </details>
                  <details className="group overflow-hidden rounded-xl border border-[var(--color-border-light)] bg-white/60">
                    <summary className="flex min-h-12 cursor-pointer items-center justify-between px-4 text-xs font-semibold text-[var(--ink)] import-interactive hover:bg-white/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--color-primary)]">
                      <span className="flex items-center gap-2">错误日志{Array.isArray(status.errors) && status.errors.length > 0 ? <span className="rounded-full bg-[var(--color-danger-light)] px-2 py-0.5 text-[9px] text-[var(--color-danger)]">{status.errors.length}</span> : null}</span>
                      <ChevronDown className="h-4 w-4 text-[var(--color-text-hint)] import-chevron group-open:rotate-180" aria-hidden="true" />
                    </summary>
                    {Array.isArray(status.errors) && status.errors.length > 0 ? <pre className="max-h-48 overflow-auto border-t import-details-body border-[var(--color-border-light)] px-4 py-3 whitespace-pre-wrap text-[10px] leading-5 text-[var(--color-danger)]">{status.errors.map((e) => `• ${e}`).join("\n")}</pre> : <p className="border-t border-[var(--color-border-light)] px-4 py-3 text-[11px] import-details-body text-[var(--color-text-hint)]">暂无错误</p>}
                  </details>
                </div>

                {status.batch_id ? (
                  <div className="flex flex-wrap items-center justify-end gap-2 border-t border-[var(--color-border-light)] pt-4">
                    <a className="inline-flex h-11 items-center gap-2 rounded-xl border border-[var(--color-border)] bg-white px-4 text-xs font-semibold text-[var(--color-text-secondary)] import-interactive hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] focus-visible:ring-offset-2" href={`/imports/review?batch_id=${encodeURIComponent(status.batch_id)}`}><FileText className="h-4 w-4" aria-hidden="true" />待审核</a>
                    <Button variant="secondary" className="h-11 import-interactive" onClick={() => setActiveTab("quality")}>质量报告</Button>
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}

          {statusQuery.isError ? (
            <div role="alert" className="m-4 flex items-start gap-2.5 rounded-xl border border-[rgba(196,77,77,0.28)] import-feedback-in bg-[var(--color-danger-light)] px-4 py-3 text-xs leading-5 text-[var(--color-danger)] sm:m-5"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />无法获取导入进度，请刷新重试。</div>
          ) : null}
        </section>
      ) : null}

      {activeTab === "quality" ? (
        <section className="overflow-hidden rounded-2xl border border-[var(--color-border-light)] bg-[rgba(254,252,249,0.82)] shadow-[var(--shadow-card)] import-panel-swap">
          <ImportPanelHeader
            title="质量报告"
            description={status?.quality_report ? `批次 ${status.batch_id || "—"} · 共 ${status.quality_report.total_questions ?? "—"} 题` : "导入完成后自动汇总风险、结构与性能指标。"}
          />

          {!status?.quality_report ? (
            <div className="flex min-h-[430px] items-center justify-center px-6 py-14">
              <div className="max-w-sm text-center import-panel-swap">
                <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] text-[var(--color-primary-dark)] import-soft-pop"><FileText className="h-6 w-6" strokeWidth={1.6} aria-hidden="true" /></div>
                <p className="mt-4 text-sm font-semibold text-[var(--ink)]">暂无质量报告</p>
                <p className="mt-1.5 text-xs leading-5 text-[var(--color-text-hint)]">{pipelineId ? "任务完成后会在这里生成质量分析。" : "先提交导入任务，完成后即可查看风险与质量指标。"}</p>
                {!pipelineId ? <Button variant="secondary" className="mt-5 h-11 import-interactive" onClick={() => setActiveTab("upload")}>前往上传</Button> : null}
              </div>
            </div>
          ) : null}

          {status?.quality_report ? (
            <div className="import-panel-swap">
              <div className="grid grid-cols-2 divide-x divide-y divide-[var(--color-border-light)] border-b border-[var(--color-border-light)] bg-white/55 sm:grid-cols-4 sm:divide-y-0">
                <ImportMetric label="总题数" value={status.quality_report.total_questions} />
                <ImportMetric label="低风险" value={status.quality_report.low_risk ?? "—"} tone="success" />
                <ImportMetric label="需检查" value={status.quality_report.medium_risk ?? "—"} tone="warning" />
                <ImportMetric label="高风险" value={status.quality_report.high_risk ?? "—"} tone="danger" />
              </div>

              <div className="space-y-5 p-4 sm:p-5">
                <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-[var(--color-border-light)] bg-[var(--color-border-light)] sm:grid-cols-4 import-panel-swap">
                  {status.quality_report.ai_answer_count !== undefined ? <div className="bg-white/80 p-4"><p className="text-[10px] font-medium text-[var(--color-text-hint)]">AI 答案</p><p className="mt-1.5 text-lg font-semibold tabular-nums text-[var(--ink)]">{status.quality_report.ai_answer_count}</p></div> : null}
                  {status.quality_report.math_image_count !== undefined ? <div className="bg-white/80 p-4"><p className="text-[10px] font-medium text-[var(--color-text-hint)]">公式截图</p><p className="mt-1.5 text-lg font-semibold tabular-nums text-[var(--ink)]">{status.quality_report.math_image_count}</p></div> : null}
                  {status.quality_report.table_markdown_count !== undefined ? <div className="bg-white/80 p-4"><p className="text-[10px] font-medium text-[var(--color-text-hint)]">表格</p><p className="mt-1.5 text-lg font-semibold tabular-nums text-[var(--ink)]">{status.quality_report.table_markdown_count}</p></div> : null}
                  {status.quality_report.estimated_manual_check_rate !== undefined ? <div className="bg-white/80 p-4"><p className="text-[10px] font-medium text-[var(--color-text-hint)]">人工检查率</p><p className={cn("mt-1.5 text-lg font-semibold tabular-nums", status.quality_report.estimated_manual_check_rate > 0.4 ? "text-[var(--color-text-primary)]" : "text-[var(--ink)]")}>{(status.quality_report.estimated_manual_check_rate * 100).toFixed(0)}%</p></div> : null}
                </div>

                {status.quality_report.performance_summary ? (
                  <details className="group overflow-hidden rounded-xl border border-[var(--color-border-light)] bg-white/60">
                    <summary className="flex min-h-12 cursor-pointer items-center justify-between px-4 text-xs font-semibold text-[var(--ink)] import-interactive hover:bg-white/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--color-primary)]"><span>性能概览</span><ChevronDown className="h-4 w-4 text-[var(--color-text-hint)] import-chevron group-open:rotate-180" aria-hidden="true" /></summary>
                    <div className="grid gap-px border-t border-[var(--color-border-light)] bg-[var(--color-border-light)] sm:grid-cols-3 import-details-body">
                      <div className="bg-white/80 p-4 text-xs"><span className="text-[var(--color-text-hint)]">总耗时</span><strong className="ml-2 text-[var(--ink)]">{(status.quality_report.performance_summary.total_duration_ms / 1000).toFixed(1)}s</strong></div>
                      <div className="bg-white/80 p-4 text-xs"><span className="text-[var(--color-text-hint)]">AI 调用</span><strong className="ml-2 text-[var(--ink)]">{status.quality_report.performance_summary.total_ai_calls} 次</strong></div>
                      <div className="bg-white/80 p-4 text-xs"><span className="text-[var(--color-text-hint)]">Token</span><strong className="ml-2 text-[var(--ink)]">{status.quality_report.performance_summary.total_tokens_used}</strong></div>
                      <div className="bg-white/80 p-4 text-xs"><span className="text-[var(--color-text-hint)]">OCR 缓存命中</span><strong className="ml-2 text-[var(--ink)]">{(status.quality_report.performance_summary.cache_hit_rate * 100).toFixed(0)}%</strong></div>
                      <div className="bg-white/80 p-4 text-xs sm:col-span-2"><span className="text-[var(--color-text-hint)]">最慢阶段</span><strong className="ml-2 text-[var(--ink)]">{status.quality_report.performance_summary.slowest_stage} · {(status.quality_report.performance_summary.slowest_duration_ms / 1000).toFixed(1)}s</strong></div>
                    </div>
                  </details>
                ) : null}

                {status.batch_id ? (
                  <div className="flex flex-wrap justify-end gap-2 border-t border-[var(--color-border-light)] pt-4">
                    <a className="inline-flex h-11 items-center gap-2 rounded-xl border border-[rgba(196,77,77,0.28)] bg-[var(--color-danger-light)] px-4 text-xs font-semibold text-[var(--color-danger)] import-interactive hover:border-[var(--color-danger)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-danger)] focus-visible:ring-offset-2" href={`/imports/review?batch_id=${encodeURIComponent(status.batch_id)}&risk_filter=high`}><AlertCircle className="h-4 w-4" aria-hidden="true" />查看高风险题</a>
                    <a className="inline-flex h-11 items-center gap-2 rounded-xl border border-[var(--color-border)] bg-white px-4 text-xs font-semibold text-[var(--color-text-secondary)] import-interactive hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] focus-visible:ring-offset-2" href={`/imports/review?batch_id=${encodeURIComponent(status.batch_id)}`}><FileText className="h-4 w-4" aria-hidden="true" />进入审核区</a>
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

"use client";

import { useCallback, useEffect, useId, useRef, useState, type DragEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, ClipboardCheck, Images, RefreshCw, UploadCloud, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { apiRequest, getApiAccessToken, toQuery } from "@/lib/api/client";
import { connectSSE } from "@/lib/api/sse";
import type { BatchImageJobStatusResponse, BatchImageUploadResponse, BatchImageReparseResponse, TraceEvent } from "@/lib/api/types";
import {
  IMAGE_MIME,
  MAX_FILES,
  DEFAULT_CONCURRENCY,
  dedupeFiles,
  taskProgress,
  computeBatchStats,
} from "@/lib/batch-image-utils";
import { AiModelConfigBanner } from "@/components/ai-model-config-banner";
import { useImportConfig } from "../hooks/useImportConfig";
import { OcrModeSelector } from "../components/ocr-mode-selector";
import { ImportMetric, ImportPanelHeader, ImportProgressBar, ImportWorkspaceHeader } from "../components/import-workspace";
import { ImportToast } from "../components/import-toast";

const ACCEPT = ".jpg,.jpeg,.png,.webp";
// ── Types ────────────────────────────────────────────────────

type QueuePhase = "idle" | "uploading" | "polling" | "done";

type MessageInfo = {
  text: string;
  type: "success" | "error" | "info";
};

type ImageTask = {
  id: string;            // `img_${ts}_${seq}`
  seq: number;
  batchId: string;
  imageId: string;
  requestId: string;
  file: File;
  status: "pending" | "uploading" | "processing" | "succeeded" | "failed";
  jobId: string | null;
  jobStatus: BatchImageJobStatusResponse | null;
  traceEvents: TraceEvent[];
  questionCount: number;
  errorMessage: string | null;
  startedAt: number;
  finishedAt: number | null;
};

// ── Helpers ───────────────────────────────────────────────────

// ── Component ─────────────────────────────────────────────────

export default function BatchImagePage() {
  const [files, setFiles] = useState<File[]>([]);
  const [subjectId, setSubjectId] = useState("");
  const [subjectOptions, setSubjectOptions] = useState<Array<{id: number; code: string; name: string}>>([]);
  useEffect(() => {
    apiRequest<Array<{id: number; code: string; name: string; path: string; level: number}>>("/imports/subject-options")
      .then(setSubjectOptions)
      .catch(() => {});
  }, []);
  const [concurrency, setConcurrency] = useState(DEFAULT_CONCURRENCY);
  const [message, setMessage] = useState<MessageInfo | null>(null);
  const { ocrMode, setOcrMode } = useImportConfig();
  const [dragActive, setDragActive] = useState(false);
  const fileInputId = useId();
  const queryClient = useQueryClient();

  // Queue state
  const [imageTasks, setImageTasks] = useState<ImageTask[]>([]);
  const [queuePhase, setQueuePhase] = useState<QueuePhase>("idle");
  const [selectOpen, setSelectOpen] = useState(false);
  const selectRef = useRef<HTMLDivElement>(null);
  const [subjectSelectOpen, setSubjectSelectOpen] = useState(false);
  const subjectSelectRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  // ── SSE streaming (replaces per-image polling) ────────────

  const abortSourcesRef = useRef<Map<string, () => void>>(new Map());
  const pollTimersRef = useRef<Map<string, ReturnType<typeof setInterval>>>(new Map());
  const doneRef = useRef(false); // guard: completion message shown once

  // Always tear down long-lived requests when leaving the page. This avoids
  // stale SSE/watchdog callbacks updating an unmounted batch-import screen.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      for (const [, close] of abortSourcesRef.current) close();
      abortSourcesRef.current.clear();
      for (const [, timer] of pollTimersRef.current) clearInterval(timer);
      pollTimersRef.current.clear();
    };
  }, []);

  // Watch for all-tasks-done to show summary + invalidate review queue
  useEffect(() => {
    if (doneRef.current || imageTasks.length === 0) return;
    const done = imageTasks.every(
      (t) => t.status === "succeeded" || t.status === "failed",
    );
    if (!done) return;
    doneRef.current = true;

    const succeeded = imageTasks.filter((t) => t.status === "succeeded").length;
    const failed = imageTasks.filter((t) => t.status === "failed").length;
    const totalQ = imageTasks.reduce((s, t) => s + t.questionCount, 0);
    setQueuePhase("done");
    setMessage({
      text: `导入完成：共 ${imageTasks.length} 张，成功 ${succeeded} 张（${totalQ} 道题）${failed > 0 ? `，失败 ${failed} 张` : ""}`,
      type: failed > 0 && succeeded === 0 ? "error" : "success",
    });
    queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
  }, [imageTasks, queryClient]);

  // ── Queue Processing ────────────────────────────────────────

  const startQueue = useCallback(async () => {
    if (files.length === 0) {
      setMessage({ text: "请先选择要导入的图片", type: "error" });
      return;
    }

    const filesToProcess = [...files];
    const maxConc = Math.max(1, Math.min(4, Number(concurrency) || 2));
    const batchId = `batch_${Date.now()}`;
    const requestId = `req_${batchId}`;
    const now = Date.now();
    doneRef.current = false;

    setFiles([]);
    const initialTasks: ImageTask[] = filesToProcess.map((file, idx) => ({
      id: `img_${now}_${idx + 1}`,
      seq: idx + 1,
      batchId,
      imageId: `img_${batchId}_${idx + 1}`,
      requestId,
      file,
      status: "uploading",
      jobId: null,
      jobStatus: null,
      traceEvents: [],
      questionCount: 0,
      errorMessage: null,
      startedAt: Date.now(),
      finishedAt: null,
    }));

    setImageTasks(initialTasks);
    setQueuePhase("uploading");
    setMessage(null);

    const abortCtrl = new AbortController();
    abortRef.current = abortCtrl;

    try {
      // The backend endpoint is already a true batch API.  Submit all images in
      // one request so its semaphore/concurrency control, merge logic and one
      // SSE stream can be used.  The previous frontend created one backend job
      // per image, which multiplied queue/SSE overhead and defeated batch merge.
      const formData = new FormData();
      for (const file of filesToProcess) formData.append("files", file);

      const qs = toQuery({
        subject_id: subjectId ? Number(subjectId) : undefined,
        concurrency: maxConc,
        enable_ai_repair: true,
        confidence_threshold: "0.6",
        batch_fast_mode: true,
        ocr_mode: ocrMode,
        batch_id: batchId,
        request_id: requestId,
      });

      const result = await apiRequest<BatchImageUploadResponse>(
        `/imports/batch-image/upload${qs}`,
        { method: "POST", body: formData, signal: abortCtrl.signal },
      );

      setQueuePhase("polling");
      setMessage({
        text: `全部 ${filesToProcess.length} 张图片已提交，正在识别中...`,
        type: "info",
      });
      setImageTasks((prev) =>
        prev.map((task) => ({ ...task, status: "pending" as const, jobId: result.job_id })),
      );

      let terminal = false;
      const syncJobStatus = async () => {
        if (terminal || abortCtrl.signal.aborted) return;
        try {
          const status = await apiRequest<BatchImageJobStatusResponse>(
            `/imports/batch-image/${result.job_id}`,
            { signal: abortCtrl.signal },
          );

          const itemsBySeq = new Map(status.items.map((item) => [item.seq, item]));
          setImageTasks((prev) =>
            prev.map((task) => {
              const item = itemsBySeq.get(task.seq);
              if (!item) return { ...task, jobStatus: status };
              const nextStatus: ImageTask["status"] =
                item.status === "succeeded" ? "succeeded"
                  : item.status === "failed" ? "failed"
                    : item.status === "processing" ? "processing"
                      : "pending";
              return {
                ...task,
                status: nextStatus,
                jobStatus: status,
                questionCount: item.question_count || 0,
                errorMessage: item.error_message,
                finishedAt:
                  nextStatus === "succeeded" || nextStatus === "failed"
                    ? (task.finishedAt || Date.now())
                    : null,
              };
            }),
          );

          if (["completed", "completed_with_warnings", "failed"].includes(status.status)) {
            terminal = true;
            const timer = pollTimersRef.current.get(result.job_id);
            if (timer) clearInterval(timer);
            pollTimersRef.current.delete(result.job_id);
            abortSourcesRef.current.get(result.job_id)?.();
            abortSourcesRef.current.delete(result.job_id);
          }
        } catch {
          // SSE remains primary; watchdog polling is intentionally best-effort.
        }
      };

      const seenSeqs = new Set<number>();
      const stream = connectSSE(
        `/imports/batch-image/${result.job_id}/stream`,
        getApiAccessToken(),
        {
          onTrace: (event) => {
            if (seenSeqs.has(event.seq)) return;
            seenSeqs.add(event.seq);
            if (!event.item_seq) return;
            setImageTasks((prev) =>
              prev.map((task) =>
                task.seq === event.item_seq
                  ? {
                      ...task,
                      status: task.status === "pending" ? "processing" : task.status,
                      traceEvents: [...task.traceEvents, event],
                    }
                  : task,
              ),
            );
          },
          onDone: () => { void syncJobStatus(); },
          onError: () => { void syncJobStatus(); },
        },
      );
      abortSourcesRef.current.set(result.job_id, stream.close);

      // Safety watchdog: backend DB is the source of truth.  This prevents a
      // Redis/SSE disconnect from leaving the page forever at “识别中 / 0%”.
      await syncJobStatus();
      if (!terminal) {
        const timer = setInterval(() => { void syncJobStatus(); }, 2500);
        pollTimersRef.current.set(result.job_id, timer);
      }
    } catch (err: unknown) {
      if (abortCtrl.signal.aborted) return;
      const msg = err instanceof Error ? err.message : String(err);
      setImageTasks((prev) =>
        prev.map((task) => ({
          ...task,
          status: "failed" as const,
          errorMessage: msg,
          finishedAt: Date.now(),
        })),
      );
      setQueuePhase("done");
      setMessage({ text: msg, type: "error" });
    }
  }, [files, subjectId, concurrency, ocrMode]);

  const resetQueue = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    // Close all SSE connections + watchdog polling timers
    for (const [, close] of abortSourcesRef.current) close();
    abortSourcesRef.current.clear();
    for (const [, timer] of pollTimersRef.current) clearInterval(timer);
    pollTimersRef.current.clear();
    doneRef.current = false;
    setImageTasks([]);
    setQueuePhase("idle");
    setMessage(null);
  }, []);

  // ── Reparse mutation ─────────────────────────────────────────

  const reparseMutation = useMutation({
    mutationFn: (itemId: number) =>
      apiRequest<BatchImageReparseResponse>(`/imports/batch-image/items/${itemId}/reparse`, {
        method: "POST",
      }),
    onSuccess: (result) => {
      setMessage({
        text: result.status === "succeeded"
          ? `第 ${result.item_id} 项重新解析成功，生成 ${result.question_count} 道题`
          : `第 ${result.item_id} 项重新解析未成功：${result.error_message || "未知原因"}`,
        type: result.status === "succeeded" ? "success" : "error",
      });
    },
    onError: (error) => {
      setMessage({ text: error instanceof Error ? error.message : "重新解析失败，请稍后重试。", type: "error" });
    },
  });

  // ── Click-outside for concurrency dropdown ───────────────────

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (selectRef.current && !selectRef.current.contains(e.target as Node)) {
        setSelectOpen(false);
      }
      if (subjectSelectRef.current && !subjectSelectRef.current.contains(e.target as Node)) {
        setSubjectSelectOpen(false);
      }
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setSelectOpen(false);
        setSubjectSelectOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  // ── Computed aggregate values ────────────────────────────────

  const totalImages = imageTasks.length;
  const { succeededCount, failedCount, totalQuestions, uploadingCount, processingCount, totalProgress: progressPct } = computeBatchStats(imageTasks);
  const isJobActive = queuePhase !== "idle";

  // ── Drag / drop / paste ──────────────────────────────────────

  const addFiles = useCallback((incoming: FileList | File[] | null) => {
    if (!incoming) return;
    const list = Array.from(incoming);
    if (list.length === 0) return;
    setFiles((prev) => dedupeFiles(prev, list));
  }, []);

  const removeFile = useCallback((index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const clearFiles = useCallback(() => setFiles([]), []);

  useEffect(() => {
    function onPaste(event: ClipboardEvent) {
      if (isJobActive) return;
      const items = event.clipboardData?.files;
      if (items && items.length > 0) {
        addFiles(items);
        setMessage({ text: `已从剪贴板添加 ${items.length} 张图片`, type: "info" });
      }
    }
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [addFiles, isJobActive]);

  const onDragOver = useCallback(
    (event: DragEvent) => {
      event.preventDefault();
      if (!isJobActive) setDragActive(true);
    },
    [isJobActive],
  );

  const onDragLeave = useCallback((event: DragEvent) => {
    event.preventDefault();
    setDragActive(false);
  }, []);

  const onDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault();
      setDragActive(false);
      if (isJobActive) return;
      addFiles(event.dataTransfer?.files ?? null);
    },
    [addFiles, isJobActive],
  );

  // ── Render ───────────────────────────────────────────────────

  const renderStatusBadge = (task: ImageTask) => {
    const base = "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold";
    if (task.status === "failed") {
      return <span className={`${base} border-[rgba(196,77,77,0.25)] bg-[var(--color-danger-light)] text-[var(--color-danger)]`}>失败</span>;
    }
    if (task.status === "succeeded") {
      return <span className={`${base} border-[rgba(91,140,91,0.25)] bg-[var(--color-success-light)] text-[var(--color-success)]`}>成功 · {task.questionCount} 题</span>;
    }
    if (task.status === "processing") {
      return (
        <span className={`${base} border-[rgba(196,154,107,0.3)] bg-[var(--color-warning-light)] text-[var(--color-text-primary)]`}>
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-warning)] import-status-active" aria-hidden="true" />
          识别中
        </span>
      );
    }
    if (task.status === "uploading") {
      return <span className={`${base} border-[rgba(74,111,138,0.24)] bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]`}>上传中</span>;
    }
    return <span className={`${base} border-[var(--color-border)] bg-white/70 text-[var(--color-text-secondary)]`}>等待中</span>;
  };

  const concurrencyOptions = [
    { value: "1", label: "1", tag: "稳定" },
    { value: "2", label: "2", tag: "推荐" },
    { value: "3", label: "3", tag: null },
    { value: "4", label: "4", tag: "上限" },
  ];

  const phaseLabel = queuePhase === "done"
    ? failedCount > 0 && succeededCount === 0 ? "全部失败" : "已完成"
    : queuePhase === "uploading" ? "上传中" : queuePhase === "polling" ? "识别中" : "待提交";

  const phaseTone = queuePhase === "done"
    ? failedCount > 0 && succeededCount === 0 ? "danger" : "success"
    : queuePhase === "idle" ? "neutral" : "warning";

  return (
    <div className="space-y-6 pb-4">
      <ImportWorkspaceHeader
        icon={Images}
        title="批量图片导题"
        description="面向连续截图与扫描题目的批处理工作台。集中配置 OCR、科目与并发数，并在同一视图追踪每张图片的识别状态与事件轨迹。"
        meta={
          <div className="inline-flex h-9 items-center gap-2 rounded-full border border-[var(--color-border)] bg-white/70 px-3 text-xs text-[var(--color-text-secondary)]">
            <span className="font-mono tabular-nums">0–{MAX_FILES}</span>
            <span className="text-[var(--color-text-hint)]">张 / 批</span>
          </div>
        }
      />

      <AiModelConfigBanner />

      <ImportToast
        message={message?.text ?? null}
        tone={message?.type ?? "info"}
        onDismiss={() => setMessage(null)}
      />

      <section className="overflow-hidden rounded-2xl border border-[var(--color-border-light)] bg-[rgba(254,252,249,0.82)] shadow-[var(--shadow-card)] import-enter" style={{ animationDelay: "55ms" }}>
        <ImportPanelHeader
          title="识别工作台"
          description="文件选择、识别参数与任务进度保持在一个操作上下文中。"
          trailing={
            <span className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold",
              phaseTone === "success" && "border-[rgba(91,140,91,0.25)] bg-[var(--color-success-light)] text-[var(--color-success)]",
              phaseTone === "danger" && "border-[rgba(196,77,77,0.25)] bg-[var(--color-danger-light)] text-[var(--color-danger)]",
              phaseTone === "warning" && "border-[rgba(196,154,107,0.3)] bg-[var(--color-warning-light)] text-[var(--color-text-primary)]",
              phaseTone === "neutral" && "border-[var(--color-border)] bg-white/70 text-[var(--color-text-secondary)]",
            )}>
              <span className={cn(
                "h-1.5 w-1.5 rounded-full",
                phaseTone === "success" && "bg-[var(--color-success)]",
                phaseTone === "danger" && "bg-[var(--color-danger)]",
                phaseTone === "warning" && "import-status-active bg-[var(--color-warning)]",
                phaseTone === "neutral" && "bg-[var(--color-text-hint)]",
              )} aria-hidden="true" />
              {phaseLabel}
            </span>
          }
        />

        <div className="grid min-h-[590px] lg:grid-cols-[300px_minmax(0,1fr)]">
          <aside className="flex min-w-0 flex-col gap-5 border-b border-[var(--color-border-light)] bg-[rgba(239,235,229,0.25)] p-4 sm:p-5 lg:border-b-0 lg:border-r">
            <label htmlFor={fileInputId} className="block">
              <div
                onDragOver={onDragOver}
                onDragLeave={onDragLeave}
                onDrop={onDrop}
                className={cn(
                  "relative flex min-h-40 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed px-4 py-5 text-center transition-[border-color,background-color,box-shadow] import-interactive",
                  (dragActive || files.length > 0) && "import-drop-active",
                  isJobActive
                    ? "cursor-not-allowed border-[var(--color-border)] bg-[var(--color-bg-input)] opacity-60"
                    : dragActive || files.length > 0
                      ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] shadow-[inset_0_0_0_1px_rgba(74,111,138,0.08)]"
                      : "border-[var(--color-border)] bg-white/60 hover:border-[var(--color-primary)] hover:bg-white",
                )}
              >
                <div className="grid h-11 w-11 place-items-center rounded-xl border border-[rgba(74,111,138,0.16)] bg-white/80 text-[var(--color-primary-dark)] import-drop-icon">
                  <Images className="h-5 w-5" strokeWidth={1.7} aria-hidden="true" />
                </div>
                <p className="mt-3 text-sm font-semibold text-[var(--ink)]">{files.length > 0 ? `${files.length} 张图片已就绪` : "添加题目图片"}</p>
                <p className="mt-1 text-xs leading-5 text-[var(--color-text-hint)]">拖拽、粘贴或点击选择 JPG / PNG / WebP</p>
                <input
                  id={fileInputId}
                  type="file"
                  multiple
                  accept={ACCEPT}
                  disabled={isJobActive}
                  className="absolute inset-0 cursor-pointer opacity-0 disabled:cursor-not-allowed"
                  onChange={(event) => { addFiles(event.target.files); event.target.value = ""; }}
                />
              </div>
            </label>

            {files.length > 0 && queuePhase === "idle" ? (
              <div>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <span className="text-xs font-semibold text-[var(--color-text-secondary)]">待上传文件</span>
                  <button type="button" disabled={isJobActive} onClick={clearFiles} className="min-h-11 rounded-lg px-2 text-xs font-semibold text-[var(--color-text-hint)] import-interactive hover:bg-white hover:text-[var(--color-danger)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] disabled:opacity-40">
                    清空
                  </button>
                </div>
                <div className="max-h-32 overflow-y-auto rounded-xl border border-[var(--color-border-light)] bg-white/55">
                  {files.map((file, index) => (
                    <div key={`${file.name}_${file.size}_${index}`} className="flex min-h-11 items-center gap-2 border-b border-[var(--color-border-light)] px-3 last:border-b-0 import-list-item" style={{ animationDelay: `${Math.min(index, 8) * 24}ms` }}>
                      <span className="min-w-0 flex-1 truncate text-[11px] text-[var(--color-text-secondary)]" title={file.name}>{file.name}</span>
                      <button
                        type="button"
                        disabled={isJobActive}
                        onClick={() => removeFile(index)}
                        className="grid h-11 w-11 shrink-0 place-items-center rounded-lg text-[var(--color-text-hint)] import-interactive hover:bg-[var(--color-danger-light)] hover:text-[var(--color-danger)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] disabled:opacity-40"
                        aria-label={`移除 ${file.name}`}
                        title="移除文件"
                      >
                        <X className="h-3.5 w-3.5" aria-hidden="true" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="space-y-4 border-t border-[var(--color-border-light)] pt-4">
              <div className="space-y-1.5">
                <span className="text-xs font-semibold text-[var(--color-text-secondary)]">科目</span>
                <div className="relative" ref={subjectSelectRef}>
                  <button
                    type="button"
                    disabled={isJobActive}
                    aria-haspopup="listbox"
                    aria-expanded={subjectSelectOpen}
                    onClick={() => setSubjectSelectOpen((prev) => !prev)}
                    className={cn(
                      "flex h-11 w-full items-center justify-between gap-2 rounded-xl border px-3 text-sm outline-none transition-[border-color,background-color,box-shadow]",
                      isJobActive ? "cursor-not-allowed border-[var(--color-border)] bg-[var(--color-bg-input)] opacity-60"
                        : subjectSelectOpen ? "border-[var(--color-primary)] bg-white ring-4 ring-[rgba(91,123,154,0.12)]"
                          : "border-[var(--color-border)] bg-white/75 hover:border-[var(--color-primary)]",
                    )}
                  >
                    <span className={cn("truncate", subjectId ? "font-semibold text-[var(--ink)]" : "text-[var(--color-text-hint)]")}>
                      {subjectId ? (subjectOptions.find((s) => String(s.id) === subjectId)?.name || subjectId) : "选择科目（可选）"}
                    </span>
                    <ChevronDown className={cn("h-4 w-4 shrink-0 text-[var(--color-text-hint)] import-chevron", subjectSelectOpen && "rotate-180")} aria-hidden="true" />
                  </button>
                  {subjectSelectOpen ? (
                    <div role="listbox" className="absolute left-0 right-0 top-full z-50 mt-1 max-h-56 import-popover overflow-y-auto rounded-xl border border-[var(--color-border-light)] bg-[var(--color-bg-card)] p-1 shadow-[var(--shadow-floating)]">
                      <button type="button" role="option" aria-selected={!subjectId} onClick={() => { setSubjectId(""); setSubjectSelectOpen(false); }} className={cn("flex min-h-11 w-full items-center justify-between gap-2 rounded-lg px-3 text-left text-xs import-interactive", !subjectId ? "bg-[var(--color-primary-light)] font-semibold text-[var(--color-primary-dark)]" : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-input)]")}>
                        未指定科目
                        {!subjectId ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : null}
                      </button>
                      {subjectOptions.map((s) => (
                        <button key={s.id} type="button" role="option" aria-selected={subjectId === String(s.id)} onClick={() => { setSubjectId(String(s.id)); setSubjectSelectOpen(false); }} className={cn("flex min-h-11 w-full items-center justify-between gap-2 rounded-lg px-3 text-left text-xs import-interactive", subjectId === String(s.id) ? "bg-[var(--color-primary-light)] font-semibold text-[var(--color-primary-dark)]" : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-input)]")}>
                          <span className="truncate">{s.name}</span>
                          {subjectId === String(s.id) ? <Check className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /> : null}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>

              <div className="space-y-1.5">
                <span className="text-xs font-semibold text-[var(--color-text-secondary)]">并发数</span>
                <div className="relative" ref={selectRef}>
                  <button
                    type="button"
                    disabled={isJobActive}
                    aria-haspopup="listbox"
                    aria-expanded={selectOpen}
                    onClick={() => setSelectOpen((prev) => !prev)}
                    className={cn(
                      "flex h-11 w-full items-center justify-between gap-2 rounded-xl border px-3 text-sm outline-none transition-[border-color,background-color,box-shadow]",
                      isJobActive ? "cursor-not-allowed border-[var(--color-border)] bg-[var(--color-bg-input)] opacity-60"
                        : selectOpen ? "border-[var(--color-primary)] bg-white ring-4 ring-[rgba(91,123,154,0.12)]"
                          : "border-[var(--color-border)] bg-white/75 hover:border-[var(--color-primary)]",
                    )}
                  >
                    <span className="flex items-center gap-2">
                      <strong className="text-[var(--ink)]">{concurrency}</strong>
                      {concurrencyOptions.find((o) => o.value === concurrency)?.tag ? <span className="rounded-full bg-[var(--color-primary-light)] px-2 py-0.5 text-[10px] font-semibold text-[var(--color-primary-dark)]">{concurrencyOptions.find((o) => o.value === concurrency)?.tag}</span> : null}
                    </span>
                    <ChevronDown className={cn("h-4 w-4 text-[var(--color-text-hint)] import-chevron", selectOpen && "rotate-180")} aria-hidden="true" />
                  </button>
                  {selectOpen ? (
                    <div role="listbox" className="absolute left-0 right-0 top-full z-50 mt-1 overflow-hidden import-popover rounded-xl border border-[var(--color-border-light)] bg-[var(--color-bg-card)] p-1 shadow-[var(--shadow-floating)]">
                      {concurrencyOptions.map((opt) => (
                        <button key={opt.value} type="button" role="option" aria-selected={concurrency === opt.value} onClick={() => { setConcurrency(opt.value); setSelectOpen(false); }} className={cn("flex min-h-11 w-full items-center justify-between gap-2 rounded-lg px-3 text-xs import-interactive", concurrency === opt.value ? "bg-[var(--color-primary-light)] font-semibold text-[var(--color-primary-dark)]" : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-input)]")}>
                          <span className="flex items-center gap-2"><strong>{opt.label}</strong>{opt.tag ? <span className="text-[10px] text-[var(--color-text-hint)]">{opt.tag}</span> : null}</span>
                          {concurrency === opt.value ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : null}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>

              <OcrModeSelector value={ocrMode} onChange={setOcrMode} disabled={isJobActive} />
            </div>

            <div className="mt-auto border-t border-[var(--color-border-light)] pt-4">
              {queuePhase === "done" ? (
                <Button onClick={resetQueue} className="h-11 w-full import-interactive" variant="secondary">
                  <RefreshCw className="h-4 w-4" aria-hidden="true" />重新导入
                </Button>
              ) : (
                <div className="flex gap-2">
                  {queuePhase === "polling" ? (
                    <Button onClick={resetQueue} variant="secondary" className="h-11 w-11 p-0 import-interactive" aria-label="停止并重置任务" title="停止并重置">
                      <X className="h-4 w-4" aria-hidden="true" />
                    </Button>
                  ) : null}
                  <Button disabled={files.length === 0 || queuePhase !== "idle"} onClick={() => { if (queuePhase === "idle") startQueue(); }} className="h-11 flex-1 import-interactive group">
                    <UploadCloud className="h-4 w-4 transition-transform duration-200 group-hover:-translate-y-0.5 motion-reduce:transform-none" aria-hidden="true" />
                    {queuePhase === "uploading" ? "上传中" : queuePhase === "polling" ? "识别中" : files.length > 0 ? `开始导入 · ${files.length}` : "开始导入"}
                  </Button>
                </div>
              )}
            </div>
          </aside>

          <div className="min-w-0 bg-white/30">
            {queuePhase === "idle" && imageTasks.length === 0 ? (
              <div className="flex min-h-[590px] items-center justify-center px-6 py-14 import-panel-swap">
                <div className="max-w-md text-center">
                  <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-input)] text-[var(--color-primary-dark)] import-soft-pop">
                    <UploadCloud className="h-6 w-6" strokeWidth={1.6} aria-hidden="true" />
                  </div>
                  <p className="mt-4 text-sm font-semibold text-[var(--ink)]">等待批量任务</p>
                  <p className="mt-1.5 text-xs leading-5 text-[var(--color-text-hint)]">添加图片并设置识别参数后开始导入。提交后，这里会实时显示总体进度、单图状态与处理轨迹。</p>
                  <div className="mt-5 grid grid-cols-3 divide-x divide-[var(--color-border-light)] border-y border-[var(--color-border-light)] py-2.5 text-[11px] text-[var(--color-text-secondary)]">
                    <span>上传</span><span>OCR / AI</span><span>待审核</span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="p-4 sm:p-5 import-panel-swap">
                <div className="grid grid-cols-2 divide-x divide-y divide-[var(--color-border-light)] overflow-hidden rounded-xl border border-[var(--color-border-light)] bg-white/60 sm:grid-cols-3 xl:grid-cols-6 xl:divide-y-0">
                  <ImportMetric label="总图片" value={totalImages} />
                  <ImportMetric label="上传中" value={uploadingCount} tone={uploadingCount > 0 ? "primary" : "neutral"} />
                  <ImportMetric label="识别中" value={processingCount} tone={processingCount > 0 ? "warning" : "neutral"} />
                  <ImportMetric label="成功" value={succeededCount} tone={succeededCount > 0 ? "success" : "neutral"} />
                  <ImportMetric label="失败" value={failedCount} tone={failedCount > 0 ? "danger" : "neutral"} />
                  <ImportMetric label="识别题目" value={totalQuestions} tone={totalQuestions > 0 ? "primary" : "neutral"} />
                </div>

                <div className="mt-5 rounded-xl border border-[var(--color-border-light)] bg-white/60 px-4 py-3.5">
                  <div className="flex items-center justify-between gap-4 text-xs">
                    <span className="font-semibold text-[var(--color-text-secondary)]">总体进度</span>
                    <span className="font-mono font-semibold tabular-nums text-[var(--ink)]">{progressPct}%</span>
                  </div>
                  <ImportProgressBar
                    value={progressPct}
                    label="总体进度"
                    active={queuePhase === "uploading" || queuePhase === "polling"}
                    tone={queuePhase === "done" && failedCount === totalImages && totalImages > 0 ? "danger" : queuePhase === "done" ? "success" : "primary"}
                    className="mt-2.5"
                  />
                </div>

                <section className="mt-5 overflow-hidden rounded-xl border border-[var(--color-border-light)] bg-white/65">
                  <ImportPanelHeader title="任务明细" description={`${imageTasks.length} 个图片任务 · 按提交顺序展示`} />
                  <div className="max-h-[430px] overflow-y-auto">
                    {imageTasks.map((task) => (
                      <article key={task.id} className={cn("border-b border-[var(--color-border-light)] last:border-b-0 import-list-item import-interactive hover:bg-white/55", task.status === "failed" && "bg-[rgba(196,77,77,0.025)]")} style={{ animationDelay: `${Math.min(task.seq - 1, 8) * 26}ms` }}>
                        <div className="flex min-h-14 items-center gap-3 px-4 py-2.5">
                          <span className="w-7 shrink-0 font-mono text-[10px] tabular-nums text-[var(--color-text-hint)]">#{task.seq}</span>
                          <div className="min-w-0 flex-1">
                            <span className="block truncate text-xs font-medium text-[var(--ink)]" title={task.file.name}>{task.file.name}</span>
                            {(task.status === "uploading" || task.status === "processing" || task.status === "pending") ? (
                              <ImportProgressBar value={taskProgress(task)} label={`图片 ${task.seq} 处理进度`} active className="mt-1.5 h-1" />
                            ) : null}
                          </div>
                          {renderStatusBadge(task)}
                        </div>
                        {task.traceEvents.length > 0 ? (
                          <div className="border-t border-[var(--color-border-light)] bg-[rgba(239,235,229,0.24)] px-4 py-2.5 import-panel-swap">
                            <div className="space-y-1.5">
                              {task.traceEvents.map((ev, idx) => (
                                <div key={idx} className="grid grid-cols-[52px_10px_minmax(0,1fr)_auto] items-center gap-2 text-[10px] leading-5">
                                  <span className="truncate font-mono text-[var(--color-text-hint)]">{ev.step}</span>
                                  <span className={cn("h-1.5 w-1.5 rounded-full", ev.status === "success" ? "bg-[var(--color-success)]" : ev.status === "failed" ? "bg-[var(--color-danger)]" : ev.status === "running" ? "import-status-active bg-[var(--color-warning)]" : "bg-[var(--color-text-hint)]")} aria-hidden="true" />
                                  <span className="min-w-0 truncate text-[var(--color-text-secondary)]" title={ev.message}>{ev.message}</span>
                                  {ev.duration_ms != null && ev.duration_ms > 0 ? <span className="font-mono tabular-nums text-[var(--color-text-hint)]">{ev.duration_ms}ms</span> : null}
                                </div>
                              ))}
                            </div>
                          </div>
                        ) : null}
                      </article>
                    ))}
                  </div>
                </section>

                {queuePhase === "done" && succeededCount > 0 ? (
                  <div className="mt-4 flex justify-end">
                    <a className="inline-flex h-11 items-center gap-2 rounded-xl border border-[var(--color-border)] bg-white px-4 text-xs font-semibold text-[var(--color-text-secondary)] import-interactive hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] focus-visible:ring-offset-2" href="/imports/review">
                      <ClipboardCheck className="h-4 w-4" aria-hidden="true" />前往待审核
                    </a>
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

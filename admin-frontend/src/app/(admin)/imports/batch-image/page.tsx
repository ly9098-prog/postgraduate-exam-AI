"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Check, CheckCircle2, ChevronDown, ClipboardCheck, Images, RefreshCw, Trash2, UploadCloud, X } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { apiRequest, getApiAccessToken, toQuery } from "@/lib/api/client";
import { connectSSE } from "@/lib/api/sse";
import type { BatchImageJobStatusResponse, BatchImageUploadResponse, BatchImageReparseResponse, TraceEvent } from "@/lib/api/types";
import { AiModelConfigBanner } from "@/components/ai-model-config-banner";
import { useImportConfig } from "../hooks/useImportConfig";
import { OcrModeSelector } from "../components/ocr-mode-selector";

const MAX_FILES = (() => {
  const n = Number(process.env.NEXT_PUBLIC_BATCH_IMAGE_MAX_FILES);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 100;
})();
const DEFAULT_CONCURRENCY = (() => {
  const n = Number(process.env.NEXT_PUBLIC_BATCH_IMAGE_DEFAULT_CONCURRENCY);
  return Number.isFinite(n) && n >= 1 && n <= 4 ? String(Math.floor(n)) : "2";
})();
const ACCEPT = ".jpg,.jpeg,.png,.webp";
const IMAGE_MIME = /^image\/(jpeg|png|webp)$/;

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

function dedupeFiles(existing: File[], incoming: File[]) {
  const seen = new Set(existing.map((f) => `${f.name}_${f.size}`));
  const merged = [...existing];
  for (const file of incoming) {
    const key = `${file.name}_${file.size}`;
    if (!seen.has(key) && IMAGE_MIME.test(file.type || "")) {
      seen.add(key);
      merged.push(file);
    }
  }
  return merged.slice(0, MAX_FILES);
}

function taskProgress(task: ImageTask) {
  if (task.status === "succeeded" || task.status === "failed") return 100;
  if (task.status === "uploading") return 10;
  if (task.status === "pending") return task.jobId ? 15 : 0;

  const hasPipelineSuccess = task.traceEvents.some(
    (event) => event.step === "pipeline" && event.status === "success",
  );
  if (hasPipelineSuccess) return 90;
  const hasPipelineRunning = task.traceEvents.some(
    (event) => event.step === "pipeline" && event.status === "running",
  );
  if (hasPipelineRunning) return 55;
  const hasOcrSuccess = task.traceEvents.some(
    (event) => event.step === "ocr" && event.status === "success",
  );
  if (hasOcrSuccess) return 40;
  return 20;
}

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
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // ── Computed aggregate values ────────────────────────────────

  const totalImages = imageTasks.length;
  const progressPct = totalImages > 0
    ? Math.round(imageTasks.reduce((sum, task) => sum + taskProgress(task), 0) / totalImages)
    : 0;
  const succeededCount = imageTasks.filter((t) => t.status === "succeeded").length;
  const failedCount = imageTasks.filter((t) => t.status === "failed").length;
  const totalQuestions = imageTasks.reduce((s, t) => s + t.questionCount, 0);
  const uploadingCount = imageTasks.filter((t) => t.status === "uploading").length;
  const processingCount = imageTasks.filter((t) => t.status === "processing").length;
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
    (event: React.DragEvent) => {
      event.preventDefault();
      if (!isJobActive) setDragActive(true);
    },
    [isJobActive],
  );

  const onDragLeave = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    setDragActive(false);
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      setDragActive(false);
      if (isJobActive) return;
      addFiles(event.dataTransfer?.files ?? null);
    },
    [addFiles, isJobActive],
  );

  // ── Render ───────────────────────────────────────────────────

  const renderStatusBadge = (task: ImageTask) => {
    const base = "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold transition-all duration-300 animate-rise-in";
    if (task.status === "failed") {
      return <span className={`${base} bg-red-50 text-red-700`}>失败</span>;
    }
    if (task.status === "succeeded") {
      return <span className={`${base} bg-green-50 text-green-700`}>成功 · {task.questionCount}题</span>;
    }
    if (task.status === "processing") {
      return (
        <span className={`${base} bg-amber-50 text-amber-700`}>
          <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500 align-middle" />
          识别中
        </span>
      );
    }
    if (task.status === "uploading") {
      return <span className={`${base} bg-blue-50 text-blue-700`}>上传中</span>;
    }
    return (
      <span className={`${base} bg-[var(--color-bg-input)] text-[var(--color-text-secondary)]`}>
        等待中
      </span>
    );
  };

  const concurrencyOptions = [
    { value: "1", label: "1", tag: "最稳", tagClass: "bg-amber-50 text-amber-700" },
    { value: "2", label: "2", tag: "推荐", tagClass: "bg-green-50 text-green-700" },
    { value: "3", label: "3", tag: null, tagClass: "" },
    { value: "4", label: "4", tag: "上限", tagClass: "bg-blue-50 text-blue-700" },
  ];

  return (
    <div className="space-y-6">
      <AiModelConfigBanner />

      {message ? (
        <div
          className={`animate-rise-in flex items-center gap-2.5 rounded-2xl border px-4 py-3 text-sm shadow-[var(--shadow-crisp)] ${
            message.type === "error"
              ? "border-amber-200 bg-amber-50/80 text-amber-800"
              : message.type === "success"
                ? "border-green-200 bg-green-50/80 text-green-800"
                : "border-[var(--color-border)] bg-white/80 text-[var(--color-text-secondary)]"
          }`}
        >
          {message.type === "error" ? (
            <AlertCircle className="h-4 w-4 shrink-0 text-amber-500" />
          ) : message.type === "success" ? (
            <CheckCircle2 className="h-4 w-4 shrink-0 text-green-500" />
          ) : (
            <AlertCircle className="h-4 w-4 shrink-0 text-blue-500" />
          )}
          {message.text}
        </div>
      ) : null}

      <Card className="overflow-hidden">
        <CardHeader className="!pb-3">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-display text-xl font-bold text-[var(--ink)]">批量导题</h3>
              <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">OCR → AI 解析 → 待审核</p>
            </div>
            {queuePhase !== "idle" && imageTasks.length > 0 && (
              <span className={cn(
                "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold",
                queuePhase === "done"
                  ? failedCount > 0 && succeededCount === 0 ? "bg-[var(--color-danger-light)] text-[var(--color-danger)]" : "bg-[var(--color-success-light)] text-[var(--color-success)]"
                  : "bg-[var(--color-warning-light)] text-[var(--color-warning)]",
              )}>
                <span className={cn(
                  "inline-block h-1.5 w-1.5 rounded-full",
                  queuePhase === "done"
                    ? failedCount > 0 && succeededCount === 0 ? "bg-[var(--color-danger)]" : "bg-[var(--color-success)]"
                    : "animate-pulse bg-[var(--color-warning)]",
                )} />
                {queuePhase === "done" ? (failedCount > 0 && succeededCount === 0 ? "全部失败" : "已完成") : queuePhase === "uploading" ? "上传中" : "识别中"}
              </span>
            )}
          </div>
        </CardHeader>

        <div className="flex min-h-[460px]">
          {/* ── Left Sidebar: Config ── */}
          <div className="flex w-[240px] shrink-0 flex-col gap-3 border-r border-[var(--color-border)] bg-[var(--color-bg-input)]/30 p-3.5">
            {/* Compact dropzone */}
            <label htmlFor={fileInputId}>
              <div
                onDragOver={onDragOver}
                onDragLeave={onDragLeave}
                onDrop={onDrop}
                className={cn(
                  "relative flex cursor-pointer flex-col items-center rounded-xl border-2 border-dashed p-4 text-center transition",
                  isJobActive
                    ? "border-[var(--color-border)] bg-[var(--color-bg-input)] opacity-50"
                    : dragActive || files.length > 0
                      ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]"
                      : "border-[var(--color-border)] bg-white/50 hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)]",
                )}
              >
                <Images className={cn("mb-1 h-6 w-6", files.length > 0 ? "text-[var(--color-primary-dark)]" : "text-[var(--color-text-hint)]")} />
                {files.length > 0 ? (
                  <p className="text-xs font-semibold text-[var(--ink)]">{files.length} 张图片</p>
                ) : (
                  <p className="text-xs font-semibold text-[var(--ink)]">选择图片</p>
                )}
                <p className="mt-0.5 text-[10px] text-[var(--color-text-hint)]">拖拽 · 粘贴 · 点击</p>
                <input
                  id={fileInputId}
                  type="file"
                  multiple
                  accept={ACCEPT}
                  disabled={isJobActive}
                  className="absolute inset-0 cursor-pointer opacity-0"
                  onChange={(event) => { addFiles(event.target.files); event.target.value = ""; }}
                />
              </div>
            </label>

            {/* File list (compact) */}
            {files.length > 0 && queuePhase === "idle" && (
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-hint)]">待上传</span>
                  <button type="button" disabled={isJobActive} onClick={clearFiles}
                    className="text-[10px] font-semibold text-[var(--color-text-hint)] transition hover:text-[var(--color-danger)] disabled:opacity-40">
                    清空
                  </button>
                </div>
                <div className="flex max-h-[100px] flex-col gap-0.5 overflow-auto">
                  {files.map((file, index) => (
                    <div key={`${file.name}_${file.size}_${index}`} className="flex items-center gap-1.5 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-text-secondary)] hover:bg-white/60">
                      <span className="max-w-[150px] truncate" title={file.name}>{file.name}</span>
                      <button type="button" disabled={isJobActive} onClick={() => removeFile(index)}
                        className="ml-auto shrink-0 text-[var(--color-text-hint)] transition hover:text-[var(--color-danger)] disabled:opacity-40">
                        <X className="h-2.5 w-2.5" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Config fields */}
            <div className="flex flex-col gap-2">
              <div className="space-y-0.5">
                <span className="text-[10px] font-semibold text-[var(--color-text-hint)]">科目</span>
                <div className="relative" ref={subjectSelectRef}>
                  <button
                    type="button"
                    disabled={isJobActive}
                    onClick={() => setSubjectSelectOpen((prev) => !prev)}
                    className={cn(
                      "flex h-8 w-full items-center justify-between gap-2 rounded-lg border px-2 text-[11px] outline-none transition-all",
                      isJobActive ? "border-[var(--color-border)] bg-[var(--color-bg-input)] opacity-50 cursor-not-allowed"
                        : subjectSelectOpen ? "border-[var(--color-primary)] bg-white ring-2 ring-[rgba(91,123,154,0.14)]"
                          : "border-[var(--color-border)] bg-white hover:border-[var(--color-primary)]",
                    )}
                  >
                    <span className={cn("truncate", subjectId ? "font-semibold text-[var(--ink)]" : "text-[var(--color-text-hint)]")}>
                      {subjectId ? (subjectOptions.find((s) => String(s.id) === subjectId)?.name || subjectId) : "选择科目（可选）"}
                    </span>
                    <ChevronDown className={cn("h-3 w-3 shrink-0 text-[var(--color-text-hint)] transition-transform", subjectSelectOpen && "rotate-180")} />
                  </button>
                  {subjectSelectOpen && (
                    <div className="absolute left-0 right-0 top-full z-50 mt-1 max-h-[200px] overflow-y-auto surface-card rounded-lg p-0.5 animate-drop-in">
                      <button
                        type="button"
                        onClick={() => { setSubjectId(""); setSubjectSelectOpen(false); }}
                        className={cn(
                          "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-[11px] transition-all",
                          !subjectId ? "bg-[var(--color-primary-light)] text-[var(--color-primary-dark)] font-semibold" : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-input)]",
                        )}
                      >
                        选择科目（可选）
                        {!subjectId && <Check className="h-3 w-3 text-[var(--color-primary-dark)]" />}
                      </button>
                      {subjectOptions.map((s) => (
                        <button
                          key={s.id}
                          type="button"
                          onClick={() => { setSubjectId(String(s.id)); setSubjectSelectOpen(false); }}
                          className={cn(
                            "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-[11px] transition-all",
                            subjectId === String(s.id) ? "bg-[var(--color-primary-light)] text-[var(--color-primary-dark)] font-semibold" : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-input)]",
                          )}
                        >
                          {s.name}
                          {subjectId === String(s.id) && <Check className="h-3 w-3 text-[var(--color-primary-dark)]" />}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <div className="space-y-0.5">
                <span className="text-[10px] font-semibold text-[var(--color-text-hint)]">并发数</span>
                <div className="relative" ref={selectRef}>
                  <button
                    type="button"
                    disabled={isJobActive}
                    onClick={() => setSelectOpen((prev) => !prev)}
                    className={cn(
                      "flex h-8 w-full items-center justify-between gap-2 rounded-lg border px-2 text-[11px] outline-none transition-all",
                      isJobActive ? "border-[var(--color-border)] bg-[var(--color-bg-input)] opacity-50 cursor-not-allowed"
                        : selectOpen ? "border-[var(--color-primary)] bg-white ring-2 ring-[rgba(91,123,154,0.14)]"
                          : "border-[var(--color-border)] bg-white hover:border-[var(--color-primary)]",
                    )}
                  >
                    <span className="flex items-center gap-1.5">
                      <span className="font-semibold text-[var(--ink)]">{concurrency}</span>
                      {(() => {
                        const opt = concurrencyOptions.find((o) => o.value === concurrency);
                        return opt?.tag ? (
                          <span className={cn("text-[9px] font-semibold leading-none rounded px-1 py-0.5", opt.tagClass)}>{opt.tag}</span>
                        ) : null;
                      })()}
                    </span>
                    <ChevronDown className={cn("h-3 w-3 text-[var(--color-text-hint)] transition-transform", selectOpen && "rotate-180")} />
                  </button>
                  {selectOpen && (
                    <div className="absolute left-0 right-0 top-full z-50 mt-1 surface-card overflow-hidden rounded-lg p-0.5 animate-drop-in">
                      {concurrencyOptions.map((opt) => (
                        <button key={opt.value} type="button"
                          onClick={() => { setConcurrency(opt.value); setSelectOpen(false); }}
                          className={cn(
                            "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-[11px] transition-all",
                            concurrency === opt.value ? "bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]" : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-input)]",
                          )}
                        >
                          <span className="flex items-center gap-1.5">
                            <span className={cn("font-semibold", concurrency === opt.value ? "text-[var(--color-primary-dark)]" : "text-[var(--ink)]")}>{opt.label}</span>
                            {opt.tag && <span className={cn("text-[9px] font-semibold leading-none rounded px-1 py-0.5", opt.tagClass)}>{opt.tag}</span>}
                          </span>
                          {concurrency === opt.value && <Check className="h-3 w-3 text-[var(--color-primary-dark)]" />}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="border-t border-[var(--color-border)]/60 pt-2">
              <OcrModeSelector value={ocrMode} onChange={setOcrMode} disabled={isJobActive} />
            </div>

            {/* Submit / Reset */}
            <div className="mt-auto border-t border-[var(--color-border)]/60 pt-3">
              {queuePhase === "done" ? (
                <Button onClick={resetQueue} className="h-9 w-full text-xs" variant="secondary">
                  <RefreshCw className="h-3.5 w-3.5" />
                  重新导入
                </Button>
              ) : (
                <div className="flex gap-2">
                  {queuePhase === "polling" && (
                    <Button onClick={resetQueue} variant="secondary" className="h-9 px-3 text-xs">
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  )}
                  <Button
                    disabled={files.length === 0 || queuePhase !== "idle"}
                    onClick={() => { if (queuePhase === "idle") startQueue(); }}
                    className="h-9 flex-1 text-xs"
                  >
                    <UploadCloud className="h-3.5 w-3.5" />
                    {queuePhase === "uploading" ? "上传中..." : queuePhase === "polling" ? "识别中..." : `开始导入${files.length > 0 ? `（${files.length}）` : ""}`}
                  </Button>
                </div>
              )}
            </div>
          </div>

          {/* ── Right: Progress Dashboard ── */}
          <div className="flex-1 p-5">
            {/* Empty state */}
            {queuePhase === "idle" && imageTasks.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center text-center">
                <Images className="mb-3 h-10 w-10 text-[var(--color-text-hint)]" />
                <p className="text-sm font-semibold text-[var(--color-text-secondary)]">等待任务提交</p>
                <p className="mt-1 max-w-xs text-xs leading-relaxed text-[var(--color-text-hint)]">
                  选择图片并点击「开始导入」，此处将显示实时进度
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Stats row */}
                <div className="grid grid-cols-5 gap-2">
                  {[
                    { label: "总数", value: totalImages, color: "var(--ink)" },
                    { label: "上传", value: uploadingCount, color: "#3a6a9a", show: uploadingCount > 0 },
                    { label: "识别", value: processingCount, color: "#b87a30", show: processingCount > 0 },
                    { label: "成功", value: succeededCount, color: "#3a7a5a", show: succeededCount > 0 },
                    { label: "题目", value: totalQuestions, color: "var(--color-primary-dark)", show: totalQuestions > 0 },
                  ].filter(s => s.show !== false).map((s) => (
                    <div key={s.label} className="rounded-lg border border-[var(--color-border)] bg-white p-2.5 text-center">
                      <span className="font-display text-xl font-bold tabular-nums" style={{ color: s.color }}>{s.value}</span>
                      <p className="mt-0.5 text-[9px] text-[var(--color-text-hint)]">{s.label}</p>
                    </div>
                  ))}
                  {failedCount > 0 && (
                    <div className="rounded-lg border border-[var(--color-danger)]/20 bg-[var(--color-danger-light)] p-2.5 text-center">
                      <span className="font-display text-xl font-bold tabular-nums text-[var(--color-danger)]">{failedCount}</span>
                      <p className="mt-0.5 text-[9px] text-[var(--color-text-hint)]">失败</p>
                    </div>
                  )}
                </div>

                {/* Progress bar */}
                <div>
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-[11px] text-[var(--color-text-secondary)]">总体进度</span>
                    <span className="text-[11px] font-semibold tabular-nums text-[var(--ink)]">{progressPct}%</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-[var(--color-bg-input)]">
                    <div className="h-full rounded-full bg-gradient-to-r from-[var(--color-primary)] to-[#7b9bbb] transition-all duration-700" style={{ width: `${progressPct}%` }} />
                  </div>
                </div>

                {/* Task list */}
                <div>
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-hint)]">任务明细</span>
                  <div className="mt-2 space-y-1">
                    {imageTasks.map((task) => (
                      <div key={task.id} className={cn(
                        "rounded-lg border bg-white transition-all hover:border-[var(--color-primary)]/30 hover:shadow-sm",
                        task.status === "failed" ? "border-[var(--color-danger)]/20" : "border-[var(--color-border)]",
                      )}>
                        <div className="flex items-center gap-2 px-3 py-2 text-xs">
                          <span className="w-6 shrink-0 font-mono text-[10px] text-[var(--color-text-hint)]">#{task.seq}</span>
                          <span className="min-w-0 flex-1 truncate text-[var(--ink)]" title={task.file.name}>{task.file.name}</span>
                          {renderStatusBadge(task)}
                        </div>
                        {/* Trace event log — visible when events exist */}
                        {task.traceEvents.length > 0 && (
                          <div className="animate-rise-in border-t border-[var(--color-border)]/50 bg-[var(--color-bg-input)]/30 px-3 py-1.5">
                            <div className="space-y-0.5">
                              {task.traceEvents.map((ev, idx) => (
                                <div key={idx} className="trace-enter flex items-center gap-1.5 text-[10px] leading-relaxed" style={{ animationDelay: `${idx * 60}ms` }}>
                                  <span className={cn(
                                    "shrink-0 rounded px-1 py-px font-medium transition-colors duration-200",
                                    ev.step === "ocr" ? "bg-blue-50 text-blue-600"
                                      : ev.step === "pipeline" ? "bg-purple-50 text-purple-600"
                                        : ev.step === "done" ? "bg-green-50 text-green-600"
                                          : ev.step === "error" ? "bg-red-50 text-red-600"
                                            : ev.step === "config" ? "bg-amber-50 text-amber-600"
                                              : "bg-[var(--color-bg-input)] text-[var(--color-text-hint)]",
                                  )}>{ev.step}</span>
                                  <span className={cn(
                                    "shrink-0 transition-colors duration-200",
                                    ev.status === "success" ? "text-green-500" : ev.status === "failed" ? "text-red-500" : ev.status === "running" ? "text-amber-500" : "text-[var(--color-text-hint)]",
                                  )}>
                                    {ev.status === "success" ? "✓" : ev.status === "failed" ? "✕" : ev.status === "running" ? "…" : "·"}
                                  </span>
                                  <span className="min-w-0 truncate text-[var(--color-text-secondary)]" title={ev.message}>{ev.message}</span>
                                  {ev.duration_ms != null && ev.duration_ms > 0 && (
                                    <span className="shrink-0 tabular-nums text-[var(--color-text-hint)]">{ev.duration_ms}ms</span>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                {/* Quick link to review */}
                {queuePhase === "done" && succeededCount > 0 && (
                  <a className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-white/70 px-3 text-[11px] font-semibold text-[var(--color-text-secondary)] transition-all hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] active:scale-95"
                    href="/imports/review">
                    <ClipboardCheck className="h-3.5 w-3.5" />
                    前往待审核
                  </a>
                )}
              </div>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}

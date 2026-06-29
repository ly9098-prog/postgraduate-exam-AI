"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Check, CheckCircle2, ChevronDown, ClipboardCheck, Images, RefreshCw, Trash2, UploadCloud, X } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
  return Number.isFinite(n) && n >= 1 && n <= 10 ? String(Math.floor(n)) : "2";
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

function fmtTime(ts?: number) {
  const d = ts ? new Date(ts) : new Date();
  return d.toLocaleTimeString("en-US", { hour12: false });
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
  const abortRef = useRef<AbortController | null>(null);
  const imageTasksRef = useRef<ImageTask[]>([]);

  // Keep ref in sync
  useEffect(() => { imageTasksRef.current = imageTasks; }, [imageTasks]);

  // ── SSE streaming (replaces per-image polling) ────────────

  const abortSourcesRef = useRef<Map<string, () => void>>(new Map());
  const doneRef = useRef(false); // guard: completion message shown once

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
    const total = filesToProcess.length;
    const maxConc = Math.max(1, Math.min(10, Number(concurrency) || 2));
    const batchId = `batch_${Date.now()}`;
    const now = Date.now();
    doneRef.current = false;

    // 1. Clear files, create task items
    setFiles([]);

    const initialTasks: ImageTask[] = filesToProcess.map((file, idx) => ({
      id: `img_${now}_${idx + 1}`,
      seq: idx + 1,
      batchId,
      imageId: `img_${batchId}_${idx + 1}`,
      requestId: `req_${batchId}_${idx + 1}`,
      file,
      status: "pending",
      jobId: null,
      jobStatus: null,
      traceEvents: [],
      questionCount: 0,
      errorMessage: null,
      startedAt: 0,
      finishedAt: null,
    }));

    setImageTasks(initialTasks);
    setQueuePhase("uploading");
    setMessage(null);

    const abortCtrl = new AbortController();
    abortRef.current = abortCtrl;

    // 2. Process in chunks
    try {
      for (let start = 0; start < total; start += maxConc) {
        const chunk = initialTasks.slice(start, start + maxConc);

        await Promise.all(
          chunk.map(async (task) => {
            if (abortCtrl.signal.aborted) return;

            const fileIdx = task.seq - 1;

            // Mark uploading
            setImageTasks((prev) =>
              prev.map((p) =>
                p.id === task.id
                  ? { ...p, status: "uploading" as const, startedAt: Date.now() }
                  : p,
              ),
            );

            try {
              const formData = new FormData();
              formData.append("files", filesToProcess[fileIdx]);
              const qs = toQuery({
                subject_id: subjectId || undefined,
                concurrency: 1,
                enable_ai_repair: true,
                confidence_threshold: "0.6",
                ocr_mode: ocrMode,
                batch_id: task.batchId,
                image_id: task.imageId,
                request_id: task.requestId,
              });

              const result = await apiRequest<BatchImageUploadResponse>(
                `/imports/batch-image/upload${qs}`,
                { method: "POST", body: formData, signal: abortCtrl.signal },
              );

              setImageTasks((prev) =>
                prev.map((p) =>
                  p.id === task.id
                    ? {
                        ...p,
                        status: "processing" as const,
                        jobId: result.job_id,
                      }
                    : p,
                ),
              );

              // Open SSE stream for this job
              const close = connectSSE(
                `/imports/batch-image/${result.job_id}/stream`,
                getApiAccessToken(),
                {
                  onTrace: (event) => {
                    setImageTasks((prev) =>
                      prev.map((p) =>
                        p.id === task.id
                          ? { ...p, traceEvents: [...p.traceEvents, event] }
                          : p,
                      ),
                    );
                  },
                  onDone: (summary) => {
                    setImageTasks((prev) =>
                      prev.map((p) =>
                        p.id === task.id
                          ? {
                              ...p,
                              status:
                                summary.status === "completed"
                                  ? ("succeeded" as const)
                                  : ("failed" as const),
                              questionCount: summary.total_questions,
                              errorMessage: summary.error_message,
                              finishedAt: Date.now(),
                            }
                          : p,
                      ),
                    );
                    abortSourcesRef.current.delete(result.job_id);
                  },
                },
              );
              abortSourcesRef.current.set(result.job_id, close);
            } catch (err: unknown) {
              if (abortCtrl.signal.aborted) return;
              const msg = err instanceof Error ? err.message : String(err);
              setImageTasks((prev) =>
                prev.map((p) =>
                  p.id === task.id
                    ? {
                        ...p,
                        status: "failed" as const,
                        errorMessage: msg,
                        startedAt: task.startedAt || Date.now(),
                        finishedAt: Date.now(),
                      }
                    : p,
                ),
              );
            }
          }),
        );

        if (abortCtrl.signal.aborted) break;
      }

      // 3. All uploads submitted → polling phase
      setQueuePhase("polling");
      const totalImg = imageTasksRef.current.length;
      setMessage({ text: `全部 ${totalImg} 张图片已提交，正在识别中...`, type: "info" });
    } catch {
      // Abort or unexpected error
    }
  }, [files, subjectId, concurrency, ocrMode]);

  const resetQueue = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    // Close all SSE connections
    for (const [, close] of abortSourcesRef.current) close();
    abortSourcesRef.current.clear();
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
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // ── Computed aggregate values ────────────────────────────────

  const totalImages = imageTasks.length;
  const doneImages = imageTasks.filter(
    (t) => t.status === "succeeded" || t.status === "failed",
  ).length;
  const progressPct = totalImages > 0 ? Math.round((doneImages / totalImages) * 100) : 0;
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
    if (task.status === "failed") {
      return (
        <span className="shrink-0 rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-semibold text-red-700 transition-all duration-300">
          失败
        </span>
      );
    }
    if (task.status === "succeeded") {
      return (
        <span className="shrink-0 rounded-full bg-green-50 px-2 py-0.5 text-[10px] font-semibold text-green-700 transition-all duration-300">
          成功 · {task.questionCount}题
        </span>
      );
    }
    if (task.status === "processing") {
      return (
        <span className="shrink-0 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700 transition-all duration-300">
          识别中
        </span>
      );
    }
    if (task.status === "uploading") {
      return (
        <span className="shrink-0 rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-blue-700 transition-all duration-300">
          上传中
        </span>
      );
    }
    return (
      <span className="shrink-0 rounded-full bg-[var(--color-bg-input)] px-2 py-0.5 text-[10px] font-semibold text-[var(--color-text-secondary)] transition-all duration-300">
        等待中
      </span>
    );
  };

  const concurrencyOptions = [
    { value: "1", label: "1", tag: "最稳", tagClass: "bg-amber-50 text-amber-700" },
    { value: "2", label: "2", tag: "推荐", tagClass: "bg-green-50 text-green-700" },
    { value: "3", label: "3", tag: null, tagClass: "" },
    { value: "4", label: "4", tag: "均衡", tagClass: "bg-blue-50 text-blue-700" },
    { value: "5", label: "5", tag: null, tagClass: "" },
    { value: "6", label: "6", tag: null, tagClass: "" },
    { value: "8", label: "8", tag: null, tagClass: "" },
    { value: "10", label: "10", tag: "最快", tagClass: "bg-indigo-50 text-indigo-700" },
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

      <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        {/* ===== Left: 选择图片 + 上传 ===== */}
        <Card>
          <CardHeader>
            <div className="flex flex-col gap-1">
              <h3 className="font-display text-2xl font-bold text-[var(--ink)]">批量导题</h3>
              <p className="text-sm text-[var(--color-text-secondary)]">
                一次选择多张题目图片，自动逐张 OCR → AI 解析 → 进入待审核区。
              </p>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            {/* Dropzone */}
            <label htmlFor={fileInputId}>
              <div
                onDragOver={onDragOver}
                onDragLeave={onDragLeave}
                onDrop={onDrop}
                className={`relative flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-8 transition ${
                  isJobActive
                    ? "border-[var(--color-border)] bg-[var(--color-bg-input)] opacity-50"
                    : dragActive
                      ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]"
                      : files.length > 0
                        ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]"
                        : "border-[var(--color-border)] bg-white/50 hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)]"
                }`}
              >
                <Images
                  className={`mb-2 h-8 w-8 ${files.length > 0 ? "text-[var(--color-primary-dark)]" : "text-[var(--color-text-hint)]"}`}
                />
                {files.length > 0 ? (
                  <p className="text-sm font-semibold text-[var(--ink)]">已选择 {files.length} 张图片</p>
                ) : (
                  <p className="text-sm font-semibold text-[var(--ink)]">点击选择 · 拖拽 · 粘贴图片</p>
                )}
                <p className="mt-0.5 text-xs text-[var(--color-text-hint)]">
                  JPG、PNG、WebP，单次最多 {MAX_FILES} 张
                </p>
                <input
                  id={fileInputId}
                  type="file"
                  multiple
                  accept={ACCEPT}
                  disabled={isJobActive}
                  className="absolute inset-0 cursor-pointer opacity-0"
                  onChange={(event) => {
                    addFiles(event.target.files);
                    event.target.value = "";
                  }}
                />
              </div>
            </label>

            {/* Selected file chips — only show before queue starts */}
            {files.length > 0 && queuePhase === "idle" ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-[var(--color-text-secondary)]">
                    待上传（{files.length}）
                  </span>
                  <button
                    type="button"
                    disabled={isJobActive}
                    onClick={clearFiles}
                    className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--color-text-hint)] transition hover:text-[var(--color-danger)] disabled:opacity-40"
                  >
                    <Trash2 className="h-3 w-3" />
                    清空
                  </button>
                </div>
                <div className="flex max-h-40 flex-wrap gap-1.5 overflow-auto rounded-2xl border border-[var(--color-border)] bg-white/60 p-2.5">
                  {files.map((file, index) => (
                    <span
                      key={`${file.name}_${file.size}_${index}`}
                      className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-white px-2 py-1 text-[11px] text-[var(--color-text-secondary)]"
                    >
                      <span className="max-w-[140px] truncate" title={file.name}>
                        {file.name}
                      </span>
                      <button
                        type="button"
                        disabled={isJobActive}
                        onClick={() => removeFile(index)}
                        className="shrink-0 text-[var(--color-text-hint)] transition hover:text-[var(--color-danger)] disabled:opacity-40"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  ))}
                </div>
              </div>
            ) : null}

            {/* Subject + concurrency */}
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1">
                <span className="text-xs font-semibold text-[var(--color-text-secondary)]">科目（可选）</span>
                <select
                  className="h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm outline-none transition focus:border-[var(--color-primary)]"
                  value={subjectId}
                  disabled={isJobActive}
                  onChange={(e) => setSubjectId(e.target.value)}
                >
                  <option value="">选择科目（可选）</option>
                  {subjectOptions.map((s) => (
                    <option key={s.id} value={String(s.id)}>{s.name}</option>
                  ))}
                </select>
              </label>
              <div className="space-y-1">
                <span className="text-xs font-semibold text-[var(--color-text-secondary)]">并发数</span>
                <div className="relative" ref={selectRef}>
                  <button
                    type="button"
                    disabled={isJobActive}
                    onClick={() => setSelectOpen((prev) => !prev)}
                    className={`h-11 w-full rounded-xl border px-3 text-sm outline-none transition-all duration-200 flex items-center justify-between gap-2 ${
                      isJobActive
                        ? "border-[var(--color-border)] bg-[var(--color-bg-input)] opacity-50 cursor-not-allowed"
                        : selectOpen
                          ? "border-[var(--color-primary)] bg-white ring-4 ring-[rgba(91,123,154,0.14)]"
                          : "border-[var(--color-border)] bg-[var(--color-bg-input)] hover:border-[var(--color-primary)] hover:bg-white"
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <span className="font-semibold text-[var(--ink)]">{concurrency}</span>
                      {(() => {
                        const opt = concurrencyOptions.find((o) => o.value === concurrency);
                        return opt?.tag ? (
                          <span className={`text-[10px] font-semibold leading-none px-1.5 py-0.5 rounded ${opt.tagClass}`}>
                            {opt.tag}
                          </span>
                        ) : null;
                      })()}
                    </span>
                    <ChevronDown
                      className={`h-4 w-4 text-[var(--color-text-hint)] transition-transform duration-200 ${selectOpen ? "rotate-180" : ""}`}
                    />
                  </button>

                  {selectOpen && (
                    <div
                      className="absolute top-full left-0 right-0 z-50 mt-1.5 surface-card rounded-xl overflow-hidden p-1 animate-drop-in"
                      onKeyDown={(e) => {
                        if (e.key === "Escape") setSelectOpen(false);
                      }}
                    >
                      {concurrencyOptions.map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => {
                            setConcurrency(opt.value);
                            setSelectOpen(false);
                          }}
                          className={`w-full flex items-center justify-between gap-2 rounded-lg px-3 py-2.5 text-sm transition-all duration-150 ${
                            concurrency === opt.value
                              ? "bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]"
                              : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-input)] hover:text-[var(--ink)]"
                          }`}
                        >
                          <span className="flex items-center gap-2">
                            <span
                              className={`font-semibold ${concurrency === opt.value ? "text-[var(--color-primary-dark)]" : "text-[var(--ink)]"}`}
                            >
                              {opt.label}
                            </span>
                            {opt.tag && (
                              <span className={`text-[10px] font-semibold leading-none px-1.5 py-0.5 rounded ${opt.tagClass}`}>
                                {opt.tag}
                              </span>
                            )}
                          </span>
                          {concurrency === opt.value && (
                            <Check className="h-3.5 w-3.5 text-[var(--color-primary-dark)]" />
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="border-t border-[var(--color-border)] pt-4">
              <OcrModeSelector value={ocrMode} onChange={setOcrMode} disabled={isJobActive} />
            </div>

            {/* Submit / Reset */}
            <div className="flex items-center justify-end gap-3 border-t border-[var(--color-border)] pt-4">
              {queuePhase === "done" ? (
                <Button onClick={resetQueue} className="h-11 px-5" variant="secondary">
                  <RefreshCw className="h-4 w-4" />
                  重新导入
                </Button>
              ) : (
                <>
                  {queuePhase === "polling" ? (
                    <Button onClick={resetQueue} variant="secondary" className="h-11 px-5">
                      <X className="h-4 w-4" />
                      取消
                    </Button>
                  ) : null}
                  <Button
                    disabled={files.length === 0 || queuePhase !== "idle"}
                    onClick={() => {
                      if (queuePhase === "idle") startQueue();
                    }}
                    className="h-11 px-5"
                  >
                    <UploadCloud className="h-4 w-4" />
                    {queuePhase === "uploading"
                      ? "上传中..."
                      : queuePhase === "polling"
                        ? "识别中..."
                        : `开始导入${files.length > 0 ? `（${files.length}）` : ""}`}
                  </Button>
                </>
              )}
            </div>
          </CardContent>
        </Card>

        {/* ===== Right: 任务进度 + 日志面板 ===== */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <h3 className="font-display text-xl font-bold text-[var(--ink)]">
                {queuePhase === "idle" ? "准备就绪" : "任务进度"}
              </h3>
              <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">
                {queuePhase === "idle"
                  ? "选择图片后点击「开始导入」"
                  : queuePhase === "done"
                    ? "全部处理完成"
                    : "实时追踪每张图片的识别状态"}
              </p>
            </div>
          </CardHeader>
          <CardContent>
            {/* Empty state */}
            {queuePhase === "idle" && imageTasks.length === 0 ? (
              <div className="flex flex-col items-center py-8 text-center">
                <Images className="mb-3 h-9 w-9 text-[var(--color-text-hint)]" />
                <p className="text-sm font-semibold text-[var(--color-text-secondary)]">等待任务提交</p>
                <p className="mt-1 max-w-xs text-xs leading-relaxed text-[var(--color-text-hint)]">
                  提交后将在此处显示每张图片的识别进度和日志。
                </p>
              </div>
            ) : null}

            {/* Compact aggregate progress + inline stats — only when active */}
            {imageTasks.length > 0 ? (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              {queuePhase !== "done" ? (
                <span className="flex items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-0.5 text-[10px] font-semibold text-amber-700 transition-all duration-300">
                  <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
                  {queuePhase === "uploading" ? "上传中" : "识别中"}
                </span>
              ) : (
                <span
                  className={`animate-rise-in flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-semibold transition-all duration-300 ${
                    failedCount > 0 && succeededCount === 0
                      ? "bg-red-50 text-red-700"
                      : "bg-green-50 text-green-700"
                  }`}
                >
                  <span
                    className={`inline-block h-1.5 w-1.5 rounded-full transition-all duration-300 ${failedCount > 0 && succeededCount === 0 ? "bg-red-500" : "bg-green-500"}`}
                  />
                  {failedCount > 0 && succeededCount === 0 ? "全部失败" : "已完成"}
                </span>
              )}

              <span className="flex flex-wrap items-center gap-x-2.5 gap-y-0 text-[10px] text-[var(--color-text-secondary)]">
                <span>总数 <strong className="text-[var(--ink)] tabular-nums">{totalImages}</strong></span>
                {uploadingCount > 0 && (
                  <span>上传 <strong className="text-blue-600 tabular-nums">{uploadingCount}</strong></span>
                )}
                {processingCount > 0 && (
                  <span>识别 <strong className="text-amber-600 tabular-nums">{processingCount}</strong></span>
                )}
                {succeededCount > 0 && (
                  <span>成功 <strong className="text-green-600 tabular-nums">{succeededCount}</strong></span>
                )}
                {failedCount > 0 && (
                  <span>失败 <strong className="text-red-600 tabular-nums">{failedCount}</strong></span>
                )}
                {totalQuestions > 0 && (
                  <span>题目 <strong className="text-[var(--color-primary-dark)] tabular-nums">{totalQuestions}</strong></span>
                )}
              </span>

              <span className="text-[10px] tabular-nums text-[var(--color-text-hint)] ml-auto">{progressPct}%</span>
            </div>
            ) : null}

            {/* Progress bar — only when there are active tasks */}
            {imageTasks.length > 0 ? (
              <div className="overflow-hidden rounded-full bg-[var(--color-bg-input)]">
                <div
                  className="h-1.5 rounded-full bg-gradient-to-r from-[var(--color-primary)] to-[#7b9bbb] transition-all duration-700"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
            ) : null}

                {/* Per-image log list */}
                {imageTasks.length > 0 ? (
                  <div className="space-y-1.5">
                    <span className="text-xs font-semibold text-[var(--color-text-secondary)]">明细</span>
                    <div className="space-y-1.5">
                      {imageTasks.map((task) => {
                        const traces = task.traceEvents;
                        return (
                          <div
                            key={task.id}
                            className={`animate-rise-in rounded-xl border bg-white/70 text-xs transition-all duration-200 hover:border-[var(--color-primary)] hover:shadow-sm ${
                              task.status === "failed"
                                ? "border-red-200"
                                : "border-[var(--color-border)]"
                            }`}
                          >
                            {/* Header */}
                            <div className="flex items-center gap-2 px-3 py-2">
                              <span className="w-6 shrink-0 font-mono text-[10px] text-[var(--color-text-hint)]">
                                #{task.seq}
                              </span>
                              <span
                                className="min-w-0 flex-1 truncate text-[var(--color-text-secondary)]"
                                title={task.file.name}
                              >
                                {task.file.name}
                              </span>
                              {renderStatusBadge(task)}
                            </div>

                            {/* Trace events log */}
                            {traces.length > 0 ? (
                              <div className="border-t border-[var(--color-border)] px-3 py-2 space-y-0.5">
                                {traces.map((e, i) => (
                                  <div key={i} className="animate-rise-in flex items-start gap-2 text-[10px] leading-relaxed min-w-0 overflow-hidden">
                                    <span className="shrink-0 font-mono text-[var(--color-text-hint)] w-16">
                                      {fmtTime(new Date(e.created_at).getTime())}
                                    </span>
                                    <span
                                      className={`shrink-0 rounded px-1.5 py-0.5 font-semibold ${
                                        e.status === "success"
                                          ? "bg-green-50 text-green-700"
                                          : e.status === "failed"
                                            ? "bg-red-50 text-red-700"
                                            : e.step === "upload"
                                              ? "bg-blue-50 text-blue-700"
                                              : e.step === "ocr"
                                                ? "bg-amber-50 text-amber-700"
                                                : "bg-gray-50 text-gray-500"
                                      }`}
                                    >
                                      {e.step === "upload" ? "上传" : e.step === "ocr" ? "OCR" : e.step === "pipeline" ? "解析" : e.step === "done" ? "完成" : e.step === "error" ? "错误" : e.step}
                                    </span>
                                    <span className="min-w-0 break-words text-[var(--color-text-secondary)] leading-relaxed">
                                      {e.message}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            ) : null}

                            {/* Error message for failed items */}
                            {task.status === "failed" && task.errorMessage ? (
                              <div className="animate-rise-in border-t border-red-100 bg-red-50/50 px-3 py-1.5 text-[10px] text-red-700">
                                {task.errorMessage}
                              </div>
                            ) : null}

                            {/* Reparse button for failed items with OCR cache */}
                            {task.status === "failed" && task.jobStatus
                              && (task.jobStatus.items ?? []).some(
                                (item) => item.status === "failed" && item.has_ocr_cache,
                              ) ? (
                              <div className="border-t border-[var(--color-border)] px-3 py-1.5">
                                {(() => {
                                  const reparseItem = (task.jobStatus.items ?? []).find(
                                    (item) => item.status === "failed" && item.has_ocr_cache,
                                  );
                                  if (!reparseItem) return null;
                                  return (
                                    <button
                                      key={reparseItem.id}
                                      type="button"
                                      disabled={reparseMutation.isPending}
                                      onClick={() => reparseMutation.mutate(reparseItem.id)}
                                      className="inline-flex items-center gap-1 rounded-lg border border-[var(--color-border)] px-2 py-0.5 text-[10px] font-semibold text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary)] hover:text-[var(--color-primary-dark)] disabled:opacity-40"
                                      title="基于缓存的 OCR 文本重新解析，不重复识别"
                                    >
                                      <RefreshCw
                                        className={`h-3 w-3 ${reparseMutation.isPending && reparseMutation.variables === reparseItem.id ? "animate-spin" : ""}`}
                                      />
                                      重解析
                                    </button>
                                  );
                                })()}
                              </div>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ) : null}

                {/* Quick link to review queue */}
                {queuePhase === "done" && succeededCount > 0 ? (
                  <div className="animate-rise-in flex flex-wrap gap-2 border-t border-[var(--color-border)] pt-3">
                    <a
                      className="inline-flex h-8 items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-white/70 px-3 text-[10px] font-semibold text-[var(--color-text-secondary)] transition-all duration-200 hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)] active:scale-95"
                      href="/imports/review"
                    >
                      <ClipboardCheck className="h-3 w-3" />
                      前往待审核
                    </a>
                  </div>
                ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

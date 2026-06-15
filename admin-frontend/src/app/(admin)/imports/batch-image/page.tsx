"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Check, CheckCircle2, ChevronDown, ClipboardCheck, Images, RefreshCw, Trash2, UploadCloud, X } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiRequest, toQuery } from "@/lib/api/client";
import type { BatchImageJobStatusResponse, BatchImageReparseResponse, BatchImageUploadResponse } from "@/lib/api/types";

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

function isTerminal(status?: string) {
  return Boolean(status && ["completed", "failed"].includes(status));
}

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

export default function BatchImagePage() {
  const [files, setFiles] = useState<File[]>([]);
  const [subject, setSubject] = useState("");
  const [concurrency, setConcurrency] = useState(DEFAULT_CONCURRENCY);
  const [jobId, setJobId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const fileInputId = useId();
  const queryClient = useQueryClient();
  const wasNotTerminal = useRef(true);
  const [selectOpen, setSelectOpen] = useState(false);
  const selectRef = useRef<HTMLDivElement>(null);

  const statusQuery = useQuery({
    queryKey: ["batch-image-job", jobId],
    queryFn: () => apiRequest<BatchImageJobStatusResponse>(`/imports/batch-image/${jobId}`),
    enabled: jobId !== null,
    refetchInterval: (query) => (isTerminal(query.state.data?.status) ? false : 2500),
    retry: false,
  });

  const status = statusQuery.data;
  const isRunning = jobId !== null && !(status && isTerminal(status.status));

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
      if (isRunning) return;
      const items = event.clipboardData?.files;
      if (items && items.length > 0) {
        addFiles(items);
        setMessage(`已从剪贴板添加 ${items.length} 张图片`);
      }
    }
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [addFiles, isRunning]);

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    if (!isRunning) setDragActive(true);
  }, [isRunning]);

  const onDragLeave = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    setDragActive(false);
  }, []);

  const onDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    setDragActive(false);
    if (isRunning) return;
    addFiles(event.dataTransfer?.files ?? null);
  }, [addFiles, isRunning]);

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (files.length === 0) throw new Error("请先选择要导入的图片");
      const formData = new FormData();
      for (const file of files) formData.append("files", file);
      const query = toQuery({
        subject: subject || undefined,
        concurrency: concurrency || DEFAULT_CONCURRENCY,
        enable_ai_repair: true,
        confidence_threshold: "0.6",
      });
      return apiRequest<BatchImageUploadResponse>(`/imports/batch-image/upload${query}`, {
        method: "POST",
        body: formData,
      });
    },
    onSuccess: (result) => {
      wasNotTerminal.current = true;
      setJobId(result.job_id);
      setFiles([]);
      const rejectedNote = result.rejected > 0 ? `，跳过 ${result.rejected} 个无效文件` : "";
      setMessage(`已提交 ${result.total} 张图片（并发 ${result.concurrency}）${rejectedNote}`);
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "上传失败，请稍后重试。");
    },
  });

  const reparseMutation = useMutation({
    mutationFn: (itemId: number) =>
      apiRequest<BatchImageReparseResponse>(`/imports/batch-image/items/${itemId}/reparse`, {
        method: "POST",
      }),
    onSuccess: (result) => {
      setMessage(
        result.status === "succeeded"
          ? `第 ${result.item_id} 项重新解析成功，生成 ${result.question_count} 道题`
          : `第 ${result.item_id} 项重新解析未成功：${result.error_message || "未知原因"}`,
      );
      queryClient.invalidateQueries({ queryKey: ["batch-image-job", jobId] });
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "重新解析失败，请稍后重试。");
    },
  });

  useEffect(() => {
    if (status && wasNotTerminal.current && isTerminal(status.status)) {
      wasNotTerminal.current = false;
      queryClient.invalidateQueries({ queryKey: ["import-review-queue"] });
    }
  }, [status, queryClient]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (selectRef.current && !selectRef.current.contains(e.target as Node)) {
        setSelectOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const total = status?.total ?? 0;
  const completed = status?.completed ?? 0;
  const progressPct = total > 0 ? Math.round((completed / total) * 100) : 0;
  const isDone = Boolean(status && isTerminal(status.status));

  return (
    <div className="space-y-6">
      {message ? (
        <div className="flex items-center gap-2.5 rounded-2xl border border-[var(--color-border)] bg-white/80 px-4 py-3 text-sm text-[var(--color-text-secondary)] shadow-[var(--shadow-crisp)]">
          {uploadMutation.isError || reparseMutation.isError ? (
            <AlertCircle className="h-4 w-4 shrink-0 text-amber-500" />
          ) : (
            <CheckCircle2 className="h-4 w-4 shrink-0 text-green-500" />
          )}
          {message}
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
                  isRunning
                    ? "border-[var(--color-border)] bg-[var(--color-bg-input)] opacity-50"
                    : dragActive
                      ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]"
                      : files.length > 0
                        ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]"
                        : "border-[var(--color-border)] bg-white/50 hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)]"
                }`}
              >
                <Images className={`mb-2 h-8 w-8 ${files.length > 0 ? "text-[var(--color-primary-dark)]" : "text-[var(--color-text-hint)]"}`} />
                {files.length > 0 ? (
                  <p className="text-sm font-semibold text-[var(--ink)]">已选择 {files.length} 张图片</p>
                ) : (
                  <p className="text-sm font-semibold text-[var(--ink)]">点击选择 · 拖拽 · 粘贴图片</p>
                )}
                <p className="mt-0.5 text-xs text-[var(--color-text-hint)]">JPG、PNG、WebP，单次最多 {MAX_FILES} 张</p>
                <input
                  id={fileInputId}
                  type="file"
                  multiple
                  accept={ACCEPT}
                  disabled={isRunning}
                  className="absolute inset-0 cursor-pointer opacity-0"
                  onChange={(event) => {
                    addFiles(event.target.files);
                    event.target.value = "";
                  }}
                />
              </div>
            </label>

            {/* Selected file chips */}
            {files.length > 0 ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-[var(--color-text-secondary)]">待上传（{files.length}）</span>
                  <button
                    type="button"
                    disabled={isRunning}
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
                      <span className="max-w-[140px] truncate" title={file.name}>{file.name}</span>
                      <button
                        type="button"
                        disabled={isRunning}
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
                <Input placeholder="如 math2 / exam408" value={subject} disabled={isRunning} onChange={(event) => setSubject(event.target.value)} />
              </label>
              <div className="space-y-1">
                <span className="text-xs font-semibold text-[var(--color-text-secondary)]">并发数</span>
                <div className="relative" ref={selectRef}>
                  <button
                    type="button"
                    disabled={isRunning}
                    onClick={() => setSelectOpen((prev) => !prev)}
                    className={`h-11 w-full rounded-xl border px-3 text-sm outline-none transition-all duration-200 flex items-center justify-between gap-2 ${
                      isRunning
                        ? "border-[var(--color-border)] bg-[var(--color-bg-input)] opacity-50 cursor-not-allowed"
                        : selectOpen
                          ? "border-[var(--color-primary)] bg-white ring-4 ring-[rgba(91,123,154,0.14)]"
                          : "border-[var(--color-border)] bg-[var(--color-bg-input)] hover:border-[var(--color-primary)] hover:bg-white"
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <span className="font-semibold text-[var(--ink)]">{concurrency}</span>
                      {concurrency === "1" && <span className="text-[10px] font-semibold leading-none text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded">最稳</span>}
                      {concurrency === "2" && <span className="text-[10px] font-semibold leading-none text-green-700 bg-green-50 px-1.5 py-0.5 rounded">推荐</span>}
                      {concurrency === "4" && <span className="text-[10px] font-semibold leading-none text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded">最快</span>}
                    </span>
                    <ChevronDown className={`h-4 w-4 text-[var(--color-text-hint)] transition-transform duration-200 ${selectOpen ? "rotate-180" : ""}`} />
                  </button>

                  {selectOpen && (
                    <div
                      className="absolute top-full left-0 right-0 z-50 mt-1.5 surface-card rounded-xl overflow-hidden p-1 animate-drop-in"
                      onKeyDown={(e) => { if (e.key === "Escape") setSelectOpen(false); }}
                    >
                      {[
                        { value: "1", label: "1", tag: "最稳", tagClass: "bg-amber-50 text-amber-700" },
                        { value: "2", label: "2", tag: "推荐", tagClass: "bg-green-50 text-green-700" },
                        { value: "3", label: "3", tag: null, tagClass: "" },
                        { value: "4", label: "4", tag: "最快", tagClass: "bg-indigo-50 text-indigo-700" },
                      ].map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => { setConcurrency(opt.value); setSelectOpen(false); }}
                          className={`w-full flex items-center justify-between gap-2 rounded-lg px-3 py-2.5 text-sm transition-all duration-150 ${
                            concurrency === opt.value
                              ? "bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]"
                              : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-input)] hover:text-[var(--ink)]"
                          }`}
                        >
                          <span className="flex items-center gap-2">
                            <span className={`font-semibold ${concurrency === opt.value ? "text-[var(--color-primary-dark)]" : "text-[var(--ink)]"}`}>{opt.label}</span>
                            {opt.tag && <span className={`text-[10px] font-semibold leading-none px-1.5 py-0.5 rounded ${opt.tagClass}`}>{opt.tag}</span>}
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

            {/* Submit */}
            <div className="flex items-center justify-end gap-3 border-t border-[var(--color-border)] pt-4">
              <Button
                disabled={files.length === 0 || uploadMutation.isPending || isRunning}
                onClick={() => uploadMutation.mutate()}
                className="h-11 px-5"
              >
                <UploadCloud className="h-4 w-4" />
                {uploadMutation.isPending ? "上传中..." : isRunning ? "识别中..." : `开始导入${files.length > 0 ? `（${files.length}）` : ""}`}
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* ===== Right: 任务进度 ===== */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <h3 className="font-display text-xl font-bold text-[var(--ink)]">{jobId ? "任务进度" : "准备就绪"}</h3>
              <p className="mt-0.5 text-xs text-[var(--color-text-secondary)]">
                {jobId ? "实时追踪每张图片的识别状态" : "选择图片后点击「开始导入」"}
              </p>
            </div>
            {jobId ? (
              <Button variant="secondary" disabled={statusQuery.isFetching} onClick={() => statusQuery.refetch()} className="shrink-0">
                <RefreshCw className={`h-3.5 w-3.5 ${statusQuery.isFetching ? "animate-spin" : ""}`} />
              </Button>
            ) : null}
          </CardHeader>
          <CardContent>
            {!jobId ? (
              <div className="flex flex-col items-center py-8 text-center">
                <Images className="mb-3 h-9 w-9 text-[var(--color-text-hint)]" />
                <p className="text-sm font-semibold text-[var(--color-text-secondary)]">等待任务提交</p>
                <p className="mt-1 max-w-xs text-xs leading-relaxed text-[var(--color-text-hint)]">
                  提交后将在此处显示总数 / 已完成 / 处理中 / 等待中，以及每张图片的识别结果。
                </p>
              </div>
            ) : null}

            {jobId && !status && !statusQuery.isError ? (
              <div className="flex items-center gap-3 rounded-2xl border border-[var(--color-border)] bg-white/70 px-4 py-6 text-sm text-[var(--color-text-secondary)]">
                <RefreshCw className="h-4 w-4 animate-spin" />
                正在获取任务进度...
              </div>
            ) : null}

            {status ? (
              <div className="space-y-4">
                {/* Status row */}
                <div className="flex flex-wrap items-center gap-2">
                  {isRunning ? (
                    <span className="flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">
                      <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-amber-500" />
                      识别中
                    </span>
                  ) : (
                    <span className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${
                      status.status === "failed" ? "bg-red-50 text-red-700" : "bg-green-50 text-green-700"
                    }`}>
                      <span className={`inline-block h-2 w-2 rounded-full ${status.status === "failed" ? "bg-red-500" : "bg-green-500"}`} />
                      {status.status === "failed" ? "已结束（有失败）" : "已完成"}
                    </span>
                  )}
                  {isRunning && status.current_file ? (
                    <span className="rounded-full bg-[var(--color-bg-input)] px-2.5 py-0.5 text-[10px] font-medium text-[var(--color-text-secondary)]">
                      第 {status.current_seq}/{total} 张 · {status.current_file}
                    </span>
                  ) : null}
                </div>

                {/* Progress bar */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between text-[10px] text-[var(--color-text-hint)]">
                    <span>整体进度</span>
                    <span>{completed}/{total}（{progressPct}%）</span>
                  </div>
                  <div className="overflow-hidden rounded-full bg-[var(--color-bg-input)]">
                    <div className="h-2.5 rounded-full bg-gradient-to-r from-[var(--color-primary)] to-[#7b9bbb] transition-all duration-700" style={{ width: `${progressPct}%` }} />
                  </div>
                </div>

                {/* Counters: 总数 / 处理中 / 等待中 / 成功 / 失败 */}
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {[
                    ["总数", total, "text-[var(--ink)]"],
                    ["处理中", status.processing, "text-amber-600"],
                    ["等待中", status.pending, "text-[var(--color-text-secondary)]"],
                    ["成功", status.succeeded, "text-green-600"],
                    ["失败", status.failed, "text-red-600"],
                    ["生成题目", status.total_questions, "text-[var(--color-primary-dark)]"],
                  ].map(([label, value, tone]) => (
                    <div key={String(label)} className="rounded-xl border border-[var(--color-border)] bg-white/70 p-2.5 text-center">
                      <p className={`text-lg font-bold ${tone}`}>{Number(value ?? 0)}</p>
                      <p className="mt-0.5 text-[10px] text-[var(--color-text-hint)]">{label}</p>
                    </div>
                  ))}
                </div>

                {/* Result summary (terminal only) */}
                {isDone ? (
                  <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-primary-light)]/40 px-4 py-3 text-sm text-[var(--color-text-secondary)]">
                    本次共 <b className="text-[var(--ink)]">{total}</b> 张图片，成功{" "}
                    <b className="text-green-600">{status.succeeded}</b>，失败{" "}
                    <b className="text-red-600">{status.failed}</b>，生成{" "}
                    <b className="text-[var(--color-primary-dark)]">{status.total_questions}</b> 道题。
                  </div>
                ) : null}

                {/* Per-item list */}
                {status.items.length > 0 ? (
                  <div className="space-y-1.5">
                    <span className="text-xs font-semibold text-[var(--color-text-secondary)]">明细</span>
                    <div className="max-h-72 space-y-1.5 overflow-auto">
                      {status.items.map((item) => (
                        <div key={item.id} className="flex items-center gap-2 rounded-xl border border-[var(--color-border)] bg-white/70 px-3 py-2 text-xs">
                          <span className="w-6 shrink-0 font-mono text-[10px] text-[var(--color-text-hint)]">#{item.seq}</span>
                          <span className="min-w-0 flex-1 truncate text-[var(--color-text-secondary)]" title={item.source_file ?? ""}>
                            {item.source_file ?? "—"}
                          </span>
                          {item.status === "succeeded" ? (
                            <span className="shrink-0 rounded-full bg-green-50 px-2 py-0.5 text-[10px] font-semibold text-green-700">成功 · {item.question_count}题</span>
                          ) : item.status === "failed" ? (
                            <span className="shrink-0 rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-semibold text-red-700" title={item.error_message ?? ""}>失败</span>
                          ) : item.status === "processing" ? (
                            <span className="shrink-0 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">处理中</span>
                          ) : (
                            <span className="shrink-0 rounded-full bg-[var(--color-bg-input)] px-2 py-0.5 text-[10px] font-semibold text-[var(--color-text-secondary)]">等待中</span>
                          )}
                          {item.status === "failed" && item.has_ocr_cache ? (
                            <button
                              type="button"
                              disabled={reparseMutation.isPending}
                              onClick={() => reparseMutation.mutate(item.id)}
                              className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-[var(--color-border)] px-2 py-0.5 text-[10px] font-semibold text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary)] hover:text-[var(--color-primary-dark)] disabled:opacity-40"
                              title="基于缓存的 OCR 文本重新解析，不重复识别"
                            >
                              <RefreshCw className={`h-3 w-3 ${reparseMutation.isPending && reparseMutation.variables === item.id ? "animate-spin" : ""}`} />
                              重解析
                            </button>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                {/* Quick link to review queue */}
                {isDone && status.succeeded > 0 ? (
                  <div className="flex flex-wrap gap-2 border-t border-[var(--color-border)] pt-3">
                    <a
                      className="inline-flex h-8 items-center gap-1.5 rounded-xl border border-[var(--color-border)] bg-white/70 px-3 text-[10px] font-semibold text-[var(--color-text-secondary)] transition hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)]"
                      href="/imports/review"
                    >
                      <ClipboardCheck className="h-3 w-3" />
                      前往待审核
                    </a>
                  </div>
                ) : null}
              </div>
            ) : null}

            {statusQuery.isError ? (
              <div className="flex items-center gap-2.5 rounded-2xl border border-[var(--color-danger)] bg-red-50/70 px-4 py-3 text-xs text-[var(--color-danger)]">
                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                无法获取任务进度，请刷新重试。
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}




/**
 * Pure helpers for batch-image import page, extracted from
 * batch-image/page.tsx. Covers file deduplication, task progress
 * calculation, and batch statistics aggregation.
 */

export const IMAGE_MIME = /^image\/(jpeg|png|webp)$/;
export const MAX_FILES = (() => {
  const n = Number(process.env.NEXT_PUBLIC_BATCH_IMAGE_MAX_FILES);
  return Number.isFinite(n) && n > 0 ? n : 50;
})();
export const DEFAULT_CONCURRENCY = (() => {
  const n = Number(process.env.NEXT_PUBLIC_BATCH_IMAGE_DEFAULT_CONCURRENCY);
  return Number.isFinite(n) && n >= 1 && n <= 4 ? String(Math.floor(n)) : "2";
})();

export type TraceEvent = {
  step: string;
  status: string;
  message?: string;
  timestamp?: string;
};

export type ImageTask = {
  id: string;
  status: "pending" | "uploading" | "processing" | "succeeded" | "failed";
  jobId: string | null;
  traceEvents: TraceEvent[];
  questionCount: number;
};

export type BatchStats = {
  succeededCount: number;
  failedCount: number;
  totalQuestions: number;
  uploadingCount: number;
  processingCount: number;
  totalProgress: number;
};

/**
 * Merge incoming files into existing, deduplicating by name+size and
 * filtering to valid image MIME types. Caps at MAX_FILES.
 */
export function dedupeFiles(existing: File[], incoming: File[]): File[] {
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

/**
 * Calculate progress percentage for an image task based on status and trace events.
 */
export function taskProgress(task: ImageTask): number {
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

/**
 * Aggregate batch statistics from a list of image tasks.
 */
export function computeBatchStats(tasks: ImageTask[]): BatchStats {
  const totalImages = tasks.length;
  const succeededCount = tasks.filter((t) => t.status === "succeeded").length;
  const failedCount = tasks.filter((t) => t.status === "failed").length;
  const totalQuestions = tasks.reduce((s, t) => s + t.questionCount, 0);
  const uploadingCount = tasks.filter((t) => t.status === "uploading").length;
  const processingCount = tasks.filter((t) => t.status === "processing").length;
  const totalProgress = totalImages
    ? Math.round(tasks.reduce((sum, task) => sum + taskProgress(task), 0) / totalImages)
    : 0;
  return { succeededCount, failedCount, totalQuestions, uploadingCount, processingCount, totalProgress };
}

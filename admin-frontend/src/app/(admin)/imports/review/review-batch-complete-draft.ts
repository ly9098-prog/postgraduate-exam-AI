export const BATCH_COMPLETE_DRAFT_KEY = "batch-complete-draft";

export const BATCH_COMPLETE_ALL_FIELDS = [
  "answer",
  "analysis",
  "knowledge_points",
  "difficulty",
  "subject_id",
  "question_type",
  "stem",
  "options",
  "tips",
  "tags",
] as const;

const DEFAULT_BATCH_COMPLETE_FIELDS = BATCH_COMPLETE_ALL_FIELDS.slice(0, 4);

export type BatchCompleteStrategy = "fill_empty" | "force_overwrite";

export type BatchCompleteDraft = {
  fields: string[];
  strategy: BatchCompleteStrategy;
};

export type BatchCompleteDraftStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;
export type BatchCompleteDraftStorageProvider = () => BatchCompleteDraftStorage;

export function createDefaultBatchCompleteDraft(): BatchCompleteDraft {
  return {
    fields: [...DEFAULT_BATCH_COMPLETE_FIELDS],
    strategy: "fill_empty",
  };
}

export function toggleBatchCompleteField(fields: string[], field: string): string[] {
  return fields.includes(field)
    ? fields.filter((item) => item !== field)
    : [...fields, field];
}

export function saveBatchCompleteDraft(
  getStorage: BatchCompleteDraftStorageProvider,
  fields: string[],
  strategy: BatchCompleteStrategy,
  now: () => number = Date.now,
): void {
  try {
    getStorage().setItem(
      BATCH_COMPLETE_DRAFT_KEY,
      JSON.stringify({ fields, strategy, savedAt: now() }),
    );
  } catch {
    // Storage may be unavailable or over quota; draft persistence is best effort.
  }
}

export function clearBatchCompleteDraft(
  getStorage: BatchCompleteDraftStorageProvider,
): void {
  try {
    getStorage().removeItem(BATCH_COMPLETE_DRAFT_KEY);
  } catch {
    // Storage may be unavailable; the in-memory form remains usable.
  }
}

export function loadBatchCompleteDraft(
  getStorage: BatchCompleteDraftStorageProvider,
): BatchCompleteDraft | null {
  try {
    const raw = getStorage().getItem(BATCH_COMPLETE_DRAFT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { fields?: unknown; strategy?: unknown } | null;
    if (!parsed || !Array.isArray(parsed.fields)) return null;
    return {
      fields: parsed.fields as string[],
      strategy: parsed.strategy === "force_overwrite" ? "force_overwrite" : "fill_empty",
    };
  } catch {
    return null;
  }
}

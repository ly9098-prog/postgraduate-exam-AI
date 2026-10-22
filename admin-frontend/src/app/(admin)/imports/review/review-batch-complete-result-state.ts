import type { BatchCompleteResponse, BatchCompleteResponseItem } from "@/lib/api/types";

export type BatchCompleteResultItem = {
  item: BatchCompleteResponseItem;
  isFailed: boolean;
  label: string;
  containerClass: string;
  labelClass: string;
  errorClass: string;
};

export type BatchCompleteResultState = {
  summary: string;
  nonSuccessItems: BatchCompleteResultItem[];
};

export function buildBatchCompleteResultState(
  result: BatchCompleteResponse | null,
): BatchCompleteResultState | null {
  if (!result) return null;
  return {
    summary: ` · 完成 ${result.succeeded} / 失败 ${result.failed} / 跳过 ${result.skipped}`,
    nonSuccessItems: result.items
      .filter((item) => item.status !== "success")
      .map((item) => {
        const isFailed = item.status === "failed";
        return {
          item,
          isFailed,
          label: isFailed ? "失败" : "跳过",
          containerClass: isFailed
            ? "border-[var(--color-danger)]/40 bg-[var(--color-danger-light)]/30"
            : "border-[var(--color-border)] bg-white/60",
          labelClass: isFailed
            ? "text-[var(--color-danger)]"
            : "text-[var(--color-text-hint)]",
          errorClass: isFailed
            ? "text-[var(--color-danger)]"
            : "text-[var(--color-text-secondary)]",
        };
      }),
  };
}

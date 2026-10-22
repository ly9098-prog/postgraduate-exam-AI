import { describe, expect, it } from "vitest";
import type { BatchCompleteResponse, BatchCompleteResponseItem } from "@/lib/api/types";
import { buildBatchCompleteResultState } from "./review-batch-complete-result-state";

const response = (items: BatchCompleteResponseItem[]): BatchCompleteResponse => ({
  total: items.length,
  succeeded: items.filter((item) => item.status === "success").length,
  failed: items.filter((item) => item.status === "failed").length,
  skipped: items.filter((item) => item.status === "skipped").length,
  items,
});

describe("review batch complete result state", () => {
  it("returns null before a result exists", () => {
    expect(buildBatchCompleteResultState(null)).toBeNull();
  });

  it("keeps summary text and excludes successful rows without reordering", () => {
    const state = buildBatchCompleteResultState(response([
      { import_id: 9, status: "skipped", completed_fields: [] },
      { import_id: 3, status: "success", completed_fields: ["answer"] },
      { import_id: 4, status: "failed", error: "bad", completed_fields: [] },
      { import_id: 7, status: "future", completed_fields: [] },
    ]))!;

    expect(state.summary).toBe(" · 完成 1 / 失败 1 / 跳过 1");
    expect(state.nonSuccessItems.map(({ item }) => item.import_id)).toEqual([9, 4, 7]);
  });

  it("maps failed and skipped display classes independently of the row status text", () => {
    const state = buildBatchCompleteResultState(response([
      { import_id: 1, status: "failed", error: "failure", completed_fields: [] },
      { import_id: 2, status: "skipped", error: "skipped", completed_fields: [] },
      { import_id: 3, status: "future", completed_fields: [] },
    ]))!;

    expect(state.nonSuccessItems.map(({ isFailed, label, containerClass, labelClass, errorClass }) => ({
      isFailed,
      label,
      containerClass,
      labelClass,
      errorClass,
    }))).toEqual([
      {
        isFailed: true,
        label: "失败",
        containerClass: "border-[var(--color-danger)]/40 bg-[var(--color-danger-light)]/30",
        labelClass: "text-[var(--color-danger)]",
        errorClass: "text-[var(--color-danger)]",
      },
      {
        isFailed: false,
        label: "跳过",
        containerClass: "border-[var(--color-border)] bg-white/60",
        labelClass: "text-[var(--color-text-hint)]",
        errorClass: "text-[var(--color-text-secondary)]",
      },
      {
        isFailed: false,
        label: "跳过",
        containerClass: "border-[var(--color-border)] bg-white/60",
        labelClass: "text-[var(--color-text-hint)]",
        errorClass: "text-[var(--color-text-secondary)]",
      },
    ]);
  });

  it("retains unknown status rows as non-success entries", () => {
    const state = buildBatchCompleteResultState(response([
      { import_id: 8, status: "", error: "", completed_fields: [] },
    ]))!;
    expect(state.nonSuccessItems).toHaveLength(1);
    expect(state.nonSuccessItems[0].item.status).toBe("");
    expect(state.nonSuccessItems[0].isFailed).toBe(false);
  });
});

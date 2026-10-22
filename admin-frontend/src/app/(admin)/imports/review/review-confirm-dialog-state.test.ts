import { describe, expect, it } from "vitest";
import type { ReviewActionState } from "./review-action-requests";
import { buildReviewConfirmDialogState } from "./review-confirm-dialog-state";

const actions: Array<ReviewActionState | null> = [
  null,
  { action: "approve", id: 1 },
  { action: "reject", id: 2 },
  { action: "batch-approve" },
  { action: "batch-reject" },
  { action: "low-risk-batch-approve" },
];

describe("review confirm dialog state", () => {
  it.each([null, ...actions])("preserves copy and tone for %j", (action) => {
    const state = buildReviewConfirmDialogState(action, 0);
    const label = action?.action ?? "";

    expect(state.title).toBe(
      label === "low-risk-batch-approve"
        ? "批量通过低风险题"
        : label.includes("reject") ? "驳回导入题目" : "通过导入题目",
    );
    expect(state.confirmText).toBe(
      label === "low-risk-batch-approve"
        ? "批量通过低风险"
        : label.includes("reject") ? "驳回" : "通过",
    );
    expect(state.danger).toBe(label.includes("reject"));
    expect(state.showRejectReason).toBe(label === "reject" || label === "batch-reject");
    expect(state.description).toBe(
      label === "low-risk-batch-approve"
        ? "将自动通过当前批次中所有低风险题（risk_level=low）并跳过高风险和需检查题。高风险和需检查题不会被通过。"
        : "操作会更新 question_imports 暂存审核状态。",
    );
  });

  it.each([1, 2, 7, 50])("uses selected count only for selected batch actions: %i", (count) => {
    expect(buildReviewConfirmDialogState({ action: "batch-approve" }, count).description)
      .toBe(`将对已选的 ${count} 条导入题目执行批量通过操作。`);
    expect(buildReviewConfirmDialogState({ action: "batch-reject" }, count).description)
      .toBe(`将对已选的 ${count} 条导入题目执行批量驳回操作。`);
    expect(buildReviewConfirmDialogState({ action: "low-risk-batch-approve" }, count).description)
      .not.toContain(`已选`);
  });

  it("rejects malformed action labels the same way as the original optional chain", () => {
    const malformed = { action: undefined } as unknown as ReviewActionState;
    expect(() => buildReviewConfirmDialogState(malformed, 1)).toThrow(TypeError);
  });
});

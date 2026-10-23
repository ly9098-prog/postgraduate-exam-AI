import { describe, expect, it } from "vitest";
import { buildQuestionDeleteFeedback } from "./question-delete-feedback";

describe("buildQuestionDeleteFeedback", () => {
  it("reports a single deletion and closes the detail drawer", () => {
    expect(buildQuestionDeleteFeedback({
      result: { status: "deleted" },
      intent: { action: "delete", id: 7 },
      selectedQuestionId: 7,
    })).toEqual({
      message: "题目 #7 已删除。",
      clearSelection: true,
      closeDetailDrawer: true,
    });
  });

  it("normalizes legacy batch result field names", () => {
    expect(buildQuestionDeleteFeedback({
      result: {
        successIds: [1, 2],
        failedItems: [
          { id: 3, error: "被试卷引用" },
          { id: 4, error: "无权限" },
        ],
      },
      intent: { action: "batch-delete" },
      selectedQuestionId: 1,
    })).toEqual({
      message: "批量删除完成，成功 2 条，失败 2 条：#3 被试卷引用；#4 无权限。",
      clearSelection: true,
      closeDetailDrawer: true,
    });
  });

  it("keeps the drawer open when the selected question is not deleted", () => {
    expect(buildQuestionDeleteFeedback({
      result: { success_ids: [8], failed_items: [{ id: 9, error: "被试卷引用" }] },
      intent: { action: "batch-delete" },
      selectedQuestionId: 9,
    })).toEqual({
      message: "批量删除完成，成功 1 条，失败 1 条：#9 被试卷引用。",
      clearSelection: true,
      closeDetailDrawer: false,
    });
  });

  it("truncates the failure preview after five items", () => {
    const feedback = buildQuestionDeleteFeedback({
      result: {
        success_ids: [],
        failed_items: [1, 2, 3, 4, 5, 6].map((id) => ({ id, error: `错误${id}` })),
      },
      intent: { action: "batch-delete" },
      selectedQuestionId: null,
    });

    expect(feedback.message).toBe(
      "批量删除完成，成功 0 条，失败 6 条：#1 错误1；#2 错误2；#3 错误3；#4 错误4；#5 错误5；…。",
    );
    expect(feedback.closeDetailDrawer).toBe(false);
  });
});

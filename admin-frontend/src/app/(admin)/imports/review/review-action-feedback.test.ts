import { describe, expect, it } from "vitest";
import type { ImportActionResponse } from "@/lib/api/types";
import type {
  ReviewActionState,
  ReviewBatchActionResult,
} from "./review-action-requests";
import { buildReviewActionFeedback } from "./review-action-feedback";

const singleResult = {
  id: 7,
  status: "approved",
  affected_count: 1,
} as ImportActionResponse;

const batchResult: ReviewBatchActionResult = {
  affected_count: 2,
  errors: [
    { id: 9, message: "conflict" },
    { id: 4, message: "forbidden" },
  ],
};

function feedback(result: unknown, action: ReviewActionState) {
  return buildReviewActionFeedback(
    result as Parameters<typeof buildReviewActionFeedback>[0],
    action,
  );
}

describe("review action feedback", () => {
  it("preserves single approve and reject copy and drawer closure", () => {
    expect(feedback(singleResult, { action: "approve", id: 7 })).toEqual({
      message: "导入题目 #7 已通过审核。",
      closeDrawer: true,
    });
    expect(feedback(singleResult, { action: "reject", id: 8 })).toEqual({
      message: "导入题目 #8 已驳回。",
      closeDrawer: true,
    });
  });

  it("preserves partial failure order and selected-batch summaries", () => {
    expect(feedback(batchResult, { action: "batch-approve" })).toEqual({
      message: "批量审核通过部分完成：成功 2，失败 2（#9、#4）。",
      closeDrawer: false,
    });
    expect(feedback(batchResult, { action: "batch-reject" })).toEqual({
      message: "批量驳回部分完成：成功 2，失败 2（#9、#4）。",
      closeDrawer: false,
    });
  });

  it("preserves whole-batch success and the missing affected_count fallback", () => {
    expect(feedback({
      batch_id: "batch",
      status: "approved",
      affected_count: 3,
    }, { action: "batch-approve" })).toEqual({
      message: "批量审核通过完成，影响 3 条导入题目。",
      closeDrawer: false,
    });
    expect(feedback({
      status: "rejected",
    }, { action: "batch-reject" })).toEqual({
      message: "批量驳回完成，影响 0 条导入题目。",
      closeDrawer: false,
    });
  });

  it("treats an empty errors array as a successful batch and does not skip the feedback", () => {
    expect(feedback({
      status: "approved",
      affected_count: 6,
      errors: [],
    }, { action: "batch-approve" })).toEqual({
      message: "批量审核通过完成，影响 6 条导入题目。",
      closeDrawer: false,
    });
  });

  it("returns defensive feedback for an unknown runtime action without closing the drawer", () => {
    expect(feedback({ affected_count: 1 }, {
      action: "unknown",
    } as unknown as ReviewActionState)).toEqual({
      message: "操作已完成，但未识别的审核动作；请刷新后确认审核结果。",
      closeDrawer: false,
    });
  });

  it("preserves low-risk counts and the skipped-reason suffix threshold", () => {
    expect(feedback({
      affected_count: 4,
      skipped_count: 2,
      skipped_reasons: ["#1: high", "#2: visual"],
    }, { action: "low-risk-batch-approve" })).toEqual({
      message: "低风险批量通过完成：通过 4 题，跳过 2 题（部分高风险/需检查题已跳过）",
      closeDrawer: false,
    });
    expect(feedback({
      affected_count: 5,
      skipped_count: 0,
      skipped_reasons: [],
    }, { action: "low-risk-batch-approve" })).toEqual({
      message: "低风险批量通过完成：通过 5 题，跳过 0 题",
      closeDrawer: false,
    });
  });
});

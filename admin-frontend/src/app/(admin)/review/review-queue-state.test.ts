import { describe, expect, it } from "vitest";
import type { AdminQuestionDetail, QuestionVersionDetail } from "@/lib/api/types";
import {
  buildReviewDiff,
  buildReviewPaginationViewport,
  buildReviewQuery,
  createReviewIdempotencyKey,
  formatBatchReviewMessage,
  normalizeBatchResult,
  pruneReviewSelection,
  reviewDifficultyLabel,
  reviewReasonError,
  reviewRequiresReason,
  reviewStatusLabel,
  toggleAllReviewSelection,
  toggleReviewSelection,
} from "./review-queue-state";

const question: AdminQuestionDetail = {
  id: 7,
  question_type: "single_choice",
  content: { stem: "new stem" },
  options: { A: "1", B: "2" },
  answer: "A",
  analysis: "new analysis",
  knowledge_points: ["栈"],
  difficulty: 3,
  review_status: "re_pending",
  is_active: false,
};

const version: QuestionVersionDetail = {
  id: 21,
  question_id: 7,
  version: 2,
  edited_by: 1,
  edited_by_name: "admin",
  content: { stem: "old stem" },
  options: { A: "1", B: "2" },
  answer: "B",
  analysis: "old analysis",
  difficulty: 3,
  knowledge_points: ["队列"],
};

describe("buildReviewQuery", () => {
  it("includes the queue tab and pagination", () => {
    expect(
      buildReviewQuery({
        tab: "re_pending",
        keyword: "",
        subjectId: "",
        page: 2,
        pageSize: 20,
      }),
    ).toEqual({ page: 2, page_size: 20, review_status: "re_pending" });
  });

  it("trims the keyword and adds a numeric subject filter", () => {
    expect(
      buildReviewQuery({
        tab: "rejected",
        keyword: "  进程  ",
        subjectId: "12",
        page: 1,
        pageSize: 50,
      }),
    ).toEqual({
      page: 1,
      page_size: 50,
      review_status: "rejected",
      keyword: "进程",
      subject_id: 12,
    });
  });

  it("omits invalid subject values", () => {
    expect(
      buildReviewQuery({
        tab: "re_pending",
        keyword: "",
        subjectId: "abc",
        page: 1,
        pageSize: 20,
      }),
    ).not.toHaveProperty("subject_id");
  });
});

describe("review reasons", () => {
  it("requires a reason only for reject and rollback actions", () => {
    expect(reviewRequiresReason("approve")).toBe(false);
    expect(reviewRequiresReason("batch-approve")).toBe(false);
    expect(reviewRequiresReason("reject")).toBe(true);
    expect(reviewRequiresReason("batch-reject")).toBe(true);
    expect(reviewRequiresReason("rollback")).toBe(true);
  });

  it("reports missing reasons with action-specific copy", () => {
    expect(reviewReasonError("reject", "   ")).toBe("请填写拒绝原因");
    expect(reviewReasonError("batch-reject", "")).toBe("请填写拒绝原因");
    expect(reviewReasonError("rollback", "")).toBe("请填写回滚原因");
  });

  it("rejects over-long reasons and accepts valid ones", () => {
    expect(reviewReasonError("reject", "x".repeat(257))).toContain("256");
    expect(reviewReasonError("reject", "重复题")).toBeNull();
    expect(reviewReasonError("approve", "")).toBeNull();
  });
});

describe("buildReviewDiff", () => {
  it("returns no rows without a baseline", () => {
    expect(buildReviewDiff(question, null)).toEqual([]);
  });

  it("marks changed fields and keeps equal fields unchanged", () => {
    const rows = buildReviewDiff(question, version);
    expect(rows.map((row) => row.key)).toEqual([
      "stem",
      "options",
      "answer",
      "analysis",
      "difficulty",
      "knowledge_points",
    ]);
    expect(rows.filter((row) => row.changed).map((row) => row.label)).toEqual([
      "题干",
      "答案",
      "解析",
      "知识点",
    ]);
    expect(rows.find((row) => row.key === "options")?.changed).toBe(false);
    expect(rows.find((row) => row.key === "difficulty")?.changed).toBe(false);
  });
});

describe("batch feedback", () => {
  it("normalizes snake_case and camelCase result shapes", () => {
    expect(normalizeBatchResult({ success_ids: [1], failed_items: [] })).toEqual({
      successIds: [1],
      failedItems: [],
    });
    expect(
      normalizeBatchResult({ successIds: [2], failedItems: [{ id: 3, error: "bad" }] }),
    ).toEqual({ successIds: [2], failedItems: [{ id: 3, error: "bad" }] });
  });

  it("reports a clean batch without claiming more than the payload", () => {
    expect(
      formatBatchReviewMessage("approved", { success_ids: [1, 2], failed_items: [] }),
    ).toBe("批量通过完成：成功 2 项，无失败项。");
  });

  it("surfaces failed ids and reasons", () => {
    const message = formatBatchReviewMessage("rejected", {
      success_ids: [1],
      failed_items: [
        { id: 2, error: "该题目当前状态不能执行此审核操作" },
        { id: 3, error: "拒绝原因不能为空" },
      ],
    });
    expect(message).toContain("成功 1 项");
    expect(message).toContain("失败 2 项");
    expect(message).toContain("#2 该题目当前状态不能执行此审核操作");
    expect(message).toContain("#3 拒绝原因不能为空");
  });
});

describe("selection helpers", () => {
  it("toggles one id and respects the batch cap", () => {
    const current = new Set([1, 2]);
    expect(toggleReviewSelection(current, 3)).toEqual(new Set([1, 2, 3]));
    expect(toggleReviewSelection(current, 1)).toEqual(new Set([2]));
    const full = new Set(Array.from({ length: 50 }, (_, index) => index + 1));
    expect(toggleReviewSelection(full, 99)).toBe(full);
  });

  it("selects and deselects the visible page", () => {
    expect(toggleAllReviewSelection(new Set(), [1, 2])).toEqual(new Set([1, 2]));
    expect(toggleAllReviewSelection(new Set([1, 2]), [1, 2])).toEqual(new Set());
    expect(toggleAllReviewSelection(new Set([1]), [1, 2])).toEqual(new Set([1, 2]));
  });

  it("prunes invisible ids and preserves the reference when unchanged", () => {
    const current = new Set([1, 2]);
    expect(pruneReviewSelection(current, [{ id: 1 }, { id: 2 }])).toBe(current);
    expect(pruneReviewSelection(current, [{ id: 2 }])).toEqual(new Set([2]));
    expect(pruneReviewSelection(current, [])).toBe(current);
  });
});

describe("pagination viewport", () => {
  it("returns no pages when empty", () => {
    expect(buildReviewPaginationViewport(1, 0)).toEqual([]);
  });

  it("keeps a five-page window around the current page", () => {
    expect(buildReviewPaginationViewport(1, 3)).toEqual([1, 2, 3]);
    expect(buildReviewPaginationViewport(6, 10)).toEqual([4, 5, 6, 7, 8]);
    expect(buildReviewPaginationViewport(10, 10)).toEqual([6, 7, 8, 9, 10]);
  });
});

describe("reviewStatusLabel", () => {
  it("maps queue statuses to Chinese labels", () => {
    expect(reviewStatusLabel("re_pending")).toBe("待重审");
    expect(reviewStatusLabel("rejected")).toBe("已驳回");
    expect(reviewStatusLabel("approved")).toBe("已通过");
    expect(reviewStatusLabel(null)).toBe("未知状态");
  });
});

describe("reviewDifficultyLabel", () => {
  it("maps 1–5 to Chinese labels and clamps out-of-range values", () => {
    expect(reviewDifficultyLabel(1)).toBe("简单");
    expect(reviewDifficultyLabel(3)).toBe("中等");
    expect(reviewDifficultyLabel(5)).toBe("困难");
    expect(reviewDifficultyLabel(0)).toBe("简单");
    expect(reviewDifficultyLabel(99)).toBe("困难");
  });

  it("accepts numeric strings and returns a placeholder for empty values", () => {
    expect(reviewDifficultyLabel("4")).toBe("较难");
    expect(reviewDifficultyLabel(null)).toBe("—");
    expect(reviewDifficultyLabel(undefined)).toBe("—");
    expect(reviewDifficultyLabel("")).toBe("—");
  });
});

describe("createReviewIdempotencyKey", () => {
  it("builds a header-safe key from the supplied uuid", () => {
    const key = createReviewIdempotencyKey(
      () => "11111111-1111-4111-8111-111111111111",
    );
    expect(key).toBe("review-batch-11111111-1111-4111-8111-111111111111");
    expect(key.length).toBeLessThanOrEqual(128);
    expect(key).not.toMatch(/\s/);
  });
});

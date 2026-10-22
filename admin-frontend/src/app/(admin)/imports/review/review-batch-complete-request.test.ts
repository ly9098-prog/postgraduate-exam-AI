import { describe, expect, it } from "vitest";
import type { BatchCompleteResponse } from "@/lib/api/types";
import {
  buildBatchCompleteFeedback,
  validateBatchCompleteRequest,
} from "./review-batch-complete-request";

describe("validateBatchCompleteRequest", () => {
  it("rejects empty import IDs", () => {
    expect(validateBatchCompleteRequest([], ["answer"], "fill_empty"))
      .toEqual({ ok: false, message: "请先选择需要补全的题目。" });
  });

  it("rejects empty fields", () => {
    expect(validateBatchCompleteRequest([1, 2], [], "fill_empty"))
      .toEqual({ ok: false, message: "请选择至少一个补全字段。" });
  });

  it("passes valid request with args", () => {
    const result = validateBatchCompleteRequest([1, 2], ["answer", "analysis"], "force_overwrite");
    expect(result).toEqual({
      ok: true,
      args: { importIds: [1, 2], fields: ["answer", "analysis"], strategy: "force_overwrite" },
    });
  });
});

describe("buildBatchCompleteFeedback", () => {
  it("builds message with all success", () => {
    const result = { total: 3, succeeded: 3, failed: 0, skipped: 0, items: [] } as BatchCompleteResponse;
    expect(buildBatchCompleteFeedback(result)).toBe("批量补全完成：成功 3，失败 0，跳过 0");
  });

  it("appends failed IDs when failures exist", () => {
    const result = {
      total: 3, succeeded: 1, failed: 2, skipped: 0,
      items: [
        { import_id: 5, status: "failed", completed_fields: [] },
        { import_id: 8, status: "failed", completed_fields: [] },
        { import_id: 3, status: "success", completed_fields: ["answer"] },
      ],
    } as unknown as BatchCompleteResponse;
    expect(buildBatchCompleteFeedback(result)).toBe("批量补全完成：成功 1，失败 2，跳过 0（#5、#8）");
  });
});

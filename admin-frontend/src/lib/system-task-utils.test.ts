import { describe, it, expect } from "vitest";
import {
  statusLabelZh,
  asyncTaskName,
  taskStatusMeta,
  runResultMeta,
  taskMatchesStatus,
  computeQueueTotal,
  computeFailedQueueTotal,
} from "./system-task-utils";

describe("statusLabelZh", () => {
  it("maps known status", () => {
    expect(statusLabelZh("pending")).toBe("待发布");
    expect(statusLabelZh("failed")).toBe("失败");
  });
  it("returns 未知 for null/undefined", () => {
    expect(statusLabelZh(null)).toBe("未知");
    expect(statusLabelZh(undefined)).toBe("未知");
    expect(statusLabelZh("")).toBe("未知");
  });
  it("returns raw value for unknown", () => {
    expect(statusLabelZh("custom_status")).toBe("custom_status");
  });
  it("is case-insensitive", () => {
    expect(statusLabelZh("PENDING")).toBe("待发布");
  });
  it("handles not_found and not-found", () => {
    expect(statusLabelZh("not_found")).toBe("未找到");
    expect(statusLabelZh("not-found")).toBe("未找到");
  });
});

describe("asyncTaskName", () => {
  it("maps known task type", () => {
    expect(asyncTaskName("import_pipeline")).toBe("题目导入流水线");
    expect(asyncTaskName("ocr_pipeline")).toBe("OCR 处理");
  });
  it("returns raw value for unknown", () => {
    expect(asyncTaskName("custom_type")).toBe("custom_type");
  });
  it("returns raw for empty", () => {
    expect(asyncTaskName("")).toBe("");
  });
});

describe("taskStatusMeta", () => {
  it("returns danger for failed", () => {
    expect(taskStatusMeta("failed")).toEqual({ label: "失败", tone: "danger" });
  });
  it("returns danger for dead location", () => {
    expect(taskStatusMeta("x", "dead")).toEqual({ label: "失败", tone: "danger" });
  });
  it("returns danger+异常 for corrupt", () => {
    expect(taskStatusMeta("x", "corrupt")).toEqual({ label: "异常", tone: "danger" });
  });
  it("returns success for running", () => {
    expect(taskStatusMeta("running")).toEqual({ label: "运行中", tone: "success" });
  });
  it("returns success for processing", () => {
    expect(taskStatusMeta("x", "processing")).toEqual({ label: "运行中", tone: "success" });
  });
  it("returns warning for retry", () => {
    expect(taskStatusMeta("x", "retry")).toEqual({ label: "等待重试", tone: "warning" });
  });
  it("returns neutral for ready", () => {
    expect(taskStatusMeta("x", "ready")).toEqual({ label: "等待中", tone: "neutral" });
  });
  it("returns neutral for disabled", () => {
    expect(taskStatusMeta("x", "disabled")).toEqual({ label: "已停用", tone: "neutral" });
  });
  it("returns success for completed", () => {
    expect(taskStatusMeta("completed")).toEqual({ label: "成功", tone: "success" });
  });
  it("falls back to statusLabelZh for unknown", () => {
    const r = taskStatusMeta("custom_status");
    expect(r.tone).toBe("neutral");
    expect(r.label).toBe("custom_status");
  });
});

describe("runResultMeta", () => {
  it("success", () => {
    expect(runResultMeta("success")).toEqual({ label: "成功", tone: "success" });
  });
  it("failed", () => {
    expect(runResultMeta("failed")).toEqual({ label: "失败", tone: "danger" });
  });
  it("skipped", () => {
    expect(runResultMeta("skipped")).toEqual({ label: "跳过", tone: "warning" });
  });
  it("no record", () => {
    expect(runResultMeta(undefined)).toEqual({ label: "暂无记录", tone: "neutral" });
    expect(runResultMeta(null)).toEqual({ label: "暂无记录", tone: "neutral" });
  });
});

describe("taskMatchesStatus", () => {
  it("all matches everything", () => {
    expect(taskMatchesStatus("all", "anything")).toBe(true);
  });
  it("running matches running/processing", () => {
    expect(taskMatchesStatus("running", "running")).toBe(true);
    expect(taskMatchesStatus("running", "x", "processing")).toBe(true);
    expect(taskMatchesStatus("running", "idle")).toBe(false);
  });
  it("waiting matches idle/ready/pending/retry", () => {
    expect(taskMatchesStatus("waiting", "idle")).toBe(true);
    expect(taskMatchesStatus("waiting", "x", "ready")).toBe(true);
    expect(taskMatchesStatus("waiting", "pending")).toBe(true);
    expect(taskMatchesStatus("waiting", "retry")).toBe(true);
    expect(taskMatchesStatus("waiting", "running")).toBe(false);
  });
  it("failed matches failed/dead/corrupt", () => {
    expect(taskMatchesStatus("failed", "failed")).toBe(true);
    expect(taskMatchesStatus("failed", "x", "dead")).toBe(true);
    expect(taskMatchesStatus("failed", "x", "corrupt")).toBe(true);
    expect(taskMatchesStatus("failed", "success")).toBe(false);
  });
  it("unavailable matches unavailable/unobservable", () => {
    expect(taskMatchesStatus("unavailable", "unavailable")).toBe(true);
    expect(taskMatchesStatus("unavailable", "x", "unobservable")).toBe(true);
    expect(taskMatchesStatus("unavailable", "running")).toBe(false);
  });
  it("disabled matches only disabled", () => {
    expect(taskMatchesStatus("disabled", "disabled")).toBe(true);
    expect(taskMatchesStatus("disabled", "x", "disabled")).toBe(true);
    expect(taskMatchesStatus("disabled", "running")).toBe(false);
  });
  it("prefers location over status", () => {
    expect(taskMatchesStatus("running", "idle", "processing")).toBe(true);
  });
});

describe("computeQueueTotal", () => {
  it("sums all fields", () => {
    expect(computeQueueTotal({ ready: 1, processing: 2, retry: 3, dead: 4, corrupt: 5 })).toBe(15);
  });
  it("returns 0 for undefined", () => {
    expect(computeQueueTotal(undefined)).toBe(0);
  });
});

describe("computeFailedQueueTotal", () => {
  it("sums dead+corrupt", () => {
    expect(computeFailedQueueTotal({ dead: 3, corrupt: 2 })).toBe(5);
  });
  it("returns 0 for undefined", () => {
    expect(computeFailedQueueTotal(undefined)).toBe(0);
  });
});

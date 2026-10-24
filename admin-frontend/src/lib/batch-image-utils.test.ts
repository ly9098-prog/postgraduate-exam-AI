import { describe, it, expect } from "vitest";
import { dedupeFiles, taskProgress, computeBatchStats, type ImageTask } from "./batch-image-utils";

const makeFile = (name: string, size: number, type = "image/png"): File =>
  ({ name, size, type } as File);

const baseTask: ImageTask = {
  id: "img_1", status: "pending", jobId: null,
  traceEvents: [], questionCount: 0,
};

describe("dedupeFiles", () => {
  it("adds new files", () => {
    const out = dedupeFiles([], [makeFile("a.png", 100)]);
    expect(out).toHaveLength(1);
  });
  it("dedupes by name+size", () => {
    const f = makeFile("a.png", 100);
    expect(dedupeFiles([f], [f])).toHaveLength(1);
  });
  it("rejects non-image types", () => {
    const f = { name: "a.txt", size: 100, type: "text/plain" } as File;
    expect(dedupeFiles([], [f])).toHaveLength(0);
  });
  it("accepts jpeg, png, webp", () => {
    expect(dedupeFiles([], [makeFile("a.jpg", 1, "image/jpeg")])).toHaveLength(1);
    expect(dedupeFiles([], [makeFile("b.png", 1, "image/png")])).toHaveLength(1);
    expect(dedupeFiles([], [makeFile("c.webp", 1, "image/webp")])).toHaveLength(1);
  });
  it("merges with existing", () => {
    const out = dedupeFiles([makeFile("a.png", 1)], [makeFile("b.png", 2)]);
    expect(out).toHaveLength(2);
  });
  it("caps at MAX_FILES", () => {
    const many = Array.from({ length: 60 }, (_, i) => makeFile(`f${i}.png`, i));
    expect(dedupeFiles([], many).length).toBeLessThanOrEqual(50);
  });
});

describe("taskProgress", () => {
  it("100 for succeeded", () => {
    expect(taskProgress({ ...baseTask, status: "succeeded" })).toBe(100);
  });
  it("100 for failed", () => {
    expect(taskProgress({ ...baseTask, status: "failed" })).toBe(100);
  });
  it("10 for uploading", () => {
    expect(taskProgress({ ...baseTask, status: "uploading" })).toBe(10);
  });
  it("0 for pending without jobId", () => {
    expect(taskProgress({ ...baseTask, status: "pending", jobId: null })).toBe(0);
  });
  it("15 for pending with jobId", () => {
    expect(taskProgress({ ...baseTask, status: "pending", jobId: "job1" })).toBe(15);
  });
  it("90 for pipeline success trace", () => {
    expect(taskProgress({
      ...baseTask, status: "processing",
      traceEvents: [{ step: "pipeline", status: "success" }],
    })).toBe(90);
  });
  it("55 for pipeline running trace", () => {
    expect(taskProgress({
      ...baseTask, status: "processing",
      traceEvents: [{ step: "pipeline", status: "running" }],
    })).toBe(55);
  });
  it("40 for ocr success trace", () => {
    expect(taskProgress({
      ...baseTask, status: "processing",
      traceEvents: [{ step: "ocr", status: "success" }],
    })).toBe(40);
  });
  it("20 default for processing with no matching traces", () => {
    expect(taskProgress({ ...baseTask, status: "processing" })).toBe(20);
  });
  it("pipeline success takes precedence over ocr success", () => {
    expect(taskProgress({
      ...baseTask, status: "processing",
      traceEvents: [
        { step: "ocr", status: "success" },
        { step: "pipeline", status: "success" },
      ],
    })).toBe(90);
  });
});

describe("computeBatchStats", () => {
  const tasks: ImageTask[] = [
    { ...baseTask, status: "succeeded", questionCount: 5 },
    { ...baseTask, status: "failed", questionCount: 2 },
    { ...baseTask, status: "uploading", questionCount: 0 },
    { ...baseTask, status: "processing", questionCount: 3 },
  ];
  it("counts by status", () => {
    const s = computeBatchStats(tasks);
    expect(s.succeededCount).toBe(1);
    expect(s.failedCount).toBe(1);
    expect(s.uploadingCount).toBe(1);
    expect(s.processingCount).toBe(1);
  });
  it("sums question counts", () => {
    expect(computeBatchStats(tasks).totalQuestions).toBe(10);
  });
  it("computes total progress", () => {
    const s = computeBatchStats(tasks);
    expect(s.totalProgress).toBeGreaterThan(0);
    expect(s.totalProgress).toBeLessThanOrEqual(100);
  });
  it("handles empty list", () => {
    expect(computeBatchStats([])).toEqual({
      succeededCount: 0, failedCount: 0, totalQuestions: 0,
      uploadingCount: 0, processingCount: 0, totalProgress: 0,
    });
  });
});

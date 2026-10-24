import { describe, expect, it, vi } from "vitest";

import { executeSegmentReplace, resolveSegmentFileChange } from "./review-segment-replace";

function makeOptions(overrides: Partial<Parameters<typeof executeSegmentReplace>[2]> = {}) {
  return {
    canWrite: true,
    previewId: 1,
    setSegmentUploading: vi.fn(),
    setEditedSegments: vi.fn(),
    updateMessage: vi.fn(),
    uploadSegmentImage: vi.fn().mockResolvedValue({ url: "https://cdn/seg.png", filename: "seg.png" }),
    ...overrides,
  };
}

describe("executeSegmentReplace", () => {
  it("returns early when canWrite is false", async () => {
    const opts = makeOptions({ canWrite: false });
    await executeSegmentReplace(0, new File(["x"], "f.png"), opts);
    expect(opts.setSegmentUploading).not.toHaveBeenCalled();
    expect(opts.uploadSegmentImage).not.toHaveBeenCalled();
  });

  it("returns early when file is empty", async () => {
    const opts = makeOptions();
    await executeSegmentReplace(0, null as unknown as File, opts);
    expect(opts.setSegmentUploading).not.toHaveBeenCalled();
  });

  it("uploads, updates segments, and shows success message", async () => {
    const opts = makeOptions();
    await executeSegmentReplace(0, new File(["x"], "f.png"), opts);
    expect(opts.setSegmentUploading).toHaveBeenCalledWith(0);
    expect(opts.uploadSegmentImage).toHaveBeenCalledTimes(1);
    expect(opts.setEditedSegments).toHaveBeenCalled();
    expect(opts.updateMessage).toHaveBeenCalledWith("图片已替换：seg.png");
    expect(opts.setSegmentUploading).toHaveBeenLastCalledWith(-1);
  });

  it("skips segment update when previewId changed during upload", async () => {
    const opts = makeOptions({ previewId: 1 });
    opts.uploadSegmentImage = vi.fn().mockImplementation(async () => {
      // Simulate preview switching during async upload
      opts.previewId = 2;
      return { url: "https://cdn/seg.png", filename: "seg.png" };
    });
    await executeSegmentReplace(0, new File(["x"], "f.png"), opts);
    expect(opts.setEditedSegments).not.toHaveBeenCalled();
    expect(opts.updateMessage).not.toHaveBeenCalled();
    expect(opts.setSegmentUploading).toHaveBeenLastCalledWith(-1);
  });

  it("shows error message on upload failure", async () => {
    const opts = makeOptions({
      uploadSegmentImage: vi.fn().mockRejectedValue(new Error("network error")),
    });
    await executeSegmentReplace(0, new File(["x"], "f.png"), opts);
    expect(opts.updateMessage).toHaveBeenCalledWith("network error");
    expect(opts.setSegmentUploading).toHaveBeenLastCalledWith(-1);
  });

  it("shows generic error on non-Error throw", async () => {
    const opts = makeOptions({
      uploadSegmentImage: vi.fn().mockRejectedValue("string error"),
    });
    await executeSegmentReplace(0, new File(["x"], "f.png"), opts);
    expect(opts.updateMessage).toHaveBeenCalledWith("图片上传失败");
  });
});

describe("resolveSegmentFileChange", () => {
  it("extracts file and resets input value", () => {
    const file = new File(["x"], "f.png");
    const input = { target: { files: [file], value: "path" } } as unknown as React.ChangeEvent<HTMLInputElement>;
    const result = resolveSegmentFileChange(input, 2);
    expect(result.file).toBe(file);
    expect(result.index).toBe(2);
    expect(input.target.value).toBe("");
  });

  it("returns null file when no files selected", () => {
    const input = { target: { files: [], value: "path" } } as unknown as React.ChangeEvent<HTMLInputElement>;
    const result = resolveSegmentFileChange(input, 1);
    expect(result.file).toBeNull();
    expect(result.index).toBe(1);
  });
});

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { exportQuestions, type QuestionExportPayload } from "../question-api";
import type { QuestionExportDownloadPorts } from "../question-export-download";
import { useQuestionExport } from "./use-question-export";

vi.mock("../question-api", () => ({
  exportQuestions: vi.fn(),
}));

function ports(overrides: Partial<QuestionExportDownloadPorts> = {}) {
  return {
    createObjectURL: vi.fn(() => "blob:url"),
    revokeObjectURL: vi.fn(),
    createAnchor: vi.fn(() => ({} as HTMLAnchorElement)),
    appendAnchor: vi.fn(),
    removeAnchor: vi.fn(),
    clickAnchor: vi.fn(),
    setTimeout: vi.fn((callback: () => void) => {
      callback();
      return 1;
    }),
    ...overrides,
  };
}

function renderHook(useFeature: () => ReturnType<typeof useQuestionExport>) {
  let result!: ReturnType<typeof useQuestionExport>;
  function Probe() {
    result = useFeature();
    return null;
  }
  renderToStaticMarkup(createElement(Probe));
  return result;
}

function setup(download = ports()) {
  const payload: QuestionExportPayload = { format: "csv" };
  const onMessage = vi.fn();
  const closeMenus = vi.fn();
  const buildPayload = vi.fn(() => payload);
  const hook = renderHook(() => useQuestionExport({
    buildPayload,
    download,
    request: exportQuestions,
    closeMenus,
    onMessage,
  }));
  return { buildPayload, closeMenus, download, hook, onMessage, payload };
}

describe("useQuestionExport", () => {
  it("exports the selected format, downloads it, and reports the message", async () => {
    const response = {
      blob: new Blob(["export"]),
      filename: "questions.csv",
      mediaType: "text/csv",
    };
    vi.mocked(exportQuestions).mockResolvedValueOnce(response);
    const value = setup();

    await value.hook.exportQuestion("csv");

    expect(value.hook.exportingFormat).toBeNull();
    expect(value.closeMenus).toHaveBeenCalledExactlyOnceWith();
    expect(exportQuestions).toHaveBeenCalledExactlyOnceWith(value.payload);
    expect(value.download.createObjectURL).toHaveBeenCalledExactlyOnceWith(response.blob);
    expect(value.onMessage).toHaveBeenCalledExactlyOnceWith("CSV 导出已开始。");
  });

  it("preserves the request error message while clearing export state", async () => {
    vi.mocked(exportQuestions).mockRejectedValueOnce(new Error("server busy"));
    const value = setup();

    await value.hook.exportQuestion("docx");

    expect(value.hook.exportingFormat).toBeNull();
    expect(value.onMessage).toHaveBeenCalledExactlyOnceWith("server busy");
    expect(value.download.createObjectURL).not.toHaveBeenCalled();
  });

  it("uses the generic export failure message for non-error rejections", async () => {
    vi.mocked(exportQuestions).mockRejectedValueOnce("network reset");
    const value = setup();

    await value.hook.exportQuestion("csv");

    expect(value.onMessage).toHaveBeenCalledExactlyOnceWith("导出失败，请稍后重试。");
  });
});

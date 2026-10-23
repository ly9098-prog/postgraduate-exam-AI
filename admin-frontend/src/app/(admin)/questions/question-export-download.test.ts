import { describe, expect, it, vi } from "vitest";
import {
  buildExportMessage,
  exportFilename,
  exportQuestionDownload,
  type QuestionExportDownloadPorts,
} from "./question-export-download";

function ports() {
  const anchor = { href: "", download: "" } as HTMLAnchorElement;
  return {
    anchor,
    ports: {
      createObjectURL: vi.fn(() => "blob:export"),
      revokeObjectURL: vi.fn(),
      createAnchor: vi.fn(() => anchor),
      appendAnchor: vi.fn(),
      removeAnchor: vi.fn(),
      clickAnchor: vi.fn(),
      setTimeout: vi.fn(),
    } satisfies QuestionExportDownloadPorts,
  };
}

describe("question export download", () => {
  it("uses the server filename when present", () => {
    const h = ports();
    exportQuestionDownload(
      { blob: new Blob(["csv"]), filename: "server.csv" },
      "csv",
      h.ports,
    );

    expect(h.anchor.href).toBe("blob:export");
    expect(h.anchor.download).toBe("server.csv");
    expect(h.ports.appendAnchor).toHaveBeenCalledWith(h.anchor);
    expect(h.ports.clickAnchor).toHaveBeenCalledWith(h.anchor);
    expect(h.ports.removeAnchor).toHaveBeenCalledWith(h.anchor);
    expect(h.ports.revokeObjectURL).not.toHaveBeenCalled();
  });

  it("falls back to a format-specific filename", () => {
    const h = ports();
    exportQuestionDownload({ blob: new Blob(["doc"]) }, "docx", h.ports);
    expect(h.anchor.download).toBe("questions-export.docx");
    expect(exportFilename("csv")).toBe("questions-export.csv");
  });

  it("keeps the delayed revoke scheduled even if DOM operations fail", () => {
    const h = ports();
    h.ports.appendAnchor.mockImplementation(() => {
      throw new Error("detached document");
    });
    expect(() => exportQuestionDownload(
      { blob: new Blob(["csv"]) },
      "csv",
      h.ports,
    )).toThrow("detached document");
    expect(h.ports.setTimeout).toHaveBeenCalledExactlyOnceWith(expect.any(Function), 1000);
    expect(h.ports.revokeObjectURL).not.toHaveBeenCalled();
  });

  it("preserves the existing user-facing messages", () => {
    expect(buildExportMessage("csv")).toBe("CSV 导出已开始。");
    expect(buildExportMessage("docx")).toBe("Word 导出已开始。");
  });
});

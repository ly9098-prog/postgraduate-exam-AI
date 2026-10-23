
type ExportResult = {
  blob: Blob;
  filename?: string | null;
};

export type QuestionExportDownloadPorts = {
  createObjectURL: (blob: Blob) => string;
  revokeObjectURL: (url: string) => void;
  createAnchor: () => HTMLAnchorElement;
  appendAnchor: (anchor: HTMLAnchorElement) => void;
  removeAnchor: (anchor: HTMLAnchorElement) => void;
  clickAnchor: (anchor: HTMLAnchorElement) => void;
  setTimeout: (callback: () => void, delay: number) => void;
};

export function exportFilename(format: "csv" | "docx"): string {
  return `questions-export.${format === "docx" ? "docx" : "csv"}`;
}

export function buildExportMessage(format: "csv" | "docx"): string {
  return format === "csv" ? "CSV 导出已开始。" : "Word 导出已开始。";
}

export function exportQuestionDownload(
  result: ExportResult,
  format: "csv" | "docx",
  ports: QuestionExportDownloadPorts,
): void {
  const url = ports.createObjectURL(result.blob);
  try {
    const anchor = ports.createAnchor();
    anchor.href = url;
    anchor.download = result.filename || exportFilename(format);
    ports.appendAnchor(anchor);
    ports.clickAnchor(anchor);
    ports.removeAnchor(anchor);
  } finally {
    ports.setTimeout(() => ports.revokeObjectURL(url), 1000);
  }
}

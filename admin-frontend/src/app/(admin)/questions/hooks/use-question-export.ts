"use client";

import { useCallback, useState } from "react";
import { exportQuestions, type QuestionExportPayload } from "../question-api";
import {
  buildExportMessage,
  exportQuestionDownload,
  type QuestionExportDownloadPorts,
} from "../question-export-download";

type QuestionExportFormat = "csv" | "docx";

type ExportCapabilities = {
  buildPayload: (format: QuestionExportFormat) => QuestionExportPayload;
  download: QuestionExportDownloadPorts;
  request: typeof exportQuestions;
  closeMenus: () => void;
  onMessage: (message: string) => void;
};

export function useQuestionExport({
  buildPayload,
  download,
  request,
  closeMenus,
  onMessage,
}: ExportCapabilities) {
  const [exportingFormat, setExportingFormat] = useState<QuestionExportFormat | null>(null);

  const exportQuestion = useCallback(async (format: QuestionExportFormat) => {
    try {
      setExportingFormat(format);
      closeMenus();
      const response = await request(buildPayload(format));
      exportQuestionDownload(response, format, download);
      onMessage(buildExportMessage(format));
    } catch (error) {
      onMessage(
        error instanceof Error ? error.message : "导出失败，请稍后重试。",
      );
    } finally {
      setExportingFormat(null);
    }
  }, [buildPayload, closeMenus, download, onMessage, request]);

  return { exportingFormat, exportQuestion };
}

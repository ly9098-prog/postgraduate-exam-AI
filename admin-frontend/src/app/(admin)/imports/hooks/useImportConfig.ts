"use client";

import { useState } from "react";

export type OcrMode = "api" | "local";

export function useImportConfig() {
  const [ocrMode, setOcrMode] = useState<OcrMode>("local");
  return { ocrMode, setOcrMode };
}

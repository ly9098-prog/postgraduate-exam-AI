/**
 * Pure utility functions for import pipeline progress & page range display.
 * Free of React dependencies — designed for direct unit testing.
 */

export function parseProgressPercent(ocrProgress: string | undefined | null): number {
  if (!ocrProgress) return 0;
  const match = ocrProgress.match(/(\d+)\/(\d+)\s*pages?/);
  if (match) {
    const current = parseInt(match[1], 10);
    const total = parseInt(match[2], 10);
    if (total > 0) return Math.min(100, Math.round((current / total) * 100));
  }
  const pctMatch = ocrProgress.match(/(\d+(?:\.\d+)?)%/);
  if (pctMatch) return Math.min(100, Math.round(parseFloat(pctMatch[1])));
  return 0;
}

export interface PageRangeValidation {
  valid: boolean;
  error?: string;
}

export function validatePageStart(value: string | undefined | null): PageRangeValidation {
  if (!value || value.trim() === "") {
    return { valid: true };
  }
  const n = Number(value);
  if (!Number.isInteger(n)) {
    return { valid: false, error: "页码必须是整数" };
  }
  if (n < 1) {
    return { valid: false, error: "起始页码不能小于 1" };
  }
  return { valid: true };
}

export function validatePageEnd(value: string | undefined | null, startValue: string | undefined | null): PageRangeValidation {
  if (!value || value.trim() === "") {
    return { valid: true };
  }
  const n = Number(value);
  if (!Number.isInteger(n)) {
    return { valid: false, error: "页码必须是整数" };
  }
  if (n < 1) {
    return { valid: false, error: "结束页码不能小于 1" };
  }
  if (startValue && startValue.trim() !== "") {
    const start = Number(startValue);
    if (n < start) {
      return { valid: false, error: "结束页码不能小于起始页码" };
    }
  }
  return { valid: true };
}

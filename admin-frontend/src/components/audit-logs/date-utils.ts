import {
  chinaDateToUtcIso,
  formatChinaDateTime,
  formatUtcTime as formatUtc,
} from "@/lib/time";

export function formatLocalDateTime(isoString: string | null | undefined): string {
  return formatChinaDateTime(isoString, { second: "2-digit" });
}

export function formatUtcTime(isoString: string | null | undefined): string {
  return formatUtc(isoString);
}

/** Convert an Asia/Shanghai date string (YYYY-MM-DD) to UTC ISO at China midnight. */
export function localDateToUtcIso(dateStr: string): string {
  return chinaDateToUtcIso(dateStr);
}

/** Convert an Asia/Shanghai date string to the next China midnight in UTC (exclusive end). */
export function localDateToUtcIsoNext(dateStr: string): string {
  return chinaDateToUtcIso(dateStr, 1);
}

export function truncate(str: string | null | undefined, maxLen: number): string {
  if (!str) return "";
  return str.length > maxLen ? str.slice(0, maxLen) + "…" : str;
}

/**
 * Admin product timezone helpers.
 *
 * Backend DateTime columns are stored as naive UTC.  New API responses carry
 * an explicit Z, while this parser also accepts historical naive ISO strings
 * and interprets them as UTC.  Product calendar dates are Asia/Shanghai.
 */

const CHINA_TIME_ZONE = "Asia/Shanghai";
const CHINA_OFFSET_MS = 8 * 60 * 60 * 1000;

function hasExplicitOffset(value: string): boolean {
  return /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
}

export function normalizeServerUtc(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return trimmed;
  const normalized = trimmed.replace(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})/, "$1T$2");
  // A date-only value is a product calendar date, not an instant.
  if (/^\d{4}-\d{2}-\d{2}$/.test(normalized)) return normalized;
  return hasExplicitOffset(normalized) ? normalized : `${normalized}Z`;
}

export function parseServerUtc(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(normalizeServerUtc(value));
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatChinaDateTime(
  value: string | null | undefined,
  options: Intl.DateTimeFormatOptions = {},
): string {
  const date = parseServerUtc(value);
  if (!date) return value || "—";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: CHINA_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    ...options,
  }).format(date);
}

export function formatChinaDate(value: string | null | undefined): string {
  const date = parseServerUtc(value);
  if (!date) return value || "—";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: CHINA_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

export function formatUtcTime(value: string | null | undefined): string {
  const date = parseServerUtc(value);
  if (!date) return value || "";
  return date.toISOString().replace("Z", " UTC");
}

function chinaParts(nowMs: number): { year: number; month: number; day: number } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: CHINA_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(nowMs));
  const get = (type: Intl.DateTimeFormatPartTypes) => Number(parts.find((part) => part.type === type)?.value || 0);
  return { year: get("year"), month: get("month"), day: get("day") };
}

export function chinaDateString(offsetDays = 0, nowMs = Date.now()): string {
  const { year, month, day } = chinaParts(nowMs);
  const shifted = new Date(Date.UTC(year, month - 1, day + offsetDays));
  return `${shifted.getUTCFullYear()}-${String(shifted.getUTCMonth() + 1).padStart(2, "0")}-${String(shifted.getUTCDate()).padStart(2, "0")}`;
}

export function formatChinaClock(nowMs = Date.now()): string {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: CHINA_TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(nowMs));
}

/** Convert a China calendar date (YYYY-MM-DD) to the corresponding UTC instant. */
export function chinaDateToUtcIso(dateStr: string, dayOffset = 0): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  if (!match) return "";
  const [, y, m, d] = match;
  const utcMs = Date.UTC(Number(y), Number(m) - 1, Number(d) + dayOffset) - CHINA_OFFSET_MS;
  return new Date(utcMs).toISOString();
}

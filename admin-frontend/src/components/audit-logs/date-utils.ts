export function formatLocalDateTime(isoString: string | null | undefined): string {
  if (!isoString) return "";
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return "时间格式异常";
    const fmt = new Intl.DateTimeFormat(undefined, {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
    return fmt.format(d);
  } catch {
    return "时间格式异常";
  }
}

export function formatUtcTime(isoString: string | null | undefined): string {
  if (!isoString) return "";
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return "时间格式异常";
    return d.toISOString().replace("Z", " UTC");
  } catch {
    return "时间格式异常";
  }
}

/** Convert a local date string (YYYY-MM-DD) to a UTC ISO string at local midnight. */
export function localDateToUtcIso(dateStr: string): string {
  const [y, m, d] = dateStr.split("-").map(Number);
  const local = new Date(y, m - 1, d);
  return local.toISOString();
}

/** Convert a local date string (YYYY-MM-DD) to the NEXT local midnight in UTC ISO (exclusive end). */
export function localDateToUtcIsoNext(dateStr: string): string {
  const [y, m, d] = dateStr.split("-").map(Number);
  const local = new Date(y, m - 1, d + 1);
  return local.toISOString();
}

export function truncate(str: string | null | undefined, maxLen: number): string {
  if (!str) return "";
  return str.length > maxLen ? str.slice(0, maxLen) + "…" : str;
}

export function isMeaningfulText(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  const text = String(value).trim();
  if (!text) return false;
  const invalidValues = new Set([
    "unknown", "UNKNOWN", "Unknown", "未知", "-", "—", "null", "undefined",
  ]);
  return !invalidValues.has(text);
}

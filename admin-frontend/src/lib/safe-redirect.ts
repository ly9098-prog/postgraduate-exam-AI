/**
 * Validate that a redirect target is a safe internal URL.
 *
 * Rules:
 * - Must start with a single "/"
 * - Must not start with "//" (protocol-relative URL)
 * - Must not contain a scheme (e.g. "https://", "javascript:")
 * - Must not contain backslash
 * - Must not contain control characters (0x00–0x1F)
 * - Must not redirect back to /login (redirect loop)
 * - On failure, return the fallback (default "/dashboard")
 */

const CONTROL_CHAR_RE = /[\x00-\x1F]/;
const HAS_SCHEME_RE = /^[a-zA-Z][a-zA-Z0-9+\-.]*:/;

export function safeInternalRedirect(
  next: string | null | undefined,
  fallback = "/dashboard",
): string {
  if (!next) return fallback;
  if (!next.startsWith("/")) return fallback;
  if (next.startsWith("//")) return fallback;
  if (next.length > 2048) return fallback;
  if (CONTROL_CHAR_RE.test(next)) return fallback;
  if (next.includes("\\")) return fallback;
  if (HAS_SCHEME_RE.test(next)) return fallback;
  if (next === "/login") return fallback;

  return next;
}

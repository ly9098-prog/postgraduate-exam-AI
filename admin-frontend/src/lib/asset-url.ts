let _apiBase: string | null = null;

function getApiBase(): string {
  if (_apiBase === null) {
    _apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "";
  }
  return _apiBase;
}

/** Reset cached API base — used in tests. */
export function _resetApiBase(): void {
  _apiBase = null;
}

const ALLOWED_SCHEMES = new Set(["http:", "https:"]);
const BLOCKED_HOST_PATTERNS = [/^localhost:/i, /^127\./, /^0\.0\.0\.0$/];

function isBlockedHost(host: string): boolean {
  return BLOCKED_HOST_PATTERNS.some((p) => p.test(host));
}

/**
 * Resolve an asset URL for display.
 *
 * - `null` / `undefined` / `""` → `""` (no asset)
 * - Full `http:` / `https:` URL → validate scheme+host; reject `javascript:`, `file:`, unapproved `data:`
 * - Protocol-relative `//...` → prepend `https:`
 * - Root-relative `/...` → prepend API base (from `NEXT_PUBLIC_API_BASE`)
 * - Other relative → resolve against API base
 *
 * In production (`NEXT_PUBLIC_API_BASE` missing) → fail closed (return `""`).
 */
export function resolveAssetUrl(url: string | null | undefined): string {
  if (!url) return "";

  // Protocol-relative
  if (url.startsWith("//")) {
    return `https:${url}`;
  }

  try {
    const parsed = new URL(url);

    if (!ALLOWED_SCHEMES.has(parsed.protocol)) {
      return "";
    }

    const base = getApiBase();

    // In dev (no API base configured), allow localhost
    if (!base) {
      // No API base — only allow if NOT localhost (production fail-closed)
      if (isBlockedHost(parsed.host)) {
        return "";
      }
      return url;
    }

    // API base configured — reject localhost unless base IS localhost
    if (isBlockedHost(parsed.host) && !isBlockedHost(new URL(base).host)) {
      return "";
    }

    return url;
  } catch {
    // Not a valid absolute URL — treat as relative/root-relative
    const base = getApiBase();
    if (!base) {
      // Production fail-closed: no API base configured, cannot resolve
      return "";
    }

    // Normalize slashes
    const baseClean = base.replace(/\/+$/, "");
    const pathClean = url.startsWith("/") ? url : `/${url}`;
    return `${baseClean}${pathClean}`;
  }
}

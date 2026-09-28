import { ApiError } from "./errors";

const DEFAULT_BASE_URL = "/api/admin/v1";
const DEFAULT_TIMEOUT_MS = 60_000;

function generateCorrelationId(prefix: "tr" | "req") {
  const uuid = globalThis.crypto?.randomUUID?.().replace(/-/g, "");
  const suffix = uuid?.slice(0, 24) ?? `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
  return `${prefix}_${suffix}`;
}

function normalizeCorrelationId(value: string | undefined, prefix: "tr" | "req") {
  const candidate = value?.trim() ?? "";
  return /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/.test(candidate)
    ? candidate
    : generateCorrelationId(prefix);
}

export function createApiTraceId() {
  return generateCorrelationId("tr");
}

export function createApiRequestId() {
  return generateCorrelationId("req");
}

function readResponseHeader(response: Response, name: string) {
  const value = response.headers.get(name);
  return value && value.length <= 64 ? value : undefined;
}

let accessToken: string | null = null;
let accessTokenProvider: (() => string | null) | null = null;

// Single-flight refresh state
let refreshPromise: Promise<string | null> | null = null;
let onAuthExpired: (() => void) | null = null;

// sessionStorage backing so a page reload reuses the still-valid token
// instead of consuming a refresh rotation on every load (each rotation
// writes an admin:refresh:used marker in Redis). Centralized here so every
// write path (login, bootstrap, auto-refresh) stays in sync.
const ACCESS_TOKEN_STORAGE_KEY = "admin_access_token";

function persistApiAccessToken(token: string | null) {
  try {
    if (token) sessionStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token);
    else sessionStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
  } catch {
    // Storage unavailable (private mode etc.) — memory-only fallback is fine.
  }
}

export function readStoredApiAccessToken(): string | null {
  try {
    return sessionStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setApiAccessToken(token: string | null) {
  accessToken = token;
  persistApiAccessToken(token);
}

export function setApiAccessTokenProvider(provider: (() => string | null) | null) {
  accessTokenProvider = provider;
}

export function getApiAccessToken() {
  return accessTokenProvider?.() ?? accessToken ?? null;
}

/**
 * Register a callback for when the auth session expires (refresh fails).
 * Used by the auth store to clean up state and redirect to login.
 */
export function setOnAuthExpired(callback: (() => void) | null) {
  onAuthExpired = callback;
}

function getBaseUrl() {
  return process.env.NEXT_PUBLIC_ADMIN_API_BASE_URL ?? DEFAULT_BASE_URL;
}

function normalizePath(path: string) {
  return path.startsWith("/") ? path : `/${path}`;
}

async function parseResponse(response: Response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function readSafeErrorMeta(payload: unknown, response?: Response) {
  const headerRequestId = response ? readResponseHeader(response, "X-Request-ID") : undefined;
  const headerTraceId = response ? readResponseHeader(response, "X-Trace-ID") : undefined;

  if (!payload || typeof payload !== "object" || !("error" in payload)) {
    return headerRequestId || headerTraceId
      ? { requestId: headerRequestId, traceId: headerTraceId, retryable: false }
      : null;
  }

  const error = (payload as { error?: unknown }).error;
  if (!error || typeof error !== "object") {
    return headerRequestId || headerTraceId
      ? { requestId: headerRequestId, traceId: headerTraceId, retryable: false }
      : null;
  }

  const value = error as Record<string, unknown>;
  return {
    code: typeof value.code === "string" ? value.code : undefined,
    requestId: typeof value.request_id === "string" ? value.request_id : headerRequestId,
    traceId: typeof value.trace_id === "string" ? value.trace_id : headerTraceId,
    retryable: value.retryable === true,
  };
}

function classifyError(status: number): string {
  switch (status) {
    case 0: return "网络连接失败，请检查网络后重试";
    case 400: return "请求参数有误，请检查后重试";
    case 401: return "登录状态已失效，请重新登录";
    case 403: return "没有权限执行此操作";
    case 404: return "请求的资源不存在";
    case 405: return "请求方式不支持";
    case 409: return "当前数据状态已变化，请刷新后重试";
    case 413: return "上传内容过大，请调整后重试";
    case 415: return "不支持的内容类型";
    case 422: return "提交内容校验未通过，请检查后重试";
    case 429: return "请求过于频繁，请稍后重试";
    case 502:
    case 503: return "服务暂时不可用，请稍后重试";
    case 504: return "服务响应超时，请稍后重试";
    default:
      if (status >= 500) return "服务器内部错误，请稍后重试";
      return "请求失败，请稍后重试";
  }
}

function buildHeaders(init: RequestInit, traceId: string, requestId: string): Headers {
  const headers = new Headers(init.headers);
  // FormData must not have Content-Type set manually — browser sets it with boundary
  if (!headers.has("Content-Type") && init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const token = getApiAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  headers.set("X-Trace-ID", traceId);
  headers.set("X-Request-ID", requestId);
  return headers;
}

interface ApiRequestOptions extends RequestInit {
  /** Override default timeout in ms. 0 = no timeout. */
  timeoutMs?: number;
  /** Skip auto-refresh on 401 for this request. */
  skipRefresh?: boolean;
  /** Optional caller-supplied trace ID to correlate multiple API calls. */
  traceId?: string;
  /**
   * Opt in to rendering a backend validation detail as the ApiError message.
   * Keep disabled by default so internal backend errors are never exposed globally.
   */
  exposeErrorDetail?: boolean;
}

async function requestWithTimeout(
  url: string, init: RequestInit, timeoutMs: number, signal?: AbortSignal,
): Promise<Response> {
  if (timeoutMs <= 0) return fetch(url, { ...init, signal });
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  // Combine external AbortSignal with timeout
  const combinedSignal = signal
    ? combineAbortSignals(signal, controller.signal)
    : controller.signal;

  try {
    return await fetch(url, { ...init, signal: combinedSignal });
  } finally {
    clearTimeout(timeoutId);
  }
}

function combineAbortSignals(...signals: AbortSignal[]): AbortSignal {
  const controller = new AbortController();
  for (const sig of signals) {
    if (sig.aborted) {
      controller.abort(sig.reason);
      return controller.signal;
    }
    sig.addEventListener("abort", () => controller.abort(sig.reason), { once: true });
  }
  return controller.signal;
}

function formatValidationDetail(detail: unknown): string | null {
  if (typeof detail === "string") {
    const text = detail.trim();
    return text ? text.slice(0, 2000) : null;
  }

  // FastAPI request-validation errors use detail: [{ loc, msg, type }, ...].
  if (Array.isArray(detail)) {
    const lines = detail.slice(0, 8).flatMap((item) => {
      if (!item || typeof item !== "object") return [];
      const value = item as Record<string, unknown>;
      const msg = typeof value.msg === "string" ? value.msg.trim() : "";
      if (!msg) return [];
      const loc = Array.isArray(value.loc)
        ? value.loc.filter((part) => typeof part === "string" || typeof part === "number").join(".")
        : "";
      return [loc ? `${loc}: ${msg}` : msg];
    });
    if (lines.length) return lines.join("；").slice(0, 2000);
  }

  if (detail && typeof detail === "object") {
    const nested = detail as Record<string, unknown>;
    for (const key of ["detail", "message", "reason"] as const) {
      const text = formatValidationDetail(nested[key]);
      if (text) return text;
    }
  }
  return null;
}

function readOptInErrorDetail(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;

  const value = payload as Record<string, unknown>;
  const detail = formatValidationDetail(value.detail);
  if (detail) return detail;

  // The backend's public error envelope is { error: { code, message, ... } }.
  // Only callers that explicitly set exposeErrorDetail may render it. This is
  // needed by import endpoints that intentionally return administrator-safe
  // row/field diagnostics instead of the global sanitized message.
  const errorDetail = formatValidationDetail(value.error);
  if (errorDetail) return errorDetail;

  return formatValidationDetail(value.message);
}

async function handleResponse(response: Response, exposeErrorDetail = false) {
  const payload = await parseResponse(response);
  if (!response.ok) {
    const fallbackMessage = classifyError(response.status);
    const message = exposeErrorDetail ? readOptInErrorDetail(payload) ?? fallbackMessage : fallbackMessage;
    throw new ApiError(response.status, message, readSafeErrorMeta(payload, response));
  }
  return payload;
}


function parseContentDispositionFilename(contentDisposition: string | null) {
  if (!contentDisposition) return null;
  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return utf8Match[1];
    }
  }
  const quotedMatch = contentDisposition.match(/filename="([^"]+)"/i);
  if (quotedMatch?.[1]) return quotedMatch[1];
  const plainMatch = contentDisposition.match(/filename=([^;]+)/i);
  return plainMatch?.[1]?.trim() ?? null;
}

export interface ApiBlobResponse {
  blob: Blob;
  filename: string | null;
  mediaType: string | null;
}

async function handleBlobResponse(response: Response, exposeErrorDetail = false): Promise<ApiBlobResponse> {
  if (!response.ok) {
    const payload = await parseResponse(response);
    const fallbackMessage = classifyError(response.status);
    const message = exposeErrorDetail ? readOptInErrorDetail(payload) ?? fallbackMessage : fallbackMessage;
    throw new ApiError(response.status, message, readSafeErrorMeta(payload, response));
  }
  return {
    blob: await response.blob(),
    filename: parseContentDispositionFilename(response.headers.get('Content-Disposition')),
    mediaType: response.headers.get('Content-Type'),
  };
}

async function attemptRefresh(traceId: string): Promise<string | null> {
  // Single-flight: if a refresh is already in-flight, join it
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    const refreshUrl = `${getBaseUrl()}/auth/refresh`;
    try {
      const response = await fetch(refreshUrl, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-Trace-ID": traceId,
          "X-Request-ID": createApiRequestId(),
        },
      });
      if (!response.ok) return null;
      const data = await response.json();
      const newToken: string | undefined = data.access_token;
      if (!newToken) return null;
      setApiAccessToken(newToken);
      return newToken;
    } catch {
      return null;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

export async function apiRequest<T>(
  path: string,
  init: ApiRequestOptions = {},
): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, skipRefresh, traceId: requestedTraceId, exposeErrorDetail = false, ...fetchInit } = init;
  const url = `${getBaseUrl()}${normalizePath(path)}`;
  const traceId = normalizeCorrelationId(requestedTraceId, "tr");
  let requestId = createApiRequestId();
  const headers = buildHeaders(fetchInit, traceId, requestId);
  const signal = fetchInit.signal ?? undefined;

  try {
    const response = await requestWithTimeout(url, { ...fetchInit, headers, credentials: "include" }, timeoutMs, signal);
    return (await handleResponse(response, exposeErrorDetail)) as T;
  } catch (error) {
    // If it's a 401, try refresh and retry once
    if (error instanceof ApiError && error.status === 401 && !skipRefresh && path !== "/auth/refresh") {
      const newToken = await attemptRefresh(traceId);
      if (newToken) {
        // Retry the original request with the new token
        const retryHeaders = new Headers(headers);
        retryHeaders.set("Authorization", `Bearer ${newToken}`);
        requestId = createApiRequestId();
        retryHeaders.set("X-Request-ID", requestId);
        try {
          const retryResponse = await requestWithTimeout(url, { ...fetchInit, headers: retryHeaders, credentials: "include" }, timeoutMs, signal);
          return (await handleResponse(retryResponse, exposeErrorDetail)) as T;
        } catch (retryError) {
          if (retryError instanceof ApiError && retryError.status === 401) {
            // Retry also got 401 — token was invalidated between refresh and retry
            onAuthExpired?.();
          }
          throw retryError;
        }
      }
      // Refresh failed
      onAuthExpired?.();
      throw new ApiError(401, "认证已过期，请重新登录", { traceId, requestId });
    }

    // Re-throw abort/timeout as ApiError
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(0, "请求已取消或超时，请重试", { traceId, requestId });
    }
    if (!(error instanceof ApiError)) {
      throw new ApiError(0, classifyError(0), { traceId, requestId });
    }

    throw error;
  }
}

export function toQuery(params: Record<string, string | number | boolean | undefined | null>) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  });
  const text = query.toString();
  return text ? `?${text}` : "";
}


export async function apiRequestBlob(
  path: string,
  init: ApiRequestOptions = {},
): Promise<ApiBlobResponse> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, skipRefresh, traceId: requestedTraceId, exposeErrorDetail = false, ...fetchInit } = init;
  const url = `${getBaseUrl()}${normalizePath(path)}`;
  const traceId = normalizeCorrelationId(requestedTraceId, 'tr');
  let requestId = createApiRequestId();
  const headers = buildHeaders(fetchInit, traceId, requestId);
  const signal = fetchInit.signal ?? undefined;

  try {
    const response = await requestWithTimeout(url, { ...fetchInit, headers, credentials: 'include' }, timeoutMs, signal);
    return await handleBlobResponse(response, exposeErrorDetail);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401 && !skipRefresh && path !== '/auth/refresh') {
      const newToken = await attemptRefresh(traceId);
      if (newToken) {
        const retryHeaders = new Headers(headers);
        retryHeaders.set('Authorization', `Bearer ${newToken}`);
        requestId = createApiRequestId();
        retryHeaders.set('X-Request-ID', requestId);
        try {
          const retryResponse = await requestWithTimeout(url, { ...fetchInit, headers: retryHeaders, credentials: 'include' }, timeoutMs, signal);
          return await handleBlobResponse(retryResponse, exposeErrorDetail);
        } catch (retryError) {
          if (retryError instanceof ApiError && retryError.status === 401) onAuthExpired?.();
          throw retryError;
        }
      }
      onAuthExpired?.();
      throw new ApiError(401, '认证已过期，请重新登录', { traceId, requestId });
    }

    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError(0, '请求已取消或超时，请重试', { traceId, requestId });
    }
    if (!(error instanceof ApiError)) {
      throw new ApiError(0, classifyError(0), { traceId, requestId });
    }
    throw error;
  }
}

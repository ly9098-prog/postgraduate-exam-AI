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

export function setApiAccessToken(token: string | null) {
  accessToken = token;
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

async function handleResponse(response: Response) {
  const payload = await parseResponse(response);
  if (!response.ok) {
    // UI message is derived only from HTTP status. Never surface backend detail/error.message.
    throw new ApiError(response.status, classifyError(response.status), readSafeErrorMeta(payload, response));
  }
  return payload;
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
  const { timeoutMs = DEFAULT_TIMEOUT_MS, skipRefresh, traceId: requestedTraceId, ...fetchInit } = init;
  const url = `${getBaseUrl()}${normalizePath(path)}`;
  const traceId = normalizeCorrelationId(requestedTraceId, "tr");
  let requestId = createApiRequestId();
  const headers = buildHeaders(fetchInit, traceId, requestId);
  const signal = fetchInit.signal ?? undefined;

  try {
    const response = await requestWithTimeout(url, { ...fetchInit, headers, credentials: "include" }, timeoutMs, signal);
    return (await handleResponse(response)) as T;
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
          return (await handleResponse(retryResponse)) as T;
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

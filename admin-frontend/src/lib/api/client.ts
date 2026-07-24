import { ApiError } from "./errors";

const DEFAULT_BASE_URL = "/api/admin/v1";
const DEFAULT_TIMEOUT_MS = 60_000;

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

function readMessage(payload: unknown) {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (typeof detail === "object" && detail !== null) {
      const innerDetail = (detail as { detail?: string }).detail;
      if (typeof innerDetail === "string") return innerDetail;
      const errorCode = (detail as { error_code?: string }).error_code;
      if (typeof errorCode === "string") return `[${errorCode}]`;
    }
  }
  if (payload && typeof payload === "object" && "error" in payload) {
    const error = (payload as { error?: { message?: unknown } }).error;
    if (typeof error?.message === "string") return error.message;
  }
  return "请求失败，请稍后重试";
}

function classifyError(status: number): string {
  switch (status) {
    case 403: return "没有权限执行此操作";
    case 404: return "请求的资源不存在";
    case 409: return "资源冲突，请刷新后重试";
    case 422: return "提交的数据校验未通过";
    case 429: return "请求过于频繁，请稍后重试";
    default:
      if (status >= 500) return "服务器内部错误，请稍后重试";
      return "请求失败，请稍后重试";
  }
}

function buildHeaders(init: RequestInit): Headers {
  const headers = new Headers(init.headers);
  // FormData must not have Content-Type set manually — browser sets it with boundary
  if (!headers.has("Content-Type") && init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const token = getApiAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return headers;
}

interface ApiRequestOptions extends RequestInit {
  /** Override default timeout in ms. 0 = no timeout. */
  timeoutMs?: number;
  /** Skip auto-refresh on 401 for this request. */
  skipRefresh?: boolean;
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
    const message = readMessage(payload) || classifyError(response.status);
    throw new ApiError(response.status, message, payload);
  }
  return payload;
}

async function attemptRefresh(): Promise<string | null> {
  // Single-flight: if a refresh is already in-flight, join it
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    const refreshUrl = `${getBaseUrl()}/auth/refresh`;
    try {
      const response = await fetch(refreshUrl, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
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
  const { timeoutMs = DEFAULT_TIMEOUT_MS, skipRefresh, ...fetchInit } = init;
  const url = `${getBaseUrl()}${normalizePath(path)}`;
  const headers = buildHeaders(fetchInit);
  const signal = fetchInit.signal ?? undefined;

  try {
    const response = await requestWithTimeout(url, { ...fetchInit, headers, credentials: "include" }, timeoutMs, signal);
    return (await handleResponse(response)) as T;
  } catch (error) {
    // If it's a 401, try refresh and retry once
    if (error instanceof ApiError && error.status === 401 && !skipRefresh && path !== "/auth/refresh") {
      const newToken = await attemptRefresh();
      if (newToken) {
        // Retry the original request with the new token
        const retryHeaders = new Headers(headers);
        retryHeaders.set("Authorization", `Bearer ${newToken}`);
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
      throw new ApiError(401, "认证已过期，请重新登录", null);
    }

    // Re-throw abort/timeout as ApiError
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(0, "请求已取消或超时", null);
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

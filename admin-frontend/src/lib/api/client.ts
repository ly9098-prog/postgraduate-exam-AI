import { ApiError } from "./errors";

const DEFAULT_BASE_URL = "http://localhost:8000/api/admin/v1";

let accessToken: string | null = null;

export function setApiAccessToken(token: string | null) {
  accessToken = token;
}

export function getApiAccessToken() {
  return accessToken;
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
  }
  if (payload && typeof payload === "object" && "error" in payload) {
    const error = (payload as { error?: { message?: unknown } }).error;
    if (typeof error?.message === "string") return error.message;
  }
  return "请求失败，请稍后重试";
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body) headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const response = await fetch(`${getBaseUrl()}${normalizePath(path)}`, {
    ...init,
    headers,
    credentials: "include",
  });
  const payload = await parseResponse(response);

  if (!response.ok) {
    throw new ApiError(response.status, readMessage(payload), payload);
  }

  return payload as T;
}

export function toQuery(params: Record<string, string | number | boolean | undefined | null>) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  });
  const text = query.toString();
  return text ? `?${text}` : "";
}

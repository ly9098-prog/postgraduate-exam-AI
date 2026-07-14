import { describe, it, expect, beforeEach, vi } from "vitest";
import { apiRequest, setApiAccessToken, setApiAccessTokenProvider, setOnAuthExpired } from "./client";
import { ApiError } from "./errors";

beforeEach(() => {
  setApiAccessToken("test-token");
  setApiAccessTokenProvider(null);
  setOnAuthExpired(null);
  vi.restoreAllMocks();
});

function mockFetch(status: number, body: unknown) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("apiRequest — auth refresh", () => {
  it("succeeds on first try without refresh", async () => {
    const fetch = mockFetch(200, { data: "ok" });
    const result = await apiRequest("/test");
    expect(result).toEqual({ data: "ok" });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("refreshes token once on 401 and retries", async () => {
    let callCount = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      callCount++;
      if (callCount === 1) {
        return new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401, headers: { "Content-Type": "application/json" } });
      }
      if (callCount === 2) {
        return new Response(JSON.stringify({ access_token: "new-token" }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response(JSON.stringify({ data: "ok" }), { status: 200, headers: { "Content-Type": "application/json" } });
    });

    const result = await apiRequest("/test");
    expect(result).toEqual({ data: "ok" });
    expect(callCount).toBe(3);
  });

  it("only does one refresh for concurrent 401s (single-flight)", async () => {
    let refreshCount = 0;
    let normalCount = 0;

    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      const path = typeof url === "string" ? url : "";
      const headers = init instanceof Request ? init.headers : init?.headers;

      if (path.includes("/auth/refresh")) {
        refreshCount++;
        return new Response(JSON.stringify({ access_token: "new-token" }), { status: 200, headers: { "Content-Type": "application/json" } });
      }

      normalCount++;
      // Succeed on retry (call after refresh)
      if (normalCount > 3) {
        return new Response(JSON.stringify({ data: "ok" }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401, headers: { "Content-Type": "application/json" } });
    });

    const [r1, r2, r3] = await Promise.allSettled([
      apiRequest("/test1"),
      apiRequest("/test2"),
      apiRequest("/test3"),
    ]);

    const succeeded = [r1, r2, r3].filter((r) => r.status === "fulfilled");
    expect(succeeded.length).toBeGreaterThanOrEqual(1);
    // Only one refresh should have been triggered for all concurrent 401s
    expect(refreshCount).toBe(1);
  });

  it("calls onAuthExpired when refresh fails", async () => {
    const onExpired = vi.fn();
    setOnAuthExpired(onExpired);

    let callCount = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      callCount++;
      return new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401, headers: { "Content-Type": "application/json" } });
    });

    await expect(apiRequest("/test")).rejects.toThrow(ApiError);
    expect(onExpired).toHaveBeenCalled();
  });

  it("does not retry /auth/refresh itself", async () => {
    let refreshAttempts = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const path = typeof url === "string" ? url : "";
      if (path.includes("/auth/refresh")) {
        refreshAttempts++;
      }
      return new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401, headers: { "Content-Type": "application/json" } });
    });

    await expect(apiRequest("/auth/refresh")).rejects.toThrow(ApiError);
    expect(refreshAttempts).toBe(1);
  });
});

describe("apiRequest — timeout and abort", () => {
  it("throws on timeout", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          const signal = (init as RequestInit | undefined)?.signal;
          if (signal) {
            signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
          }
        }),
    );
    await expect(apiRequest("/test", { timeoutMs: 50 })).rejects.toThrow(ApiError);
  });

  it("throws on external abort", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          const signal = (init as RequestInit | undefined)?.signal;
          if (signal) {
            signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
          }
        }),
    );
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 10);
    await expect(apiRequest("/test", { signal: controller.signal })).rejects.toThrow(ApiError);
  });
});

describe("apiRequest — status code errors", () => {
  it("throws ApiError with correct status for 403", async () => {
    mockFetch(403, { detail: "Forbidden" });
    try { await apiRequest("/test"); expect.unreachable(); }
    catch (e) { expect(e).toBeInstanceOf(ApiError); expect((e as ApiError).status).toBe(403); }
  });

  it("throws ApiError with correct status for 404", async () => {
    mockFetch(404, { detail: "Not found" });
    try { await apiRequest("/test"); expect.unreachable(); }
    catch (e) { expect(e).toBeInstanceOf(ApiError); expect((e as ApiError).status).toBe(404); }
  });

  it("throws ApiError with correct status for 422", async () => {
    mockFetch(422, { detail: "Validation error" });
    try { await apiRequest("/test"); expect.unreachable(); }
    catch (e) { expect(e).toBeInstanceOf(ApiError); expect((e as ApiError).status).toBe(422); }
  });

  it("throws ApiError with correct status for 429", async () => {
    mockFetch(429, { detail: "Too many requests" });
    try { await apiRequest("/test"); expect.unreachable(); }
    catch (e) { expect(e).toBeInstanceOf(ApiError); expect((e as ApiError).status).toBe(429); }
  });

  it("throws ApiError with correct status for 500", async () => {
    mockFetch(500, { detail: "Server error" });
    try { await apiRequest("/test"); expect.unreachable(); }
    catch (e) { expect(e).toBeInstanceOf(ApiError); expect((e as ApiError).status).toBe(500); }
  });
});

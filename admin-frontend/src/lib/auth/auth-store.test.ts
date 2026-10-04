import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  apiRequest,
  apiRequestBlob,
  getApiAccessToken,
  readStoredApiAccessToken,
  setApiAccessToken,
} from "@/lib/api/client";
import { useAuthStore } from "./auth-store";

const EXPIRED_TOKEN = "expired-access-token";
const FRESH_TOKEN = "fresh-access-token";

beforeEach(() => {
  const storage = new Map<string, string>();
  vi.stubGlobal("sessionStorage", {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  });
  useAuthStore.getState().clear();
  useAuthStore.setState({ accessToken: EXPIRED_TOKEN, isAuthenticated: true });
  setApiAccessToken(EXPIRED_TOKEN);
});

afterEach(() => {
  useAuthStore.getState().clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function mockSuccessfulRotation() {
  let refreshCount = 0;
  const businessTokens: (string | null)[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (String(input).endsWith("/auth/refresh")) {
      refreshCount++;
      return Response.json({ access_token: FRESH_TOKEN });
    }
    const token = new Headers(init?.headers).get("Authorization");
    businessTokens.push(token);
    if (token === `Bearer ${EXPIRED_TOKEN}`) {
      return Response.json({ detail: "Unauthorized" }, { status: 401 });
    }
    return Response.json({ data: "ok" });
  });
  return { refreshCount: () => refreshCount, businessTokens };
}

describe("auth store — API token synchronization", () => {
  it.each(["json", "blob"] as const)(
    "reuses the rotated token for subsequent %s and JSON requests",
    async (kind) => {
      const rotation = mockSuccessfulRotation();
      if (kind === "blob") await apiRequestBlob("/mock-download");
      else await apiRequest("/mock-resource");
      await apiRequest("/mock-next");
      await apiRequestBlob("/mock-next-download");

      expect(rotation.refreshCount()).toBe(1);
      expect(rotation.businessTokens).toEqual([
        `Bearer ${EXPIRED_TOKEN}`,
        `Bearer ${FRESH_TOKEN}`,
        `Bearer ${FRESH_TOKEN}`,
        `Bearer ${FRESH_TOKEN}`,
      ]);
      expect(useAuthStore.getState().accessToken).toBe(FRESH_TOKEN);
      expect(getApiAccessToken()).toBe(FRESH_TOKEN);
      expect(readStoredApiAccessToken()).toBe(FRESH_TOKEN);
    },
  );

  it("shares one rotation across concurrent 401s and the next request", async () => {
    const rotation = mockSuccessfulRotation();
    await Promise.all([
      apiRequest("/mock-first"),
      apiRequest("/mock-second"),
      apiRequestBlob("/mock-download"),
    ]);
    await apiRequest("/mock-next");

    expect(rotation.refreshCount()).toBe(1);
    expect(useAuthStore.getState().accessToken).toBe(FRESH_TOKEN);
    expect(getApiAccessToken()).toBe(FRESH_TOKEN);
  });

  it("synchronizes explicit token updates and clearing with the store", () => {
    setApiAccessToken(FRESH_TOKEN);
    expect(useAuthStore.getState().accessToken).toBe(FRESH_TOKEN);
    expect(readStoredApiAccessToken()).toBe(FRESH_TOKEN);

    setApiAccessToken(null);
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(getApiAccessToken()).toBeNull();
    expect(readStoredApiAccessToken()).toBeNull();
  });

  it("clears all token state when refresh fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({ detail: "Unauthorized" }, { status: 401 }),
    );

    await expect(apiRequest("/mock-resource")).rejects.toMatchObject({ status: 401 });
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(getApiAccessToken()).toBeNull();
    expect(readStoredApiAccessToken()).toBeNull();
  });

  it("reuses a stored token on bootstrap without rotating the refresh cookie", async () => {
    useAuthStore.setState({ isAuthenticated: false, isBootstrapping: true });
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({ user: { id: 1 }, role: null, permissions: [] }),
    );

    await useAuthStore.getState().bootstrap();

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(String(fetch.mock.calls[0][0])).toMatch(/\/auth\/me$/);
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
    expect(getApiAccessToken()).toBe(EXPIRED_TOKEN);
  });
});

"use client";

import { create } from "zustand";
import { apiRequest, setApiAccessToken, setApiAccessTokenProvider, setOnAuthExpired } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { AuthUser, LoginResponse, MeResponse, Role } from "@/lib/api/types";

type AuthState = {
  accessToken: string | null;
  user: AuthUser | MeResponse | null;
  role: Role | null;
  permissions: string[];
  isAuthenticated: boolean;
  isBootstrapping: boolean;
  needsTwoFactor: boolean;
  pendingToken: string | null;
  login: (username: string, password: string) => Promise<void>;
  verifyTwoFactor: (code: string) => Promise<void>;
  cancelTwoFactor: () => void;
  logout: () => Promise<void>;
  bootstrap: () => Promise<void>;
  setPermissions: (permissions: string[]) => void;
  clear: () => void;
};

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: null,
  user: null,
  role: null,
  permissions: [],
  isAuthenticated: false,
  isBootstrapping: true,
  needsTwoFactor: false,
  pendingToken: null,
  async login(username, password) {
    const data = await apiRequest<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    if (data.two_factor_required && data.pending_token) {
      set({
        needsTwoFactor: true,
        pendingToken: data.pending_token,
        user: data.user ?? null,
        role: data.role ?? null,
        permissions: data.permissions ?? [],
        isAuthenticated: false,
        isBootstrapping: false,
      });
      return;
    }
    set({
      accessToken: data.access_token ?? null,
      user: data.user ?? null,
      role: data.role ?? null,
      permissions: data.permissions ?? [],
      isAuthenticated: Boolean(data.access_token),
      isBootstrapping: false,
      needsTwoFactor: false,
      pendingToken: null,
    });
    setApiAccessToken(data.access_token ?? null);
  },
  async verifyTwoFactor(code) {
    const pendingToken = get().pendingToken;
    if (!pendingToken) throw new ApiError(401, "2FA 会话已失效，请重新登录", null);
    const data = await apiRequest<LoginResponse>("/auth/2fa/verify", {
      method: "POST",
      skipRefresh: true,
      body: JSON.stringify({ pending_token: pendingToken, code }),
    });
    set({
      accessToken: data.access_token ?? null,
      user: data.user ?? null,
      role: data.role ?? null,
      permissions: data.permissions ?? [],
      isAuthenticated: Boolean(data.access_token),
      isBootstrapping: false,
      needsTwoFactor: false,
      pendingToken: null,
    });
    setApiAccessToken(data.access_token ?? null);
  },
  cancelTwoFactor() {
    set({ needsTwoFactor: false, pendingToken: null });
  },
  async logout() {
    try {
      if (get().accessToken) await apiRequest<{ status: string }>("/auth/logout", { method: "POST", skipRefresh: true });
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) throw error;
    } finally {
      get().clear();
    }
  },
  async bootstrap() {
    if (get().isAuthenticated) {
      set({ isBootstrapping: false });
      return;
    }

    const token = get().accessToken;
    if (token) {
      setApiAccessToken(token);
      try {
        const me = await apiRequest<MeResponse>("/auth/me");
        set({
          user: me.user,
          role: me.role,
          permissions: me.permissions,
          isAuthenticated: true,
          isBootstrapping: false,
        });
        return;
      } catch {
        setApiAccessToken(null);
        set({ accessToken: null });
      }
    }

    try {
      const refresh = await apiRequest<LoginResponse>("/auth/refresh", { method: "POST", skipRefresh: true });
      set({
        accessToken: refresh.access_token ?? null,
        user: refresh.user ?? null,
        role: refresh.role ?? null,
        permissions: refresh.permissions ?? [],
        isAuthenticated: Boolean(refresh.access_token),
        isBootstrapping: false,
      });
      setApiAccessToken(refresh.access_token ?? null);
    } catch {
      get().clear();
    }
  },
  setPermissions(permissions) {
    set({ permissions });
  },
  clear() {
    setApiAccessToken(null);
    set({
      accessToken: null,
      user: null,
      role: null,
      permissions: [],
      isAuthenticated: false,
      isBootstrapping: false,
      needsTwoFactor: false,
      pendingToken: null,
    });
  },
}));

setApiAccessTokenProvider(() => useAuthStore.getState().accessToken);

// When the API client detects an expired session during automated refresh,
// clear auth state so the AuthGuard / middleware redirects to login.
setOnAuthExpired(() => {
  useAuthStore.getState().clear();
});

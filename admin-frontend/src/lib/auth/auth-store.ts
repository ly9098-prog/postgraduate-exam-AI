"use client";

import { create } from "zustand";
import { apiRequest, setApiAccessToken, setApiAccessTokenProvider } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { AuthUser, LoginResponse, MeResponse, Role } from "@/lib/api/types";

type AuthState = {
  accessToken: string | null;
  user: AuthUser | MeResponse | null;
  role: Role | null;
  permissions: string[];
  isAuthenticated: boolean;
  isBootstrapping: boolean;
  login: (username: string, password: string) => Promise<void>;
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
  async login(username, password) {
    const data = await apiRequest<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    set({
      accessToken: data.access_token,
      user: data.user,
      role: data.role,
      permissions: data.permissions ?? [],
      isAuthenticated: true,
      isBootstrapping: false,
    });
    setApiAccessToken(data.access_token);
  },
  async logout() {
    try {
      if (get().accessToken) await apiRequest<{ status: string }>("/auth/logout", { method: "POST" });
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
      const refresh = await apiRequest<LoginResponse>("/auth/refresh", { method: "POST" });
      set({
        accessToken: refresh.access_token,
        user: refresh.user,
        role: refresh.role,
        permissions: refresh.permissions,
        isAuthenticated: true,
        isBootstrapping: false,
      });
      setApiAccessToken(refresh.access_token);
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
    });
  },
}));

setApiAccessTokenProvider(() => useAuthStore.getState().accessToken);

"use client";

import { LogOut, Menu, UserRound } from "lucide-react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/lib/auth/auth-store";

function getUserName(user: unknown) {
  if (user && typeof user === "object" && "username" in user && typeof user.username === "string") return user.username;
  return "Admin";
}

export function Topbar() {
  const router = useRouter();
  const user = useAuthStore((state) => state.user);
  const role = useAuthStore((state) => state.role);
  const logout = useAuthStore((state) => state.logout);

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

  return (
    <header className="sticky top-0 z-20 border-b border-[var(--color-border)] bg-[rgba(247,245,240,0.8)] px-4 py-4 backdrop-blur-xl lg:px-8">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <button className="grid h-10 w-10 place-items-center rounded-xl border border-[var(--color-border)] bg-white/70 text-[var(--color-text-secondary)] lg:hidden">
            <Menu className="h-5 w-5" />
          </button>
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.28em] text-[var(--color-text-hint)]">Operations Console</p>
            <h1 className="font-display text-2xl font-bold text-[var(--ink)]">后台管理系统</h1>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="hidden items-center gap-3 rounded-2xl border border-[var(--color-border)] bg-white/70 px-4 py-2 md:flex">
            <UserRound className="h-4 w-4 text-[var(--color-primary)]" />
            <div>
              <div className="text-sm font-semibold text-[var(--ink)]">{getUserName(user)}</div>
              <div className="text-xs text-[var(--color-text-hint)]">{role?.display_name ?? role?.name ?? "会话内存态"}</div>
            </div>
          </div>
          <Button variant="ghost" onClick={handleLogout}>
            <LogOut className="h-4 w-4" />
            登出
          </Button>
        </div>
      </div>
    </header>
  );
}

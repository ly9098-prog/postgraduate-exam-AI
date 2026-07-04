"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo } from "react";
import { Sidebar } from "./sidebar";
import { Topbar } from "./topbar";
import { useAuthBootstrap } from "@/lib/auth/use-auth-bootstrap";
import { useAuthStore } from "@/lib/auth/auth-store";

function SidebarSkeleton() {
  return (
    <aside className="hidden h-full w-72 shrink-0 border-r border-[var(--color-border)] bg-[rgba(255,253,248,0.82)] px-5 py-6 lg:block">
      {/* Logo skeleton */}
      <div className="mb-8 flex items-center gap-3">
        <div className="h-12 w-12 rounded-2xl bg-[var(--color-border)]" />
        <div className="space-y-1.5">
          <div className="h-5 w-28 rounded bg-[var(--color-border)]" />
          <div className="h-3 w-20 rounded bg-[var(--color-border)]" />
        </div>
      </div>
      {/* Nav links skeleton */}
      <div className="space-y-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 rounded-2xl px-4 py-3">
            <div className="h-5 w-5 rounded bg-[var(--color-border)]" />
            <div className="space-y-1">
              <div className="h-3.5 w-24 rounded bg-[var(--color-border)]" />
              <div className="h-3 w-16 rounded bg-[var(--color-border)]" />
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}

function TopbarSkeleton() {
  return (
    <header className="sticky top-0 z-20 border-b border-[var(--color-border)] bg-[rgba(247,245,240,0.8)] px-4 py-4 backdrop-blur-xl lg:px-8">
      <div className="flex items-center justify-between gap-4">
        <div className="space-y-1.5">
          <div className="h-3 w-36 rounded bg-[var(--color-border)]" />
          <div className="h-6 w-44 rounded bg-[var(--color-border)]" />
        </div>
        <div className="flex items-center gap-3">
          <div className="h-10 w-32 rounded-2xl bg-[var(--color-border)]" />
          <div className="h-10 w-16 rounded-xl bg-[var(--color-border)]" />
        </div>
      </div>
    </header>
  );
}

function MainContentSkeleton() {
  return (
    <div className="space-y-5 p-6 lg:px-8">
      {/* Filter bar skeleton */}
      <div className="flex flex-wrap gap-3">
        <div className="h-11 w-full max-w-xs rounded-xl bg-[var(--color-border)]" />
        <div className="h-11 w-32 rounded-xl bg-[var(--color-border)]" />
        <div className="h-11 w-28 rounded-xl bg-[var(--color-border)]" />
        <div className="h-11 w-24 rounded-xl bg-[var(--color-border)]" />
      </div>
      {/* List skeleton */}
      <div className="space-y-2.5">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="animate-pulse rounded-xl border border-[var(--color-border)] bg-white/70 p-4 motion-reduce:animate-none"
          >
            <div className="flex flex-wrap items-center gap-3">
              <div className="h-5 w-16 rounded-full bg-[var(--color-border)]" />
              <div className="h-5 w-14 rounded-full bg-[var(--color-border)]" />
              <div className="h-4 w-36 rounded bg-[var(--color-border)]" />
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-4">
              <div className="h-3 w-32 rounded bg-[var(--color-border)]" />
              <div className="h-3 w-20 rounded bg-[var(--color-border)]" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function AdminShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isBootstrapping = useAuthStore((state) => state.isBootstrapping);
  useAuthBootstrap();

  const redirectPath = useMemo(() => {
    if (pathname === "/login") return "";
    return `?next=${encodeURIComponent(pathname)}`;
  }, [pathname]);

  useEffect(() => {
    if (!isBootstrapping && !isAuthenticated) {
      router.replace(`/login${redirectPath}`);
    }
  }, [isAuthenticated, isBootstrapping, router, redirectPath]);

  // Bootstrapping: render skeleton layout matching real structure
  if (isBootstrapping) {
    return (
      <div className="flex h-dvh min-h-dvh overflow-hidden">
        <SidebarSkeleton />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopbarSkeleton />
          <main className="min-h-0 flex-1 overflow-y-auto">
            <MainContentSkeleton />
          </main>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) return null;

  return (
    <div className="flex h-dvh min-h-dvh overflow-hidden">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <main className="min-h-0 flex-1 overflow-y-auto px-4 py-6 lg:px-8">
          {children}
        </main>
      </div>
    </div>
  );
}

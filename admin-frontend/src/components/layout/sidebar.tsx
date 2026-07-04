"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import { adminRoutes } from "@/lib/routes";
import { cn } from "@/lib/utils";

export function Sidebar() {
  const pathname = usePathname();
  const permissions = useAuthStore((state) => state.permissions);
  const role = useAuthStore((state) => state.role);
  const visibleRoutes = role?.name === "super_admin" ? adminRoutes : adminRoutes.filter((route) => hasPermission(permissions, route.permission));

  return (
    <aside className="hidden sticky top-0 h-full w-72 shrink-0 overflow-y-auto border-r border-[var(--color-border)] bg-[rgba(255,253,248,0.82)] px-5 py-6 backdrop-blur-xl lg:block">
      <Link href="/dashboard" className="mb-8 flex items-center gap-3">
        <div className="grid h-12 w-12 place-items-center rounded-2xl border border-[var(--color-primary)] bg-[var(--color-primary)] font-display text-xl font-black text-white shadow-[var(--shadow-crisp)]">
          MG
        </div>
        <div>
          <div className="font-display text-xl font-bold tracking-tight text-[var(--ink)]">MemoGrad</div>
          <div className="font-mono text-xs uppercase tracking-[0.28em] text-[var(--color-text-hint)]">Admin Lab</div>
        </div>
      </Link>

      <nav className="space-y-2">
        {visibleRoutes.map((route) => {
          const Icon = route.icon;
          const active = pathname === route.href || pathname.startsWith(`${route.href}/`);
          return (
            <Link
              key={route.href}
              href={route.href}
              className={cn(
                "group flex items-center gap-3 rounded-2xl border px-4 py-3 transition",
                active
                  ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary-dark)] shadow-[var(--shadow-crisp)]"
                  : "border-transparent text-[var(--color-text-secondary)] hover:border-[var(--color-border)] hover:bg-white/70 hover:text-[var(--ink)]",
              )}
            >
              <Icon className="h-5 w-5" />
              <span>
                <span className="block text-sm font-semibold">{route.label}</span>
                <span className="block text-xs text-[var(--color-text-hint)]">{route.description}</span>
              </span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}

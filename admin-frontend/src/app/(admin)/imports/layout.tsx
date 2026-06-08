"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ClipboardCheck, FileQuestion, FileText, History, UploadCloud } from "lucide-react";
import { cn } from "@/lib/utils";

const importTabs = [
  { href: "/imports/questions", label: "题目列表", icon: FileQuestion },
  { href: "/imports/tasks", label: "导入任务", icon: UploadCloud },
  { href: "/imports/text-import", label: "文本导入", icon: FileText },
  { href: "/imports/review", label: "待审核题目", icon: ClipboardCheck },
  { href: "/imports/history", label: "导入记录", icon: History },
];

export default function ImportsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="space-y-6">
      <div>
        <p className="font-mono text-xs uppercase tracking-[0.3em] text-[var(--color-text-hint)]">Import Center</p>
        <h2 className="mt-2 font-display text-4xl font-bold text-[var(--ink)]">题目导入管理</h2>
      </div>
      <nav className="flex flex-wrap gap-2 rounded-3xl border border-[var(--color-border)] bg-white/70 p-2 shadow-[var(--shadow-crisp)]">
        {importTabs.map((tab) => {
          const Icon = tab.icon;
          const active = pathname === tab.href || pathname.startsWith(`${tab.href}/`);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={cn(
                "inline-flex h-11 items-center gap-2 rounded-2xl border px-4 text-sm font-semibold transition",
                active
                  ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]"
                  : "border-transparent text-[var(--color-text-secondary)] hover:border-[var(--color-border)] hover:bg-white hover:text-[var(--ink)]",
              )}
            >
              <Icon className="h-4 w-4" />
              {tab.label}
            </Link>
          );
        })}
      </nav>
      {children}
    </div>
  );
}

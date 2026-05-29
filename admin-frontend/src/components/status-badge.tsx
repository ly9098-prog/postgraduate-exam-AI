import { cn } from "@/lib/utils";

type StatusTone = "success" | "warning" | "danger" | "neutral" | "primary";

const tones: Record<StatusTone, string> = {
  success: "border-[var(--color-success)] bg-[var(--color-success-light)] text-[var(--color-success)]",
  warning: "border-[var(--color-warning)] bg-[var(--color-warning-light)] text-[#9b6f3b]",
  danger: "border-[var(--color-danger)] bg-[var(--color-danger-light)] text-[var(--color-danger)]",
  neutral: "border-[var(--color-border)] bg-white/70 text-[var(--color-text-secondary)]",
  primary: "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]",
};

export function StatusBadge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: StatusTone }) {
  return <span className={cn("inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold", tones[tone])}>{children}</span>;
}

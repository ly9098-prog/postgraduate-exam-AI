import type { ReactNode } from "react";
import { AlertCircle, CheckCircle2, Info, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "accent" | "success" | "warning" | "danger";

type MetricTone = "default" | "accent" | "warning" | "success";

const toneDot: Record<Tone, string> = {
  neutral: "bg-slate-400",
  accent: "bg-[var(--color-primary)]",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  danger: "bg-red-500",
};

export function ManagementPage({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "mgmt-page-enter relative isolate mx-auto w-full max-w-[1580px] space-y-8 pb-16 [--mgmt-line:#dde5ea] [--mgmt-muted:#71818d] [--mgmt-paper:#fffefa] [--mgmt-steel:#edf3f6] [--mgmt-steel-strong:#e4edf2] [--mgmt-shadow:0_16px_50px_rgba(31,49,61,0.055)] before:pointer-events-none before:absolute before:-inset-x-5 before:-bottom-8 before:-top-6 before:-z-10 before:border-x before:border-[rgba(74,111,138,0.055)] before:bg-[linear-gradient(180deg,rgba(255,255,255,0.48),rgba(247,249,250,0.76))] after:pointer-events-none after:absolute after:-left-5 after:top-0 after:-z-10 after:h-28 after:w-px after:bg-[linear-gradient(180deg,var(--color-primary),transparent)]",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function ManagementPageHeader({
  icon,
  title,
  description,
  actions,
  meta,
}: {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <header className="relative border-b border-[var(--mgmt-line)] pb-5 pt-1">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-4">
            {icon ? (
              <div className="relative mt-0.5 grid h-12 w-12 shrink-0 place-items-center rounded-[14px] border border-[rgba(74,111,138,0.22)] bg-[linear-gradient(145deg,#ffffff,var(--mgmt-steel))] text-[var(--color-primary-dark)] shadow-[0_8px_22px_rgba(45,80,104,0.08),inset_0_0_0_1px_rgba(255,255,255,0.78)] before:absolute before:-bottom-1 before:h-1 before:w-5 before:rounded-full before:bg-[rgba(74,111,138,0.70)]">
                {icon}
              </div>
            ) : null}
            <div className="min-w-0">
              <h1 className="text-[30px] font-bold leading-[1.15] tracking-[-0.045em] text-[var(--ink)] md:text-[34px]">
                {title}
              </h1>
              {description ? (
                <p className="mt-2.5 max-w-[78ch] text-[13px] leading-6 text-[var(--color-text-secondary)] md:text-sm">
                  {description}
                </p>
              ) : null}
            </div>
          </div>
          {meta ? (
            <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-[var(--mgmt-muted)] lg:ml-16">
              <span aria-hidden="true" className="h-px w-5 bg-[rgba(74,111,138,0.32)]" />
              {meta}
            </div>
          ) : null}
        </div>
        {actions ? (
          <div className="flex shrink-0 flex-wrap items-center gap-2.5 lg:justify-end lg:pb-0.5">
            {actions}
          </div>
        ) : null}
      </div>
    </header>
  );
}

export function MetricStrip({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <section
      className={cn(
        "grid gap-px overflow-hidden rounded-[18px] border border-[var(--mgmt-line)] bg-[var(--mgmt-line)] shadow-[0_12px_34px_rgba(24,35,45,0.035)]",
        className,
      )}
    >
      {children}
    </section>
  );
}

export function ManagementPanel({
  title,
  description,
  icon,
  actions,
  children,
  className,
  contentClassName,
  variant = "default",
}: {
  title?: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  variant?: "default" | "quiet" | "focus";
}) {
  const hasHeader = title || description || icon || actions;
  return (
    <section
      className={cn(
        "relative overflow-hidden border border-[var(--mgmt-line)] bg-[var(--mgmt-paper)] transition-[border-color,box-shadow] duration-300 motion-reduce:transition-none",
        variant === "default" && "rounded-[18px] shadow-[0_9px_30px_rgba(24,35,45,0.035)]",
        variant === "quiet" && "rounded-[16px] bg-[rgba(255,254,250,0.76)] shadow-none",
        variant === "focus" && "rounded-[20px] border-[rgba(74,111,138,0.30)] shadow-[var(--mgmt-shadow)]",
        className,
      )}
    >
      {variant === "focus" ? (
        <>
          <div className="absolute inset-x-0 top-0 h-[2px] bg-[linear-gradient(90deg,var(--color-primary),rgba(74,111,138,0.14)_52%,transparent)]" />
          <div aria-hidden="true" className="absolute bottom-0 left-0 top-0 w-px bg-[rgba(74,111,138,0.16)]" />
        </>
      ) : null}
      {hasHeader ? (
        <div className="flex flex-col gap-3 border-b border-[var(--mgmt-line)] bg-[linear-gradient(180deg,rgba(237,243,246,0.46),rgba(255,255,255,0.18))] px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            {icon ? (
              <div className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-[9px] border border-[rgba(74,111,138,0.16)] bg-white text-[var(--color-primary-dark)] shadow-[0_4px_12px_rgba(45,80,104,0.05)]">
                {icon}
              </div>
            ) : null}
            <div className="min-w-0">
              {title ? <h2 className="text-[15px] font-bold leading-5 tracking-[-0.015em] text-[var(--ink)]">{title}</h2> : null}
              {description ? <p className="mt-1 max-w-[76ch] text-xs leading-5 text-[var(--color-text-secondary)]">{description}</p> : null}
            </div>
          </div>
          {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2.5">{actions}</div> : null}
        </div>
      ) : null}
      <div className={cn("p-5", contentClassName)}>{children}</div>
    </section>
  );
}

export function MetricCard({
  label,
  value,
  hint,
  tone = "default",
  icon,
  progress,
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  tone?: MetricTone;
  icon?: ReactNode;
  progress?: number;
}) {
  const toneClass = {
    default: "text-[var(--ink)]",
    accent: "text-[var(--color-primary-dark)]",
    warning: "text-amber-700",
    success: "text-emerald-700",
  }[tone];
  const markerClass = {
    default: "bg-slate-300",
    accent: "bg-[var(--color-primary)]",
    warning: "bg-amber-500",
    success: "bg-emerald-500",
  }[tone];

  return (
    <div className="group relative min-w-0 bg-[var(--mgmt-paper)] px-5 py-[18px] transition-[background-color] duration-200 hover:bg-white motion-reduce:transition-none">
      <span aria-hidden="true" className={cn("absolute left-5 top-0 h-[2px] w-8 origin-left scale-x-50 rounded-full opacity-55 transition-[transform,opacity] duration-300 group-hover:scale-x-100 group-hover:opacity-100 motion-reduce:transition-none", markerClass)} />
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-medium leading-5 text-[var(--color-text-secondary)]">{label}</p>
        {icon ? <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-[rgba(237,243,246,0.72)] text-[var(--color-text-hint)] transition-colors duration-200 group-hover:text-[var(--color-primary-dark)]">{icon}</span> : null}
      </div>
      <p className={cn("mt-1.5 text-[27px] font-semibold leading-none tracking-[-0.04em] tabular-nums", toneClass)}>{value}</p>
      {typeof progress === "number" ? <ManagementProgress className="mt-3" value={progress} tone={tone === "default" ? "accent" : tone} /> : null}
      {hint ? (
        <p className="mt-2 min-h-4 truncate text-[11px] leading-4 text-[var(--color-text-tertiary)]" title={typeof hint === "string" ? hint : undefined}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function StatusBadge({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
}) {
  const tones: Record<Tone, string> = {
    neutral: "border-slate-200 bg-white/90 text-slate-600",
    accent: "border-[rgba(74,111,138,0.22)] bg-[var(--mgmt-steel)] text-[var(--color-primary-dark)]",
    success: "border-emerald-200 bg-emerald-50/75 text-emerald-700",
    warning: "border-amber-200 bg-amber-50/85 text-amber-800",
    danger: "border-red-200 bg-red-50/85 text-red-700",
  };

  return (
    <span className={cn("inline-flex min-h-6 items-center gap-1.5 whitespace-nowrap rounded-[7px] border px-2 text-[11px] font-semibold leading-5", tones[tone], className)}>
      <span aria-hidden="true" className={cn("h-1.5 w-1.5 rounded-full", toneDot[tone])} />
      {children}
    </span>
  );
}

export function ManagementNotice({
  title,
  children,
  tone = "info",
  className,
}: {
  title?: ReactNode;
  children: ReactNode;
  tone?: "info" | "success" | "warning" | "danger";
  className?: string;
}) {
  const settings = {
    info: { icon: Info, box: "border-[rgba(74,111,138,0.20)] bg-[rgba(237,243,246,0.70)] text-[var(--color-primary-dark)]" },
    success: { icon: CheckCircle2, box: "border-emerald-200 bg-emerald-50/70 text-emerald-800" },
    warning: { icon: TriangleAlert, box: "border-amber-200 bg-amber-50/82 text-amber-900" },
    danger: { icon: AlertCircle, box: "border-red-200 bg-red-50/82 text-red-800" },
  }[tone];
  const Icon = settings.icon;

  return (
    <div className={cn("flex gap-3 rounded-[14px] border px-4 py-3.5 text-sm shadow-[0_8px_24px_rgba(24,35,45,0.025)]", settings.box, className)}>
      <Icon className="mt-0.5 h-5 w-5 shrink-0" />
      <div className="min-w-0">
        {title ? <p className="font-semibold leading-5">{title}</p> : null}
        <div className={cn("leading-6", title && "mt-1")}>{children}</div>
      </div>
    </div>
  );
}

export function FieldLabel({ children }: { children: ReactNode }) {
  return <span className="mb-1.5 block text-xs font-semibold leading-5 text-[var(--color-text-secondary)]">{children}</span>;
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-36 place-items-center px-5 py-10 text-center text-sm leading-6 text-[var(--color-text-secondary)]">
      <div className="max-w-md">
        <span aria-hidden="true" className="mx-auto mb-3 block h-1.5 w-8 rounded-full bg-[var(--mgmt-line)]" />
        {children}
      </div>
    </div>
  );
}

export function ManagementProgress({
  value,
  max = 100,
  tone = "accent",
  className,
}: {
  value: number;
  max?: number;
  tone?: MetricTone;
  className?: string;
}) {
  const normalizedMax = max > 0 ? max : 100;
  const percentage = Math.max(0, Math.min(100, (value / normalizedMax) * 100));
  const bar = {
    default: "bg-slate-500",
    accent: "bg-[var(--color-primary)]",
    warning: "bg-amber-500",
    success: "bg-emerald-500",
  }[tone];

  return (
    <div
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-[rgba(113,129,141,0.13)]", className)}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={normalizedMax}
      aria-valuenow={Math.max(0, Math.min(normalizedMax, value))}
    >
      <div
        className={cn("h-full origin-left rounded-full transition-[width] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none", bar)}
        style={{ width: `${percentage}%` }}
      />
    </div>
  );
}

export function ManagementSkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="divide-y divide-[var(--mgmt-line)]" aria-hidden="true">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="flex items-center gap-3 px-5 py-4">
          <div className="mgmt-skeleton h-8 w-8 shrink-0 rounded-lg" />
          <div className="min-w-0 flex-1 space-y-2">
            <div className="mgmt-skeleton h-3.5 w-[42%] rounded-full" />
            <div className="mgmt-skeleton h-2.5 w-[68%] rounded-full" />
          </div>
          <div className="mgmt-skeleton h-6 w-16 rounded-lg" />
        </div>
      ))}
    </div>
  );
}

import type { CSSProperties, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

const motionStyles = `
  @keyframes import-enter {
    from { opacity: 0; transform: translate3d(0, 10px, 0); }
    to { opacity: 1; transform: translate3d(0, 0, 0); }
  }
  @keyframes import-panel-swap {
    from { opacity: 0; transform: translate3d(0, 7px, 0); }
    to { opacity: 1; transform: translate3d(0, 0, 0); }
  }
  @keyframes import-popover-in {
    from { opacity: 0; transform: translate3d(0, -4px, 0) scale(.985); }
    to { opacity: 1; transform: translate3d(0, 0, 0) scale(1); }
  }
  @keyframes import-feedback-in {
    from { opacity: 0; transform: translate3d(0, -5px, 0); }
    to { opacity: 1; transform: translate3d(0, 0, 0); }
  }
  @keyframes import-soft-pop {
    0% { opacity: .55; transform: scale(.94); }
    100% { opacity: 1; transform: scale(1); }
  }
  @keyframes import-status-breathe {
    0%, 100% { opacity: .52; transform: scale(.82); }
    50% { opacity: 1; transform: scale(1); }
  }
  @keyframes import-progress-sheen {
    from { transform: translate3d(-115%, 0, 0); }
    to { transform: translate3d(240%, 0, 0); }
  }

  .import-interactive {
    transition-property: color, background-color, border-color, box-shadow, opacity, transform;
    transition-duration: 170ms;
    transition-timing-function: cubic-bezier(.16, 1, .3, 1);
  }
  .import-interactive:active:not(:disabled) { transform: scale(.985); }
  .import-chevron { transition: transform 180ms cubic-bezier(.16, 1, .3, 1); }
  .import-progress-fill {
    transform-origin: left center;
    transition: transform 420ms cubic-bezier(.16, 1, .3, 1), background-color 180ms ease;
  }
  .import-progress-sheen { position: absolute; inset: 0; overflow: hidden; border-radius: inherit; pointer-events: none; }
  .import-progress-sheen::after {
    content: "";
    position: absolute;
    inset: 0 auto 0 0;
    width: 38%;
    transform: translate3d(-115%, 0, 0);
    background: rgba(255,255,255,.34);
  }
  .import-details-body { transform-origin: top center; }

  @media (prefers-reduced-motion: no-preference) {
    .import-enter { animation: import-enter 420ms cubic-bezier(.16, 1, .3, 1) both; }
    .import-panel-swap { animation: import-panel-swap 280ms cubic-bezier(.16, 1, .3, 1) both; }
    .import-feedback-in { animation: import-feedback-in 220ms cubic-bezier(.16, 1, .3, 1) both; }
    .import-popover { animation: import-popover-in 170ms cubic-bezier(.16, 1, .3, 1) both; }
    .import-soft-pop { animation: import-soft-pop 260ms cubic-bezier(.16, 1, .3, 1) both; }
    .import-list-item { animation: import-panel-swap 300ms cubic-bezier(.16, 1, .3, 1) both; }
    .import-status-active { animation: import-status-breathe 1.55s ease-in-out infinite; }
    .import-progress-active .import-progress-sheen::after { animation: import-progress-sheen 1.55s ease-in-out infinite; }
    .import-details-body { animation: import-panel-swap 220ms cubic-bezier(.16, 1, .3, 1) both; }
    .import-drop-icon { transition: transform 220ms cubic-bezier(.16, 1, .3, 1); }
    .import-drop-active .import-drop-icon { transform: translate3d(0, -3px, 0) scale(1.045); }
  }

  @media (prefers-reduced-motion: reduce) {
    .import-enter, .import-panel-swap, .import-feedback-in, .import-popover, .import-soft-pop, .import-list-item, .import-status-active, .import-details-body,
    .import-progress-active .import-progress-sheen::after { animation: none !important; }
    .import-interactive, .import-chevron, .import-progress-fill, .import-drop-icon { transition-duration: 0.01ms !important; }
    .import-interactive:active:not(:disabled), .import-drop-active .import-drop-icon { transform: none; }
  }
`;

export function ImportWorkspaceHeader({
  icon: Icon,
  title,
  description,
  meta,
  actions,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  meta?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <>
      <style>{motionStyles}</style>
      <header className="relative import-enter">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="flex min-w-0 items-start gap-3.5">
            <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-[rgba(74,111,138,0.22)] bg-[var(--color-primary-light)] text-[var(--color-primary-dark)] shadow-[0_6px_20px_rgba(45,80,104,0.07)] import-soft-pop">
              <Icon className="h-[18px] w-[18px]" strokeWidth={1.8} aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <h2 className="font-display text-[26px] font-bold leading-tight tracking-[-0.02em] text-[var(--ink)] sm:text-[30px]">
                {title}
              </h2>
              <p className="mt-1.5 max-w-[68ch] text-sm leading-6 text-[var(--color-text-secondary)]">{description}</p>
            </div>
          </div>
          {(meta || actions) ? (
            <div className="flex shrink-0 flex-wrap items-center gap-2 lg:justify-end">
              {meta}
              {actions}
            </div>
          ) : null}
        </div>
        <div className="mt-5 h-px bg-[var(--color-border-light)]">
          <div className="h-px w-20 bg-[var(--color-primary)]" />
        </div>
      </header>
    </>
  );
}

export function ImportPanelHeader({
  title,
  description,
  trailing,
  className,
}: {
  title: string;
  description?: string;
  trailing?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex min-h-16 items-center justify-between gap-4 border-b border-[var(--color-border-light)] px-5 py-3.5", className)}>
      <div className="min-w-0">
        <h3 className="text-sm font-semibold tracking-[-0.01em] text-[var(--ink)]">{title}</h3>
        {description ? <p className="mt-0.5 text-xs leading-5 text-[var(--color-text-hint)]">{description}</p> : null}
      </div>
      {trailing ? <div className="shrink-0">{trailing}</div> : null}
    </div>
  );
}

export function ImportMetric({
  label,
  value,
  tone = "neutral",
  className,
}: {
  label: string;
  value: ReactNode;
  tone?: "neutral" | "primary" | "success" | "warning" | "danger";
  className?: string;
}) {
  const toneClass = {
    neutral: "text-[var(--ink)]",
    primary: "text-[var(--color-primary-dark)]",
    success: "text-[var(--color-success)]",
    warning: "text-[var(--color-text-primary)]",
    danger: "text-[var(--color-danger)]",
  }[tone];

  return (
    <div className={cn("min-w-0 px-4 py-3 import-interactive hover:bg-white/55", className)}>
      <div className={cn("text-xl font-semibold leading-none tabular-nums tracking-[-0.02em]", toneClass)}>{value}</div>
      <div className="mt-1.5 text-[11px] font-medium text-[var(--color-text-hint)]">{label}</div>
    </div>
  );
}

export function ImportProgressBar({
  value,
  label,
  active = false,
  tone = "primary",
  className,
}: {
  value: number;
  label: string;
  active?: boolean;
  tone?: "primary" | "success" | "danger";
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
  const fillClass = {
    primary: "bg-[var(--color-primary)]",
    success: "bg-[var(--color-success)]",
    danger: "bg-[var(--color-danger)]",
  }[tone];

  return (
    <div
      className={cn("relative h-2 overflow-hidden rounded-full bg-[var(--color-bg-input)]", active && "import-progress-active", className)}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(clamped)}
    >
      <div
        className={cn("absolute inset-0 rounded-full import-progress-fill", fillClass)}
        style={{ transform: `scaleX(${clamped / 100})` } as CSSProperties}
      />
      {active && clamped > 0 && clamped < 100 ? <span className="import-progress-sheen" aria-hidden="true" /> : null}
    </div>
  );
}

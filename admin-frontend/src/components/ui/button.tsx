import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
type ButtonSize = "sm" | "md";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  children: ReactNode;
};

const variants: Record<ButtonVariant, string> = {
  primary: "border-[var(--color-primary-dark)] bg-[var(--color-primary)] text-white shadow-[var(--shadow-crisp)] hover:-translate-y-0.5 hover:bg-[var(--color-primary-dark)]",
  secondary: "border-[var(--color-border)] bg-white/80 text-[var(--color-text-primary)] hover:border-[var(--color-primary)] hover:bg-[var(--color-primary-light)]",
  danger: "border-[var(--color-danger)] bg-[var(--color-danger)] text-white hover:bg-[#ad6262]",
  ghost: "border-transparent bg-transparent text-[var(--color-text-secondary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)]",
};

const sizes: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
};

export function Button({ className, variant = "primary", size = "md", children, ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-xl border font-semibold transition disabled:pointer-events-none disabled:opacity-50",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

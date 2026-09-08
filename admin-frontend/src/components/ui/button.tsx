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
  primary:
    "border-[var(--color-primary-dark)] bg-[var(--color-primary)] text-white shadow-[var(--shadow-crisp)] hover:-translate-y-px hover:bg-[var(--color-primary-dark)] hover:shadow-[0_8px_18px_rgba(45,80,104,0.13)]",
  secondary:
    "border-[var(--color-border)] bg-white/90 text-[var(--color-text-primary)] shadow-[0_3px_10px_rgba(31,49,61,0.025)] hover:-translate-y-px hover:border-[rgba(74,111,138,0.38)] hover:bg-[var(--color-primary-light)]",
  danger:
    "border-[var(--color-danger)] bg-[var(--color-danger)] text-white hover:-translate-y-px hover:bg-[#ad6262]",
  ghost:
    "border-transparent bg-transparent text-[var(--color-text-secondary)] hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)]",
};

const sizes: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
};

export function Button({ className, variant = "primary", size = "md", children, ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-xl border font-semibold leading-none transition-[background-color,border-color,color,box-shadow,transform] duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] focus-visible:ring-offset-2 active:translate-y-0 active:scale-[0.985] disabled:pointer-events-none disabled:translate-y-0 disabled:opacity-50 motion-reduce:transition-none motion-reduce:transform-none",
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

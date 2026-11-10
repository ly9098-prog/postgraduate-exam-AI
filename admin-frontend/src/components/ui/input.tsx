import type { InputHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type InputVariant = "default" | "ghost";

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  variant?: InputVariant;
};

const variants: Record<InputVariant, string> = {
  default:
    "h-11 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.14)]",
  ghost: "h-full rounded-none border-0 bg-transparent px-0 focus:bg-transparent focus:ring-0",
};

export function Input({ className, variant = "default", ...props }: InputProps) {
  return (
    <input
      className={cn(
        "w-full text-sm text-[var(--color-text-primary)] outline-none transition placeholder:text-[var(--color-text-hint)] disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}

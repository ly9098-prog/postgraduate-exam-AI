import type { InputHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-11 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 text-sm text-[var(--color-text-primary)] outline-none transition placeholder:text-[var(--color-text-hint)] focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.14)]",
        className,
      )}
      {...props}
    />
  );
}

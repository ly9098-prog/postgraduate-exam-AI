"use client";

import { cn } from "@/lib/utils";

interface ToggleProps {
  checked: boolean;
  onChange: () => void;
  disabled?: boolean;
  size?: "sm" | "md";
  color?: string;
}

export function Toggle({ checked, onChange, disabled, size = "md", color }: ToggleProps) {
  const height = size === "sm" ? 5 : 6;
  const width = size === "sm" ? 9 : 11;
  const knob = size === "sm" ? 3.5 : 5;
  const translate = size === "sm" ? 120 : 100;

  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={onChange}
      disabled={disabled}
      className={cn(
        "relative inline-flex shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] focus-visible:ring-offset-2",
        disabled && "cursor-not-allowed opacity-50",
      )}
      style={{
        height: `${height * 0.25}rem`,
        width: `${width * 0.25}rem`,
        backgroundColor: checked
          ? color ?? "var(--color-success)"
          : "var(--color-bg-input)",
        borderColor: checked
          ? "transparent"
          : "var(--color-border)",
      }}
    >
      <span
        className="absolute inline-block rounded-full bg-white shadow-sm transition-transform duration-200"
        style={{
          left: "2px",
          top: "2px",
          height: `calc(100% - 4px)`,
          aspectRatio: "1",
          transform: checked ? `translateX(calc(${width * 0.25}rem - 100% - 4px))` : "translateX(0)",
        }}
      />
    </button>
  );
}

import { BarChart3 } from "lucide-react";

/** Difficulty pill */
export function DifficultyBadge({
  difficulty,
}: {
  difficulty: number | string | null | undefined;
}) {
  const d = Number(difficulty) || 0;
  const colors = [
    "bg-emerald-50 text-emerald-700 border-emerald-200",
    "bg-green-50 text-green-700 border-green-200",
    "bg-amber-50 text-amber-700 border-amber-200",
    "bg-orange-50 text-orange-700 border-orange-200",
    "bg-red-50 text-red-700 border-red-200",
  ];
  const idx = Math.min(Math.max(Math.round(d) - 1, 0), colors.length - 1);
  const label = ["简单", "较易", "中等", "较难", "困难"];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${colors[idx]}`}
    >
      <BarChart3 className="h-3 w-3" />
      {label[idx] ?? d}
    </span>
  );
}

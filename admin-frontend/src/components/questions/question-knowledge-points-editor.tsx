"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Plus, Tag, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";

function displayKnowledgePoint(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);

  if (value && typeof value === "object" && !Array.isArray(value)) {
    const record = value as Record<string, unknown>;
    for (const key of ["name", "title", "label", "knowledge_point", "point", "text"]) {
      const candidate = record[key];
      if (typeof candidate === "string" && candidate.trim()) return candidate;
    }

    const scalarValues = Object.values(record)
      .filter((item) => typeof item === "string" || typeof item === "number")
      .map(String)
      .filter(Boolean);
    if (scalarValues.length > 0) return scalarValues.join(" · ");
    return "结构化知识点";
  }

  if (Array.isArray(value)) {
    return value.map(displayKnowledgePoint).filter(Boolean).join(" · ");
  }

  return String(value);
}

export function QuestionKnowledgePointsEditor({
  value,
  onChange,
}: {
  value?: unknown[] | null;
  onChange: (value: unknown[]) => void;
}) {
  const points = useMemo(() => (Array.isArray(value) ? value : []), [value]);
  const [draft, setDraft] = useState("");
  const [removingIndex, setRemovingIndex] = useState<number | null>(null);
  const [enteringIndex, setEnteringIndex] = useState<number | null>(null);
  const timersRef = useRef<number[]>([]);
  const addInputRef = useRef<HTMLInputElement>(null);
  const pointsRef = useRef(points);
  pointsRef.current = points;

  useEffect(() => {
    return () => {
      timersRef.current.forEach((timer) => window.clearTimeout(timer));
    };
  }, []);

  const schedule = (callback: () => void, delay: number) => {
    const timer = window.setTimeout(callback, delay);
    timersRef.current.push(timer);
  };

  const addPoint = () => {
    const text = draft.trim();
    if (!text) {
      addInputRef.current?.focus();
      return;
    }

    const nextIndex = points.length;
    setEnteringIndex(nextIndex);
    onChange([...points, text]);
    setDraft("");
    schedule(() => setEnteringIndex(null), 220);
    requestAnimationFrame(() => addInputRef.current?.focus());
  };

  const updatePoint = (index: number, text: string) => {
    const next = [...points];
    next[index] = text;
    onChange(next);
  };

  const removePoint = (index: number) => {
    if (removingIndex !== null) return;
    setRemovingIndex(index);
    schedule(() => {
      onChange(pointsRef.current.filter((_, itemIndex) => itemIndex !== index));
      setRemovingIndex(null);
    }, 170);
  };

  return (
    <section className="border-t border-slate-200 pt-6">
      <style>{`
        @keyframes knowledgePointEnter {
          from { opacity: 0; transform: translateY(-7px) scale(.985); }
          to { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes knowledgePointExit {
          from { opacity: 1; transform: translateY(0) scale(1); }
          to { opacity: 0; transform: translateY(-5px) scale(.985); }
        }
        .knowledge-point-enter { animation: knowledgePointEnter 190ms cubic-bezier(.2,.8,.2,1); }
        .knowledge-point-exit { animation: knowledgePointExit 170ms ease-in forwards; pointer-events: none; }
        @media (prefers-reduced-motion: reduce) {
          .knowledge-point-enter, .knowledge-point-exit { animation: none !important; }
        }
      `}</style>

      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Tag className="h-4 w-4 text-slate-400" />
            <p className="text-sm font-semibold text-slate-950">知识点</p>
          </div>
          <p className="mt-1.5 pl-6 text-[11px] leading-5 text-slate-400">
            使用简短标签归纳本题核心知识；回车可快速添加。
          </p>
        </div>
        {points.length > 0 ? (
          <span className="shrink-0 rounded-md bg-slate-100 px-2 py-1 text-[10px] font-medium tabular-nums text-slate-500">
            {points.length} 项
          </span>
        ) : null}
      </div>

      {points.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {points.map((point, index) => {
            const isStructured = point !== null && typeof point === "object";
            return (
              <div
                key={`knowledge-point-${index}`}
                className={`group inline-flex max-w-full items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 transition hover:border-slate-300 hover:bg-slate-50 ${
                  enteringIndex === index ? "knowledge-point-enter" : ""
                } ${removingIndex === index ? "knowledge-point-exit" : ""}`}
              >
                <span className="grid h-5 w-5 shrink-0 place-items-center rounded-md bg-slate-100 text-slate-500">
                  <Tag className="h-3 w-3" />
                </span>
                <div className="min-w-0 flex-1">
                  <input
                    className="h-6 min-w-[120px] max-w-[260px] bg-transparent px-1 text-sm text-slate-700 outline-none"
                    value={displayKnowledgePoint(point)}
                    aria-label={`知识点 ${index + 1}`}
                    onChange={(event) => updatePoint(index, event.target.value)}
                  />
                  {isStructured ? (
                    <p className="px-1 text-[9px] text-slate-400">
                      历史结构化数据；仅在修改此项后转换为普通文本。
                    </p>
                  ) : null}
                </div>
                <button
                  type="button"
                  onClick={() => removePoint(index)}
                  disabled={removingIndex !== null}
                  className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-slate-300 opacity-70 transition hover:bg-red-50 hover:text-red-500 group-hover:opacity-100 disabled:cursor-default disabled:opacity-35"
                  aria-label={`删除知识点 ${index + 1}`}
                  title="删除知识点"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50/60 px-4 py-4 text-center">
          <p className="text-xs text-slate-400">暂无知识点，可在下方添加。</p>
        </div>
      )}

      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input
          ref={addInputRef}
          className="h-10 min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none transition placeholder:text-slate-300 focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
          value={draft}
          placeholder="输入知识点，例如：特殊矩阵压缩存储"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              addPoint();
            }
          }}
        />
        <Button
          type="button"
          variant="secondary"
          className="shrink-0 border-slate-200 bg-white shadow-none"
          onClick={addPoint}
          disabled={!draft.trim()}
        >
          <Plus className="h-4 w-4" />
          添加知识点
        </Button>
      </div>
    </section>
  );
}

export function QuestionKnowledgePointsDisplay({ value }: { value?: unknown[] | null }) {
  const points = Array.isArray(value) ? value : [];

  if (points.length === 0) {
    return <span className="text-[var(--color-text-hint)]">—</span>;
  }

  return (
    <div className="flex flex-wrap gap-2">
      {points.map((point, index) => (
        <span
          key={`${index}-${displayKnowledgePoint(point)}`}
          className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-600"
        >
          <Tag className="h-3 w-3 shrink-0 text-slate-400" />
          <span className="break-words">{displayKnowledgePoint(point) || "未命名知识点"}</span>
        </span>
      ))}
    </div>
  );
}

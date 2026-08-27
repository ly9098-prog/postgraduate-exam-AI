"use client";

import type { ReactNode } from "react";
import { AlertTriangle, BookOpen, ClipboardCheck, FileText, type LucideIcon } from "lucide-react";
import { MathFormula } from "@/components/ui/math-formula";

type AnalysisObject = Record<string, unknown>;

type AnalysisSection = {
  key: string;
  title: string;
  description: string;
  value: unknown;
  icon: LucideIcon;
};

const SECTION_META: Record<string, Omit<AnalysisSection, "key" | "value">> = {
  mistakediagnosis: {
    title: "失误诊断",
    description: "定位本题容易出错的判断与思维环节",
    icon: AlertTriangle,
  },
  errordiagnosis: {
    title: "失误诊断",
    description: "定位本题容易出错的判断与思维环节",
    icon: AlertTriangle,
  },
  knowledgepatch: {
    title: "知识补丁",
    description: "补充本题涉及的规则、条件与判断依据",
    icon: BookOpen,
  },
  knowledgepoint: {
    title: "知识补丁",
    description: "补充本题涉及的规则、条件与判断依据",
    icon: BookOpen,
  },
  reviewask: {
    title: "复盘任务",
    description: "整理下一次复习时需要执行的检查动作",
    icon: ClipboardCheck,
  },
  reviewtask: {
    title: "复盘任务",
    description: "整理下一次复习时需要执行的检查动作",
    icon: ClipboardCheck,
  },
  explanation: {
    title: "解题说明",
    description: "题目思路与关键推导",
    icon: FileText,
  },
  solution: {
    title: "解题步骤",
    description: "按步骤梳理解题过程",
    icon: FileText,
  },
  keypoint: {
    title: "关键点",
    description: "本题需要优先关注的信息",
    icon: FileText,
  },
};

function normalizeKey(key: string) {
  return key.toLowerCase().replace(/[\s_-]+/g, "");
}

function titleFromKey(key: string) {
  const normalized = normalizeKey(key);
  if (SECTION_META[normalized]) return SECTION_META[normalized].title;
  return (
    key
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/[_-]+/g, " ")
      .trim()
      .replace(/^./, (char) => char.toUpperCase()) || "补充说明"
  );
}

function stripCodeFence(value: string) {
  const trimmed = value.trim();
  const fenced = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  return fenced ? fenced[1].trim() : trimmed;
}

function tryParseJson(value: string): unknown {
  const candidate = stripCodeFence(value);
  if (!candidate || (!candidate.startsWith("{") && !candidate.startsWith("["))) return null;

  try {
    const parsed = JSON.parse(candidate);
    if (typeof parsed === "string") {
      const nested = stripCodeFence(parsed);
      if (nested.startsWith("{") || nested.startsWith("[")) {
        try {
          return JSON.parse(nested);
        } catch {
          return parsed;
        }
      }
    }
    return parsed;
  } catch {
    return null;
  }
}

function asAnalysisObject(value: string): AnalysisObject | null {
  const parsed = tryParseJson(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  return parsed as AnalysisObject;
}

function isEmpty(value: unknown) {
  return value === null || value === undefined || value === "";
}

function renderScalar(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function StructuredValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    return (
      <ol className="space-y-2.5">
        {value.map((item, index) => (
          <li key={index} className="grid grid-cols-[22px_minmax(0,1fr)] items-start gap-2.5">
            <span className="mt-[3px] grid h-[22px] w-[22px] place-items-center rounded-md bg-[var(--color-bg-input)] text-[10px] font-semibold tabular-nums text-[var(--color-text-hint)]">
              {index + 1}
            </span>
            <div className="min-w-0 leading-7 text-[var(--color-text-secondary)]">
              <MathFormula text={renderScalar(item)} />
            </div>
          </li>
        ))}
      </ol>
    );
  }

  if (value && typeof value === "object") {
    return (
      <dl className="divide-y divide-[var(--color-border-light)]">
        {Object.entries(value as AnalysisObject).map(([key, item]) => (
          <div key={key} className="grid gap-1 py-2.5 first:pt-0 last:pb-0 sm:grid-cols-[112px_minmax(0,1fr)] sm:gap-4">
            <dt className="text-xs font-medium text-[var(--color-text-hint)]">{titleFromKey(key)}</dt>
            <dd className="min-w-0 leading-7 text-[var(--color-text-secondary)]">
              <MathFormula text={renderScalar(item)} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }

  const text = renderScalar(value).trim();
  const paragraphs = text
    .split(/\n{2,}/)
    .map((item) => item.trim())
    .filter(Boolean);

  if (paragraphs.length > 1) {
    return (
      <div className="space-y-2.5">
        {paragraphs.map((paragraph, index) => (
          <p key={index} className="leading-7">
            <MathFormula text={paragraph} />
          </p>
        ))}
      </div>
    );
  }

  return (
    <div className="whitespace-pre-wrap break-words leading-7">
      <MathFormula text={text || "—"} />
    </div>
  );
}

function buildSections(value: AnalysisObject): AnalysisSection[] {
  return Object.entries(value)
    .filter(([, item]) => !isEmpty(item))
    .map(([key, item]) => {
      const normalized = normalizeKey(key);
      const meta = SECTION_META[normalized] ?? {
        title: titleFromKey(key),
        description: "解析补充信息",
        icon: FileText,
      };

      return {
        key,
        value: item,
        ...meta,
      };
    });
}

function AnalysisSectionRow({
  section,
  compact,
  index,
  isLast,
}: {
  section: AnalysisSection;
  compact: boolean;
  index: number;
  isLast: boolean;
}) {
  const Icon = section.icon;

  return (
    <article
      className={`group relative ${compact ? "py-3" : "py-4.5"} ${!isLast ? "border-b border-[var(--color-border-light)]" : ""}`}
    >
      <div className={`grid ${compact ? "grid-cols-[30px_minmax(0,1fr)] gap-2.5" : "grid-cols-[38px_minmax(0,1fr)] gap-3.5"}`}>
        <div className="relative">
          <span
            className={`grid ${compact ? "h-7 w-7" : "h-9 w-9"} place-items-center rounded-xl border border-[#dbe5ef] bg-[#f4f8fc] text-[#527496] transition-colors duration-200 group-hover:border-[#cbd9e6] group-hover:bg-[#edf4fa] group-hover:text-[#365f87]`}
          >
            <Icon className={compact ? "h-3.5 w-3.5" : "h-4 w-4"} strokeWidth={1.8} />
          </span>
          {!compact ? (
            <span className="absolute -right-1 -top-1 grid h-4 min-w-4 place-items-center rounded-full border border-white bg-[#e9f0f6] px-1 text-[9px] font-semibold tabular-nums text-[#6f879d]">
              {String(index + 1).padStart(2, "0")}
            </span>
          ) : null}
        </div>

        <div className="min-w-0">
          <div className={compact ? "mb-1.5" : "mb-2.5"}>
            <h4 className={`${compact ? "text-[13px]" : "text-[15px]"} font-semibold tracking-[0.01em] text-[var(--ink)]`}>
              {section.title}
            </h4>
            {!compact ? (
              <p className="mt-0.5 text-[11px] leading-5 text-[var(--color-text-hint)]">{section.description}</p>
            ) : null}
          </div>

          <div className={`${compact ? "text-[13px]" : "text-sm"} text-[var(--color-text-secondary)]`}>
            <StructuredValue value={section.value} />
          </div>
        </div>
      </div>
    </article>
  );
}

function PlainAnalysis({ value, compact }: { value: string; compact: boolean }) {
  return (
    <div
      className={`${compact ? "px-3.5 py-3" : "px-4 py-3.5"} rounded-xl border border-[var(--color-border-light)] bg-white/55 text-[var(--color-text-secondary)]`}
    >
      <div className={`${compact ? "text-[13px]" : "text-sm"} whitespace-pre-wrap break-words leading-7`}>
        <MathFormula text={value || "—"} />
      </div>
    </div>
  );
}

export function QuestionAnalysis({
  value,
  compact = false,
  className = "",
}: {
  value?: string | null;
  compact?: boolean;
  className?: string;
}) {
  const raw = String(value ?? "").trim();
  if (!raw) return <PlainAnalysis value="—" compact={compact} />;

  const parsed = asAnalysisObject(raw);
  const sections = parsed ? buildSections(parsed) : [];

  if (!parsed) {
    return <PlainAnalysis value={raw} compact={compact} />;
  }

  if (sections.length === 0) {
    return <PlainAnalysis value="—" compact={compact} />;
  }

  return (
    <div
      className={`${compact ? "px-3.5" : "px-4.5"} rounded-xl border border-[var(--color-border-light)] bg-[#fbfcfd]/70 ${className}`}
    >
      {sections.map((section, index) => (
        <AnalysisSectionRow
          key={section.key}
          section={section}
          compact={compact}
          index={index}
          isLast={index === sections.length - 1}
        />
      ))}
    </div>
  );
}

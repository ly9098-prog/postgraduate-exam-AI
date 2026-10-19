import { MathFormula } from "@/components/ui/math-formula";
import { QuestionContentRenderer } from "@/components/question-content-renderer";
import { MultiBlankQuestionOptions } from "@/components/question-options";
import { QuestionAnalysis } from "@/components/questions/question-analysis";
import { QuestionKnowledgePointsDisplay } from "@/components/questions/question-knowledge-points-editor";
import { normalizeBlankOptionGroups, normalizeQuestionOptions } from "@/lib/question-options";
import type { QuestionOptionsValue } from "@/lib/api/types";
import { textFromContent } from "../question-content-editing";
import { versionValueText } from "../question-version-comparison";
import { DifficultyBadge } from "./question-difficulty-badge";

function VersionOptions({ value }: { value: unknown }) {
  const blankGroups = normalizeBlankOptionGroups(value);
  if (blankGroups.length > 0) {
    return <MultiBlankQuestionOptions groups={blankGroups} />;
  }

  const options = normalizeQuestionOptions(value as QuestionOptionsValue | undefined);
  if (options.length === 0) return <span className="text-xs text-slate-400">—</span>;
  return (
    <div className="space-y-1.5">
      {options.map((option) => (
        <div key={option.key} className="flex items-start gap-2 text-xs leading-5 text-slate-600">
          <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded bg-slate-100 font-semibold text-slate-500">
            {option.key}
          </span>
          <div className="min-w-0 flex-1 [overflow-wrap:anywhere]">
            <MathFormula text={option.text || "—"} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function QuestionVersionValue({ label, value, emphasized = false }: {
  label: string; value: unknown; emphasized?: boolean;
}) {
  if (label === "题干") {
    const content = value as Record<string, unknown> | string | null | undefined;
    return (
      <div className={`min-w-0 text-slate-600 [overflow-wrap:anywhere] ${emphasized ? "text-sm leading-7" : "text-xs leading-6"}`}>
        <QuestionContentRenderer
          content={content}
          fallbackText={textFromContent(content)}
          preserveCodeText
        />
      </div>
    );
  }

  if (label === "选项") return <VersionOptions value={value} />;

  if (label === "答案") {
    return (
      <div className="min-w-0 text-xs leading-6 text-slate-600 [overflow-wrap:anywhere]">
        <MathFormula text={value == null || value === "" ? "—" : String(value)} />
      </div>
    );
  }

  if (label === "解析") {
    return (
      <div className="min-w-0 text-xs [&_*]:max-w-full">
        <QuestionAnalysis
          value={typeof value === "string" ? value : value ? JSON.stringify(value) : ""}
          compact
        />
      </div>
    );
  }

  if (label === "知识点") {
    return <QuestionKnowledgePointsDisplay value={Array.isArray(value) ? value : []} />;
  }

  if (label === "难度") {
    const difficulty = Number(value);
    return Number.isFinite(difficulty) ? <DifficultyBadge difficulty={difficulty} /> : <span className="text-xs text-slate-400">—</span>;
  }

  const text = versionValueText(value);
  return <div className="whitespace-pre-wrap break-words text-xs leading-6 text-slate-600">{text}</div>;
}

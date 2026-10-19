import { Loader2 } from "lucide-react";
import { questionVersionFields, type QuestionSnapshot } from "../question-version-comparison";
import { QuestionVersionDiff } from "./question-version-diff";

type ComparisonProps = {
  enabled: boolean;
  questionType: string;
  left: QuestionSnapshot | null | undefined;
  right: QuestionSnapshot | null | undefined;
  leftTitle: string;
  rightTitle: string;
  loading: boolean;
  pendingLabel: string | null;
};

function PendingVersion({ label }: { label: string | null }) {
  return (
    <div className="mb-2 flex justify-end">
      <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-medium text-slate-500">
        <Loader2 className="h-3 w-3 animate-spin" />
        正在切换到 {label ?? "所选版本"}
      </span>
    </div>
  );
}

function ComparisonSkeleton() {
  return (
    <div className="mt-4 space-y-3 animate-pulse">
      <div className="h-24 rounded-xl border border-slate-200 bg-slate-50/60" />
      <div className="h-20 rounded-xl border border-slate-200 bg-slate-50/60" />
      <div className="h-20 rounded-xl border border-slate-200 bg-slate-50/60" />
    </div>
  );
}

function RawVersionData({
  left, right, leftTitle, rightTitle,
}: Pick<ComparisonProps, "left" | "right" | "leftTitle" | "rightTitle">) {
  return (
    <details className="rounded-xl border border-dashed border-slate-200 bg-slate-50/50 px-4 py-3 transition-colors hover:border-slate-300">
      <summary className="cursor-pointer select-none text-xs font-medium text-slate-500 hover:text-slate-700">
        查看原始版本数据
      </summary>
      <pre className="mt-3 max-h-72 overflow-auto rounded-lg bg-white p-3 text-[11px] leading-5 text-slate-500">
        {JSON.stringify({ [leftTitle]: left, [rightTitle]: right }, null, 2)}
      </pre>
    </details>
  );
}

export function QuestionVersionComparison(props: ComparisonProps) {
  const { enabled, questionType, left, right, leftTitle, rightTitle, loading, pendingLabel } = props;
  if (!enabled || !left || !right) return loading ? <ComparisonSkeleton /> : null;
  return (
    <div className="relative mt-4 [overflow-anchor:none]">
      {loading ? <PendingVersion label={pendingLabel} /> : null}
      <div
        key={`${leftTitle}-${rightTitle}`}
        className={`space-y-3 transition-opacity duration-200 ${
          loading ? "opacity-60" : "animate-fade-in opacity-100"
        }`}
      >
        {questionVersionFields(questionType, left, right).map((field) => (
          <QuestionVersionDiff
            key={field.label}
            {...field}
            leftTitle={leftTitle}
            rightTitle={rightTitle}
          />
        ))}
        <RawVersionData left={left} right={right} leftTitle={leftTitle} rightTitle={rightTitle} />
      </div>
    </div>
  );
}

import { versionValueText } from "../question-version-comparison";
import { QuestionVersionValue } from "./question-version-value";

export function QuestionVersionDiff({
  label, leftValue, rightValue, leftTitle, rightTitle,
}: {
  label: string; leftValue: unknown; rightValue: unknown; leftTitle: string; rightTitle: string;
}) {
  const left = versionValueText(leftValue);
  const right = versionValueText(rightValue);
  const changed = left !== right;
  return (
    <section key={label} className={`rounded-xl border border-slate-200 bg-white ${label === "解析" ? "p-3" : "p-4"}`}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-slate-900">{label}</p>
        <span className={`rounded-md px-2 py-1 text-[10px] font-medium ${changed ? "bg-amber-50 text-amber-700" : "bg-slate-100 text-slate-500"}`}>
          {changed ? "有变更" : "无变更"}
        </span>
      </div>
      {changed ? (
        <div className="grid gap-3 md:grid-cols-2">
          <div className={`min-w-0 rounded-lg bg-amber-50/70 ${label === "解析" ? "p-2.5" : "p-3"}`}>
            <p className="mb-2 text-[10px] font-semibold tracking-wide text-amber-700">{leftTitle}</p>
            <QuestionVersionValue label={label} value={leftValue} />
          </div>
          <div className={`min-w-0 rounded-lg bg-emerald-50/60 ${label === "解析" ? "p-2.5" : "p-3"}`}>
            <p className="mb-2 text-[10px] font-semibold tracking-wide text-emerald-700">{rightTitle}</p>
            <QuestionVersionValue label={label} value={rightValue} />
          </div>
        </div>
      ) : (
        <div className="rounded-lg bg-slate-50 p-3"><QuestionVersionValue label={label} value={leftValue} emphasized={label === "题干"} /></div>
      )}
    </section>
  );
}

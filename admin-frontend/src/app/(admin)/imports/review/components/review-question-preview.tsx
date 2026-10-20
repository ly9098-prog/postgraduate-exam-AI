import { QuestionContentRenderer } from "@/components/question-content-renderer";
import { MathFormula } from "@/components/ui/math-formula";
import type { ImportQuestionItem } from "@/lib/api/types";
import { normalizeOptionTextForDisplay, type OptionVisualModel } from "@/lib/option-visual-utils";
import { isMultiBlankChoice, type EditState } from "../review-edit-state";
import { MultiBlankChoicePreview } from "./multi-blank-choice-preview";
import { OptionVisualPreview } from "./option-visual-preview";

type PreviewProps = {
  content: ImportQuestionItem["parsed_content"];
  draft: Pick<EditState, "stem" | "question_type" | "options" | "multiBlank">;
  visualModel: OptionVisualModel;
  onRuntimeIssue: (issue: string) => void;
};

function StemPreview({ content, draft, visualModel }: Omit<PreviewProps, "onRuntimeIssue">) {
  return (
    <section className="animate-fade-up drawer-section-delay-1 section-scroll section-scroll-ink rounded-2xl border border-[var(--color-border)]/80 bg-white/90 p-5 shadow-sm transition-all hover:shadow-md">
      <div className="flex items-center gap-2.5 mb-3">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--color-primary)]/10">
          <span className="text-xs font-bold text-[var(--color-primary)]" style={{ fontFamily: "'Georgia', serif" }}>题</span>
        </span>
        <span className="text-sm font-semibold text-[var(--ink)]">题干</span>
      </div>
      <div className="ml-9 stem-text">
        <QuestionContentRenderer content={content} fallbackText={draft.stem} showTableMetadata ignoredSegmentIds={visualModel.consumedSegmentIds} preserveCodeText />
      </div>
    </section>
  );
}

function RegularOptions({ draft, visualModel, onRuntimeIssue }: Omit<PreviewProps, "content">) {
  if (visualModel.mode !== "none") {
    return <OptionVisualPreview model={visualModel} options={draft.options} onRuntimeIssue={onRuntimeIssue} />;
  }
  if (draft.options.length === 0) {
    return <p className="text-sm text-[var(--color-text-hint)]">（无选项）</p>;
  }
  return (
    <div className="space-y-2">
      {draft.options.map((option) => (
        <div key={option.key} className="flex items-center gap-3">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center option-chip">{option.key}</span>
          <span className="text-sm text-[var(--color-text-secondary)]"><MathFormula text={normalizeOptionTextForDisplay(option.text)} /></span>
        </div>
      ))}
    </div>
  );
}

function OptionsPreview({ draft, visualModel, onRuntimeIssue }: Omit<PreviewProps, "content">) {
  const multiBlank = isMultiBlankChoice(draft.question_type) ? draft.multiBlank : null;
  if (multiBlank && multiBlank.groups.length >= 2) {
    return (
      <section className="animate-fade-up drawer-section-delay-2 section-scroll section-scroll-warm rounded-2xl border border-[var(--color-border)]/80 bg-white/90 p-5 shadow-sm transition-all hover:shadow-md">
        <MultiBlankChoicePreview
          groups={multiBlank.groups}
          answerMap={multiBlank.answerMap}
          usesSharedOptions={multiBlank.usesSharedOptions}
          sharedOptions={multiBlank.sharedOptions}
          stem={draft.stem}
        />
      </section>
    );
  }
  return (
    <section className="animate-fade-up drawer-section-delay-2 section-scroll section-scroll-warm rounded-2xl border border-[var(--color-border)]/80 bg-white/90 p-5 shadow-sm transition-all hover:shadow-md">
      <div className="flex items-center gap-2.5 mb-3">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ backgroundColor: "rgba(196,154,107,0.12)" }}>
          <span className="text-xs font-bold" style={{ color: "#c49a6b", fontFamily: "'Georgia', serif" }}>选</span>
        </span>
        <span className="text-sm font-semibold text-[var(--ink)]">选项</span>
      </div>
      <div className="ml-9">
        <RegularOptions draft={draft} visualModel={visualModel} onRuntimeIssue={onRuntimeIssue} />
      </div>
    </section>
  );
}

export function ReviewQuestionPreview(props: PreviewProps) {
  return (
    <>
      <StemPreview content={props.content} draft={props.draft} visualModel={props.visualModel} />
      <OptionsPreview draft={props.draft} visualModel={props.visualModel} onRuntimeIssue={props.onRuntimeIssue} />
    </>
  );
}

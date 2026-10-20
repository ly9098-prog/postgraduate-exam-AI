import { canonicalizeQuestionType } from "@/lib/question-types";
import type { OptionVisualModel } from "@/lib/option-visual-utils";
import { isMultiBlankChoice, type EditState } from "../review-edit-state";
import { removeReviewOptionSegment, updateReviewOptionText } from "../review-option-editing";
import { MultiBlankChoiceEditor } from "./multi-blank-choice-editor";
import type { MultiBlankAction } from "./multi-blank-choice-utils";
import { OptionVisualEditor } from "./option-visual-editor";

type EditorProps = {
  questionType: string;
  options: EditState["options"];
  multiBlank: EditState["multiBlank"];
  visualModel: OptionVisualModel;
  onOptionsChange: (options: EditState["options"]) => void;
  onMultiBlankAction: (action: MultiBlankAction) => void;
  onRequestTextModeOverride: () => void;
};

function OptionSegment({ segment, onRemove }: {
  segment: Record<string, unknown>;
  onRemove: () => void;
}) {
  const type = String(segment.type ?? "").toLowerCase();
  if (type === "text") return null;
  const isImage = ["image", "math_image", "table_image", "code_image"].includes(type);
  if (!isImage && type !== "newline") return null;
  const label = type === "math_image" ? "公式" : type === "table_image" ? "表格" : type === "code_image" ? "代码" : type === "newline" ? "换行" : "图片";
  return (
    <div className="flex items-center gap-1 rounded-md border border-[var(--color-border)]/50 bg-white/70 px-2 py-1">
      {isImage && segment.url ? (
        <img src={String(segment.url)} alt="" className="h-8 w-8 rounded object-cover" />
      ) : null}
      <span className="text-[10px] text-[var(--color-text-hint)]">{label}</span>
      <button
        type="button"
        className="ml-0.5 flex h-4 w-4 items-center justify-center rounded text-[9px] text-red-400 hover:bg-red-50 hover:text-red-600"
        onClick={onRemove}
        title="移除该片段"
      >✕</button>
    </div>
  );
}

function RegularOptions({ options, onOptionsChange }: Pick<EditorProps, "options" | "onOptionsChange">) {
  return (
    <div className="space-y-2">
      {options.length === 0 ? <p className="text-sm text-[var(--color-text-hint)]">暂无可编辑选项</p> : null}
      {options.map((option, index) => (
        <div key={index} className="flex items-start gap-2">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center option-chip mt-1">{option.key}</span>
          <div className="flex-1 space-y-1.5">
            <input
              className="h-9 w-full rounded-xl border border-[var(--color-border)] bg-white px-3 text-sm outline-none transition focus:border-[var(--color-primary)] focus:ring-2 focus:ring-[var(--color-primary)]/15"
              value={option.text}
              onChange={(event) => onOptionsChange(updateReviewOptionText(options, index, event.target.value))}
            />
            {option.segments && option.segments.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {option.segments.map((segment, segmentIndex) => (
                  <OptionSegment
                    key={segmentIndex}
                    segment={segment}
                    onRemove={() => onOptionsChange(removeReviewOptionSegment(options, index, segmentIndex))}
                  />
                ))}
              </div>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}

function OptionEditorContent(props: EditorProps) {
  const { questionType, options, visualModel, onOptionsChange, onMultiBlankAction, onRequestTextModeOverride } = props;
  const multiBlank = isMultiBlankChoice(questionType) ? (props.multiBlank ?? null) : null;
  if (multiBlank && multiBlank.groups.length >= 2) {
    return (
      <MultiBlankChoiceEditor
        groups={multiBlank.groups}
        answerMap={multiBlank.answerMap}
        usesSharedOptions={multiBlank.usesSharedOptions}
        sharedOptions={multiBlank.sharedOptions}
        multiSelect={canonicalizeQuestionType(questionType) === "multi_blank_multiple_choice"}
        dedupWarnings={multiBlank.dedupWarnings}
        dedupErrors={multiBlank.dedupErrors}
        hasUnappliedDraft={multiBlank.hasUnappliedDraft}
        onAction={onMultiBlankAction}
      />
    );
  }
  if (visualModel.mode !== "none") {
    return (
      <OptionVisualEditor
        model={visualModel}
        options={options}
        onChange={onOptionsChange}
        onRequestTextModeOverride={onRequestTextModeOverride}
      />
    );
  }
  return <RegularOptions options={options} onOptionsChange={onOptionsChange} />;
}

export function ReviewOptionEditor(props: EditorProps) {
  return (
    <section className="animate-fade-up drawer-section-delay-3 rounded-xl border border-[var(--color-border)]/60 bg-white/80 p-4 shadow-sm">
      <div className="mb-3 flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-md" style={{ backgroundColor: "rgba(196,154,107,0.12)" }}>
          <span className="text-[10px] font-bold" style={{ color: "#c49a6b" }}>选</span>
        </span>
        <p className="text-xs font-semibold text-[var(--color-text-secondary)]">选项</p>
      </div>
      <OptionEditorContent {...props} />
    </section>
  );
}

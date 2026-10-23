import type { Dispatch, SetStateAction } from "react";
import { CustomSelect } from "@/components/ui/custom-select";
import type { QuestionEditRequest } from "@/lib/api/types";
import type { QuestionSubjectOption } from "./hooks/use-question-subject-options";
import {
  QUESTION_TYPE_OPTIONS,
  canonicalizeQuestionType,
  formatUnknownType,
} from "@/lib/question-types";

type QuestionEditBasicsProps = {
  editForm: QuestionEditRequest;
  setEditForm: Dispatch<SetStateAction<QuestionEditRequest>>;
  subjectOptions: QuestionSubjectOption[];
};

const difficultyOptions = ["简单", "较易", "中等", "较难", "困难"].map(
  (label, index) => ({ label, value: String(index + 1) }),
);

export function QuestionEditBasics({
  editForm,
  setEditForm,
  subjectOptions,
}: QuestionEditBasicsProps) {
  const questionType = editForm.question_type ?? "";
  const unknownTypeOption = {
    value: questionType,
    label: formatUnknownType(questionType),
    disabled: true,
  };
  const typeOptions = canonicalizeQuestionType(questionType) || !questionType
    ? QUESTION_TYPE_OPTIONS
    : [...QUESTION_TYPE_OPTIONS, unknownTypeOption];

  return (
    <section className="border-b border-slate-200 py-5">
      <div className="grid gap-x-4 gap-y-3 md:grid-cols-3">
        <div className="space-y-1">
          <p className="text-xs font-semibold text-[var(--color-text-secondary)]">科目</p>
          <CustomSelect
            value={String(editForm.subject_id ?? "")}
            onChange={(value) =>
              setEditForm((current) => ({
                ...current,
                subject_id: value ? Number(value) : null,
              }))
            }
            options={subjectOptions.map((subject) => ({
              label: subject.name,
              value: String(subject.id),
            }))}
            placeholder="选择科目"
            clearable={false}
            className="rounded-lg border-slate-200 bg-slate-50/60 shadow-none hover:border-slate-400"
          />
        </div>
        <div className="space-y-1">
          <p className="text-xs font-semibold text-[var(--color-text-secondary)]">题型</p>
          <CustomSelect
            value={questionType}
            onChange={(value) =>
              setEditForm((current) => ({ ...current, question_type: value }))
            }
            options={typeOptions}
            clearable={false}
            className="rounded-lg border-slate-200 bg-slate-50/60 shadow-none hover:border-slate-400"
          />
        </div>
        <div className="space-y-1">
          <p className="text-xs font-semibold text-[var(--color-text-secondary)]">难度</p>
          <CustomSelect
            value={String(editForm.difficulty ?? 3)}
            onChange={(value) =>
              setEditForm((current) => ({ ...current, difficulty: Number(value) }))
            }
            options={difficultyOptions}
            clearable={false}
            className="rounded-lg border-slate-200 bg-slate-50/60 shadow-none hover:border-slate-400"
          />
        </div>
      </div>
    </section>
  );
}

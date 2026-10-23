"use client";

import { QuestionImageField } from "@/components/questions/question-image-field";
import type { AdminQuestion } from "@/lib/api/types";
import { isPlainImageSegment, type ContentSegment } from "./question-content-editing";
import type { QuestionImmediateMutationOwner } from "./hooks/use-question-immediate-mutations";

type QuestionStemEditorProps = {
  stemText: string;
  setStemText: (value: string) => void;
  segments: ContentSegment[];
  fallbackImageUrls: string[];
  questionId: number;
  dirty: boolean;
  beforeDirtyMutation: () => Promise<QuestionImmediateMutationOwner | null>;
  onMutated: (
    question: AdminQuestion,
    owner?: QuestionImmediateMutationOwner,
  ) => void;
};

export function QuestionStemEditor(props: QuestionStemEditorProps) {
  const hasImages = props.segments.some(isPlainImageSegment) ||
    props.fallbackImageUrls.length > 0;

  return (
    <section className="border-b border-slate-200 py-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-950">题干</p>
          <p className="mt-1 text-[11px] text-slate-400">
            编辑题目正文、代码块与题干图片
          </p>
        </div>
      </div>
      <textarea
        wrap="soft"
        spellCheck={false}
        className="min-h-36 w-full resize-y overflow-x-hidden whitespace-pre-wrap break-words rounded-lg border border-slate-200 bg-slate-50/60 px-4 py-3 text-sm leading-7 text-slate-800 outline-none transition [overflow-wrap:anywhere] placeholder:text-slate-300 focus:border-slate-400 focus:bg-white focus:ring-2 focus:ring-slate-100"
        value={props.stemText}
        onChange={(event) => props.setStemText(event.target.value)}
      />
      <div className="mt-4">
        <p className="mb-2 text-xs font-medium text-slate-500">题干图片</p>
        {hasImages ? (
          <div className="space-y-3">
            {props.segments.map((segment, index) =>
              isPlainImageSegment(segment) ? (
                <div key={`${index}-${String(segment.url ?? "")}`} className="w-full max-w-xl">
                  <QuestionImageField
                    questionId={props.questionId}
                    target="stem"
                    valueUrl={typeof segment.url === "string" ? segment.url : null}
                    canDelete
                    dirty={props.dirty}
                    beforeDirtyMutation={props.beforeDirtyMutation}
                    addLabel="更换图片"
                    onMutated={props.onMutated}
                  />
                </div>
              ) : null,
            )}
            {props.fallbackImageUrls.map((url, index) => (
              <div key={`legacy-${url}-${index}`} className="w-full max-w-xl">
                <QuestionImageField
                  questionId={props.questionId}
                  target="stem"
                  valueUrl={url}
                  canDelete
                  dirty={props.dirty}
                  beforeDirtyMutation={props.beforeDirtyMutation}
                  addLabel="更换图片"
                  onMutated={props.onMutated}
                />
              </div>
            ))}
          </div>
        ) : (
          <QuestionImageField
            questionId={props.questionId}
            target="stem"
            dirty={props.dirty}
            beforeDirtyMutation={props.beforeDirtyMutation}
            addLabel="插入题干图片"
            onMutated={props.onMutated}
          />
        )}
      </div>
    </section>
  );
}

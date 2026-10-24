"use client";

import { AlertCircle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { AdminQuestion } from "@/lib/api/types";
import type { QuestionImmediateMutationOwner } from "./hooks/use-question-immediate-mutations";
import type { QuestionSubjectOption } from "./hooks/use-question-subject-options";
import type { QuestionEditRequest } from "@/lib/api/types";
import type { ContentSegment } from "./question-content-editing";
import { QuestionDrawerEditForm } from "./question-drawer-edit-form";
import { QuestionDetailView } from "./question-detail-view";
import { QuestionSecondaryInfo } from "./components/question-secondary-info";
import { QuestionVersionHistorySection } from "./question-version-history-section";
import type { QuestionVersionLabels } from "./question-version-labels";

type QuestionDrawerBodyProps = {
  editing: boolean;
  question?: AdminQuestion | null;
  detailError: boolean;
  editForm: QuestionEditRequest;
  setEditForm: React.Dispatch<React.SetStateAction<QuestionEditRequest>>;
  setStemText: React.Dispatch<React.SetStateAction<string>>;
  stemText: string;
  subjectOptions: QuestionSubjectOption[];
  segments: ContentSegment[];
  fallbackImageUrls: string[];
  dirty: boolean;
  unresolvedTableCount: number;
  emptyCodeCount: number;
  saving: boolean;
  beforeDirtyMutation: () => Promise<QuestionImmediateMutationOwner | null>;
  onMutated: (question: AdminQuestion, owner?: QuestionImmediateMutationOwner) => void;
  cancelEditing: () => void;
  saveEditing: () => void;
  versions: Parameters<typeof QuestionVersionHistorySection>[0]["versions"];
  history: Parameters<typeof QuestionVersionHistorySection>[0]["history"];
  details: Parameters<typeof QuestionVersionHistorySection>[0]["details"];
  labels: QuestionVersionLabels;
  onRetry: () => void;
};

function DetailError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 px-7 text-center">
      <AlertCircle className="h-8 w-8 text-red-400" />
      <div>
        <p className="text-sm font-semibold text-red-700">题目详情加载失败</p>
        <p className="mt-1 text-xs text-slate-400">请检查网络连接后重试。</p>
      </div>
      <Button
        type="button"
        variant="secondary"
        size="sm"
        className="border-slate-200 bg-white shadow-none"
        onClick={onRetry}
      >
        <RotateCcw className="h-3.5 w-3.5" />
        重新加载
      </Button>
    </div>
  );
}

function DetailLoading() {
  return (
    <div className="space-y-3 px-7 py-6">
      <div className="h-16 animate-pulse rounded-xl bg-slate-100" />
      <div className="h-32 animate-pulse rounded-xl bg-slate-100/80" />
      <div className="h-24 animate-pulse rounded-xl bg-slate-100/60" />
    </div>
  );
}

export function QuestionDrawerBody({
  editing,
  question,
  detailError,
  editForm,
  setEditForm,
  setStemText,
  stemText,
  subjectOptions,
  segments,
  fallbackImageUrls,
  dirty,
  unresolvedTableCount,
  emptyCodeCount,
  saving,
  beforeDirtyMutation,
  onMutated,
  cancelEditing,
  saveEditing,
  versions,
  history,
  details,
  labels,
  onRetry,
}: QuestionDrawerBodyProps) {
  if (!question) {
    return detailError ? <DetailError onRetry={onRetry} /> : <DetailLoading />;
  }

  if (editing) {
    return (
      <QuestionDrawerEditForm
        questionId={question.id}
        editForm={editForm}
        setEditForm={setEditForm}
        setStemText={setStemText}
        stemText={stemText}
        subjectOptions={subjectOptions}
        segments={segments}
        fallbackImageUrls={fallbackImageUrls}
        dirty={dirty}
        unresolvedTableCount={unresolvedTableCount}
        emptyCodeCount={emptyCodeCount}
        saving={saving}
        beforeDirtyMutation={beforeDirtyMutation}
        onMutated={onMutated}
        cancelEditing={cancelEditing}
        saveEditing={saveEditing}
      />
    );
  }

  return (
    <>
      <QuestionDetailView question={question} />
      <QuestionVersionHistorySection
        question={question}
        versions={versions}
        history={history}
        details={details}
        labels={labels}
      />
      <QuestionSecondaryInfo question={question} />
    </>
  );
}

"use client";

import type { Dispatch, SetStateAction } from "react";
import { QuestionAnalysisEditor } from "@/components/questions/question-analysis-editor";
import { QuestionKnowledgePointsEditor } from "@/components/questions/question-knowledge-points-editor";
import type { QuestionEditRequest } from "@/lib/api/types";
import type { AdminQuestion } from "@/lib/api/types";
import { QuestionAnswerEditor } from "./question-answer-editor";
import { QuestionEditBasics } from "./question-edit-basics";
import { QuestionEditSubmitFooter } from "./question-edit-submit-footer";
import { QuestionStemEditor } from "./question-stem-editor";
import { QuestionTableEditors } from "./components/question-table-editors";
import { QuestionCodeEditor } from "./components/question-code-editor";
import { QuestionOptionEditor } from "./components/question-option-editor";
import type { ContentSegment } from "./question-content-editing";
import { addQuestionCodeSegment, replaceQuestionSegments } from "./question-segment-editing";
import type { QuestionSubjectOption } from "./hooks/use-question-subject-options";
import type { QuestionImmediateMutationOwner } from "./hooks/use-question-immediate-mutations";

type QuestionDrawerEditFormProps = {
  questionId: number;
  editForm: QuestionEditRequest;
  setEditForm: Dispatch<SetStateAction<QuestionEditRequest>>;
  setStemText: Dispatch<SetStateAction<string>>;
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
};

export function QuestionDrawerEditForm({
  questionId,
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
}: QuestionDrawerEditFormProps) {
  return (
    <div className="question-drawer-edit px-7 pb-24 pt-1">
      <QuestionEditBasics
        editForm={editForm}
        setEditForm={setEditForm}
        subjectOptions={subjectOptions}
      />

      <QuestionStemEditor
        stemText={stemText}
        setStemText={setStemText}
        segments={segments}
        fallbackImageUrls={fallbackImageUrls}
        questionId={questionId}
        dirty={dirty}
        beforeDirtyMutation={beforeDirtyMutation}
        onMutated={onMutated}
      />

      <QuestionTableEditors
        segments={segments}
        onReplace={(next) => setEditForm((current) => replaceQuestionSegments(current, next))}
      />
      <QuestionCodeEditor
        segments={segments}
        onReplace={(next) => setEditForm((current) => replaceQuestionSegments(current, next))}
        onAdd={() => setEditForm(addQuestionCodeSegment)}
      />

      <QuestionOptionEditor
        editForm={editForm}
        editStemText={stemText}
        setEditForm={setEditForm}
        selectedQuestionId={questionId}
        dirty={dirty}
        beforeDirtyMutation={beforeDirtyMutation}
        onMutated={onMutated}
      />

      <QuestionAnswerEditor editForm={editForm} setEditForm={setEditForm} />

      <QuestionKnowledgePointsEditor
        value={editForm.knowledge_points ?? []}
        onChange={(knowledgePoints) =>
          setEditForm((current) => ({
            ...current,
            knowledge_points: knowledgePoints,
          }))
        }
      />

      <QuestionAnalysisEditor
        value={editForm.analysis ?? ""}
        onChange={(analysis) =>
          setEditForm((current) => ({ ...current, analysis }))
        }
      />

      {unresolvedTableCount > 0 ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          仍有 {unresolvedTableCount} 个结构化表格需要人工核验。请检查单元格和合并关系，并点击“标记人工已核验”后再保存。
        </div>
      ) : null}
      {emptyCodeCount > 0 ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          仍有 {emptyCodeCount} 个代码块正文为空。请输入代码内容，或删除空代码块后再保存。
        </div>
      ) : null}

      <QuestionEditSubmitFooter
        cancelEditing={cancelEditing}
        saveEditing={saveEditing}
        saving={saving}
        dirty={dirty}
        unresolvedTableCount={unresolvedTableCount}
        emptyCodeCount={emptyCodeCount}
      />
    </div>
  );
}

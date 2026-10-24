"use client";

import type { ReactNode } from "react";
import { QuestionDrawerHeader } from "./question-drawer-header";

type QuestionDetailDrawerProps = {
  open: boolean;
  questionId: number | null;
  editing: boolean;
  dirty: boolean;
  canWrite: boolean;
  canDelete: boolean;
  copyButton: ReactNode;
  onBackToDetail: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onClose: () => void;
  children: ReactNode;
};

export function QuestionDetailDrawer({
  open,
  questionId,
  editing,
  dirty,
  canWrite,
  canDelete,
  copyButton,
  onBackToDetail,
  onEdit,
  onDelete,
  onClose,
  children,
}: QuestionDetailDrawerProps) {
  if (!open || questionId === null) return null;

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-slate-950/25 backdrop-blur-[1px] animate-fade-in"
      onClick={onClose}
    >
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={editing ? "编辑题目" : "题目详情"}
        className="question-detail-drawer h-full w-full max-w-[880px] overflow-y-auto overscroll-contain border-l border-slate-200/80 bg-white shadow-[-18px_0_52px_rgba(15,23,42,0.12)] animate-drop-in"
        onClick={(event) => event.stopPropagation()}
      >
        <QuestionDrawerHeader
          editing={editing}
          dirty={dirty}
          questionId={questionId}
          canWrite={canWrite}
          canDelete={canDelete}
          copyButton={copyButton}
          onBackToDetail={onBackToDetail}
          onEdit={onEdit}
          onDelete={onDelete}
          onClose={onClose}
        />
        {children}
      </aside>
    </div>
  );
}

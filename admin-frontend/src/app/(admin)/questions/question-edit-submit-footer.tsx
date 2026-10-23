"use client";

import { Save, X } from "lucide-react";
import { Button } from "@/components/ui/button";

type QuestionEditSubmitFooterProps = {
  cancelEditing: () => void;
  saveEditing: () => void;
  saving: boolean;
  dirty: boolean;
  unresolvedTableCount: number;
  emptyCodeCount: number;
};

export function QuestionEditSubmitFooter({
  cancelEditing,
  saveEditing,
  saving,
  dirty,
  unresolvedTableCount,
  emptyCodeCount,
}: QuestionEditSubmitFooterProps) {
  return (
    <div className="sticky bottom-0 z-10 -mx-7 -mb-24 mt-8 flex justify-end gap-2 border-t border-slate-200 bg-white/96 px-7 py-4 shadow-[0_-12px_30px_rgba(15,23,42,0.04)] backdrop-blur-xl">
      <Button
        variant="secondary"
        className="min-w-24 border-slate-200 bg-white shadow-none"
        onClick={cancelEditing}
      >
        <X className="h-4 w-4" />
        取消
      </Button>
      <Button
        variant="primary"
        className="min-w-28 shadow-none"
        onClick={saveEditing}
        disabled={!dirty || saving || unresolvedTableCount > 0 || emptyCodeCount > 0}
      >
        <Save className="h-4 w-4" />
        {saving ? "保存中..." : "保存修改"}
      </Button>
    </div>
  );
}

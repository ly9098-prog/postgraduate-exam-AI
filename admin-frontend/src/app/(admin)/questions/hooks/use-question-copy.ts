import { useCallback, useState } from "react";
import type { AdminQuestion } from "@/lib/api/types";
import { copyTextToClipboard } from "@/lib/clipboard";
import { buildQuestionCopyText } from "@/lib/question-copy";

export function useQuestionCopy(
  question: AdminQuestion | undefined,
  onMessage: (message: string) => void,
) {
  const [copyingQuestion, setCopyingQuestion] = useState(false);

  const copyQuestion = useCallback(async () => {
    if (!question || copyingQuestion) return;
    setCopyingQuestion(true);
    try {
      await copyTextToClipboard(buildQuestionCopyText(question));
      onMessage("题干和选项已复制。");
    } catch {
      onMessage("复制失败，请检查浏览器剪贴板权限后重试。");
    } finally {
      setCopyingQuestion(false);
    }
  }, [copyingQuestion, onMessage, question]);

  return { copyingQuestion, copyQuestion };
}

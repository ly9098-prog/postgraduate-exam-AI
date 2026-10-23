import { useEffect, useState } from "react";
import { fetchSubjectOptions } from "../question-api";

export type QuestionSubjectOption = {
  id: number;
  code: string;
  name: string;
};

export function useQuestionSubjectOptions() {
  const [subjectOptions, setSubjectOptions] = useState<QuestionSubjectOption[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchSubjectOptions()
      .then((options) => {
        if (!cancelled) setSubjectOptions(options);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return subjectOptions;
}

import { MathFormula } from "@/components/ui/math-formula";
import { parseMultiBlankChoiceAnswer } from "@/lib/question-options";
import { isMultiBlankChoice } from "../question-display-helpers";

export function QuestionAnswerDisplay({
  questionType,
  answer,
}: {
  questionType: string;
  answer: string | null | undefined;
}) {
  if (isMultiBlankChoice(questionType)) {
    const items = parseMultiBlankChoiceAnswer(answer);
    if (items.length > 0) {
      return (
        <div className="space-y-1">
          {items.map((item, index) => (
            <div
              key={`${item.blankId}-${index}`}
              className="grid grid-cols-[auto_1fr] items-center gap-x-3 leading-6"
            >
              <span>{item.blankId}</span>
              <span>
                <MathFormula text={item.optionKey} />
              </span>
            </div>
          ))}
        </div>
      );
    }
  }

  return <MathFormula text={answer || "—"} />;
}

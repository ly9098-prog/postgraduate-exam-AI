"use client";

import { QuestionContentRenderer } from "@/components/question-content-renderer";
import { MultiBlankQuestionOptions, QuestionOptions } from "@/components/question-options";
import { QuestionAnalysis } from "@/components/questions/question-analysis";
import {
  QuestionKnowledgePointsDisplay,
} from "@/components/questions/question-knowledge-points-editor";
import { resolveAssetUrl } from "@/lib/asset-url";
import {
  normalizeQuestionOptions,
  resolveQuestionBlankOptionGroups,
  resolveQuestionOptions,
} from "@/lib/question-options";
import type { AdminQuestion } from "@/lib/api/types";
import { QuestionAnswerDisplay } from "./components/question-answer-display";
import { DifficultyBadge } from "./components/question-difficulty-badge";
import { QuestionSecondaryInfo } from "./components/question-secondary-info";
import { TypeBadge } from "./components/question-type-badge";
import { textFromContent } from "./question-content-editing";
import {
  comparableAssetUrl,
  fallbackQuestionImageUrls,
  isMultiBlankChoice,
} from "./question-display-helpers";

type QuestionDetailViewProps = {
  question: AdminQuestion;
};

export function QuestionDetailView({ question }: QuestionDetailViewProps) {
  // Structured content renders image segments above. `image_url` is a legacy
  // mirror on many records, so only distinct fallback images are shown here.
  const fallbackUrls = fallbackQuestionImageUrls(
    question.content,
    question.image_url,
  );

  return (
    <div className="question-drawer-detail px-7 py-6 text-sm">
      <section className="border-b border-slate-200 pb-6">
        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <p className="text-sm font-semibold text-slate-950">题干</p>
          <div className="flex flex-wrap items-center gap-2">
            <TypeBadge type={question.question_type} />
            <DifficultyBadge difficulty={question.difficulty} />
          </div>
        </div>
        <div className="whitespace-pre-wrap text-[15px] leading-7 text-slate-700">
          <QuestionContentRenderer
            content={question.content}
            fallbackText={textFromContent(question.content)}
            showTableMetadata
            preserveCodeText
          />
        </div>
      </section>

      {fallbackUrls.length > 0 ? (
        <section className="border-b border-slate-200 py-6">
          <p className="mb-3 text-sm font-semibold text-slate-950">其他题目图片</p>
          <div className="grid gap-3">
            {fallbackUrls.map((raw, index) => {
              const src = resolveAssetUrl(raw) || raw;
              return (
                <a
                  key={`${comparableAssetUrl(raw)}-${index}`}
                  href={src}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group/img relative block overflow-hidden rounded-xl border border-[var(--color-border)]/50 bg-[var(--color-bg-input)]/30 focus:outline-none focus:ring-2 focus:ring-slate-300"
                  aria-label={`在新窗口查看题目图片 ${index + 1}`}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element -- legacy image mirror */}
                  <img
                    src={src}
                    alt={`题目图片 ${index + 1}`}
                    className="max-w-full cursor-zoom-in rounded-lg transition-transform duration-300 group-hover/img:scale-[1.02]"
                    style={{ maxHeight: "400px", width: "auto", objectFit: "contain" }}
                    onError={(event) => {
                      const target = event.currentTarget;
                      target.style.display = "none";
                      target.closest("a")?.classList.add("hidden");
                    }}
                  />
                  <div className="pointer-events-none absolute inset-0 rounded-xl ring-1 ring-inset ring-black/5" />
                </a>
              );
            })}
          </div>
        </section>
      ) : null}

      <section className="border-b border-slate-200 py-6">
        <p className="text-sm font-semibold text-slate-950">选项</p>
        <div className="mt-3">
          {isMultiBlankChoice(question.question_type) ? (
            <MultiBlankQuestionOptions
              groups={resolveQuestionBlankOptionGroups(question)}
            />
          ) : (
            <QuestionOptions
              options={normalizeQuestionOptions(resolveQuestionOptions(question))}
            />
          )}
        </div>
      </section>

      <section className="border-b border-slate-200 py-6">
        <p className="text-sm font-semibold text-slate-950">答案</p>
        <div className="mt-3 inline-flex min-h-10 items-center rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[15px] font-semibold leading-6 text-slate-800">
          <QuestionAnswerDisplay
            questionType={question.question_type}
            answer={question.answer}
          />
        </div>
      </section>

      <section className="border-b border-slate-200 py-6">
        <p className="text-sm font-semibold text-slate-950">解析</p>
        <div className="mt-3">
          <QuestionAnalysis value={question.analysis} />
        </div>
      </section>

      <section className="border-b border-slate-200 py-6">
        <div className="mb-4 flex items-center justify-between gap-3">
          <p className="text-sm font-semibold text-slate-950">知识点与难度</p>
          <DifficultyBadge difficulty={question.difficulty} />
        </div>
        <QuestionKnowledgePointsDisplay value={question.knowledge_points} />
      </section>
      <QuestionSecondaryInfo question={question} />
    </div>
  );
}

"use client";

import { ArrowLeftRight, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { QuestionVersionPicker, type QuestionVersionSelection } from "@/components/questions/question-version-picker";
import type { AdminQuestion, QuestionVersion, QuestionVersionDetail } from "@/lib/api/types";
import { QuestionVersionComparison } from "./components/question-version-comparison";
import type { QuestionVersionLabels } from "./question-version-labels";

export type QuestionVersionHistorySectionProps = {
  question: AdminQuestion;
  versions: {
    data?: {
      total?: number;
      items?: QuestionVersion[];
    };
    isFetching: boolean;
  };
  history: {
    open: boolean;
    toggle: () => void;
    base: QuestionVersionSelection | null;
    compare: QuestionVersionSelection | null;
    setBase: (value: QuestionVersionSelection) => void;
    setCompare: (value: QuestionVersionSelection) => void;
    swap: () => void;
  };
  details: {
    base?: QuestionVersionDetail | null;
    compare?: QuestionVersionDetail | null;
  };
  labels: QuestionVersionLabels;
};

export function QuestionVersionHistorySection(props: QuestionVersionHistorySectionProps) {
  const { versions, history, details, labels } = props;
  const baseData = history.base === "current"
    ? props.question
    : details.base;
  const compareData = history.compare === "current"
    ? props.question
    : details.compare;
  const hasNoVersions = (versions.data?.total ?? 0) === 0 && !versions.isFetching;

  return (
    <section className="py-6">
      <button
        type="button"
        onClick={history.toggle}
        className="flex w-full items-center justify-between gap-4 rounded-lg px-1 py-1 text-left transition hover:bg-slate-50"
        aria-expanded={history.open}
      >
        <div>
          <p className="text-sm font-semibold text-slate-950">版本历史</p>
          <p className="mt-1 text-[11px] leading-5 text-slate-400">
            可按时间、修改人或修改原因查找，并支持任意两个版本对比。
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="rounded-md bg-slate-100 px-2 py-1 text-[10px] font-medium text-slate-500">
            {versions.data?.total ?? 0} 个版本
          </span>
          <ChevronDown className={`h-4 w-4 text-slate-400 transition-transform duration-200 ${history.open ? "rotate-180" : ""}`} />
        </div>
      </button>

      {history.open ? (
        <div className="mt-4 animate-fade-in">
          {hasNoVersions ? (
            <div className="rounded-xl border border-slate-200 bg-slate-50/60 px-4 py-5 text-center text-xs text-slate-400">
              暂无历史版本
            </div>
          ) : (
            <>
              <div className="rounded-2xl border border-slate-200 bg-slate-50/50 p-3">
                <div className="grid items-end gap-3 md:grid-cols-[minmax(0,1fr)_44px_minmax(0,1fr)]">
                  <div className="min-w-0">
                    <p className="mb-2 px-0.5 text-[11px] font-medium text-slate-500">基准版本</p>
                    <QuestionVersionPicker
                      value={history.base}
                      onChange={history.setBase}
                      versions={versions.data?.items ?? []}
                      disabledValue={history.compare}
                      loading={versions.isFetching && !versions.data}
                    />
                  </div>
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    className="h-10 w-11 rounded-xl p-0 shadow-none"
                    disabled={history.compare === null}
                    title="交换对比版本"
                    aria-label="交换基准版本和对比版本"
                    onClick={history.swap}
                  >
                    <ArrowLeftRight className="h-4 w-4" />
                  </Button>
                  <div className="min-w-0">
                    <p className="mb-2 px-0.5 text-[11px] font-medium text-slate-500">对比版本</p>
                    <QuestionVersionPicker
                      value={history.compare}
                      onChange={history.setCompare}
                      versions={versions.data?.items ?? []}
                      disabledValue={history.base}
                      disabled={history.compare === null && !versions.isFetching && (versions.data?.total ?? 0) === 0}
                      loading={versions.isFetching && !versions.data}
                    />
                  </div>
                </div>
                <p className="mt-3 text-[10px] leading-5 text-slate-400">
                  可按日期精确筛选，也可按“今天 / 本周 / 上周 / 更早”浏览；支持搜索版本号、修改人或修改原因。切换版本时会保留当前对比区域，避免页面跳动。
                </p>
              </div>

              <QuestionVersionComparison
                enabled={history.compare !== null}
                questionType={props.question.question_type}
                left={baseData}
                right={compareData}
                leftTitle={labels.baseVersionLabel}
                rightTitle={labels.compareVersionLabel}
                loading={labels.versionComparisonLoading}
                pendingLabel={labels.pendingVersionLabel}
              />
            </>
          )}
        </div>
      ) : null}
    </section>
  );
}

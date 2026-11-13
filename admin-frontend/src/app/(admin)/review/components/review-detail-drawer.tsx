"use client";

import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  History,
  Loader2,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/drawer";
import { MathFormula } from "@/components/ui/math-formula";
import { StatusBadge } from "@/components/status-badge";
import { QuestionContentRenderer } from "@/components/question-content-renderer";
import {
  MultiBlankQuestionOptions,
  QuestionOptions,
} from "@/components/question-options";
import { QuestionAnalysis } from "@/components/questions/question-analysis";
import {
  normalizeQuestionOptions,
  parseMultiBlankChoiceAnswer,
  resolveQuestionBlankOptionGroups,
  resolveQuestionOptions,
} from "@/lib/question-options";
import { canonicalizeQuestionType, getQuestionTypeLabel } from "@/lib/question-types";
import { statusTone, textFromContent, unresolvedTableCount } from "@/lib/review-page-utils";
import { formatChinaDateTime } from "@/lib/time";
import type {
  AdminQuestionDetail,
  AdminQuestionImportSummary,
  QuestionVersion,
  QuestionVersionDetail,
} from "@/lib/api/types";
import {
  buildReviewDiff,
  reviewDifficultyLabel,
  reviewStatusLabel,
  type ReviewDiffRow,
} from "../review-queue-state";

type ReviewDetailDrawerProps = {
  open: boolean;
  questionId: number | null;
  question: AdminQuestionDetail | undefined;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  onClose: () => void;
  canReview: boolean;
  canRollback: boolean;
  versions: QuestionVersion[];
  versionsLoading: boolean;
  versionsError: boolean;
  baselineVersion: number | undefined;
  onSelectBaseline: (version: number) => void;
  baselineDetail: QuestionVersionDetail | undefined;
  baselineLoading: boolean;
  baselineError: boolean;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
  onRollback: (id: number, version: number) => void;
};

function isMultiBlankChoice(type: string): boolean {
  const code = canonicalizeQuestionType(type);
  return code === "multi_blank_choice" || code === "multi_blank_multiple_choice";
}

function AnswerValue({
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
              <MathFormula text={item.optionKey} />
            </div>
          ))}
        </div>
      );
    }
  }
  return <MathFormula text={answer || "—"} />;
}

function ContentSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-[var(--color-border)] bg-white p-4">
      <h3 className="mb-3 text-sm font-semibold text-[var(--ink)]">{title}</h3>
      {children}
    </section>
  );
}

function DuplicateAlert({ record }: { record: AdminQuestionImportSummary }) {
  return (
    <section className="rounded-2xl border border-[var(--color-warning)]/45 bg-[var(--color-warning-light)] p-4">
      <div className="flex flex-wrap items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-[var(--color-warning)]" aria-hidden="true" />
        <p className="text-sm font-semibold text-[var(--ink)]">疑似重复题目</p>
        <StatusBadge tone="warning">疑似重复</StatusBadge>
      </div>
      <p className="mt-2 text-xs leading-5 text-[var(--color-text-secondary)]">
        需要人工核对来源关系后再决定是否通过。
      </p>
      <div className="mt-3 grid gap-2 text-xs sm:grid-cols-3">
        <div className="rounded-xl border border-[var(--color-border)] bg-white/60 p-2.5">
          <p className="text-[11px] text-[var(--color-text-hint)]">题目 hash</p>
          <p className="mt-1 break-all font-mono text-[11px] text-[var(--ink)]">
            {record.question_hash || "—"}
          </p>
        </div>
        <div className="rounded-xl border border-[var(--color-border)] bg-white/60 p-2.5">
          <p className="text-[11px] text-[var(--color-text-hint)]">重复正式题</p>
          {record.duplicate_of_question_id ? (
            <Link
              href={`/questions?selected_id=${record.duplicate_of_question_id}`}
              className="mt-1 inline-flex items-center gap-1 font-mono text-[11px] font-semibold text-[var(--color-primary-dark)] underline decoration-[var(--color-primary)]/40 underline-offset-2 hover:decoration-[var(--color-primary)]"
            >
              #{record.duplicate_of_question_id}
              <ExternalLink className="h-3 w-3" aria-hidden="true" />
            </Link>
          ) : (
            <p className="mt-1 font-mono text-[11px] text-[var(--color-text-secondary)]">—</p>
          )}
        </div>
        <div className="rounded-xl border border-[var(--color-border)] bg-white/60 p-2.5">
          <p className="text-[11px] text-[var(--color-text-hint)]">重复导入项</p>
          <p className="mt-1 font-mono text-[11px] text-[var(--ink)]">
            {record.duplicate_of_import_id ? `#${record.duplicate_of_import_id}` : "—"}
          </p>
        </div>
      </div>
    </section>
  );
}

function DiffPanel({
  baselineVersion,
  rows,
}: {
  baselineVersion: number;
  rows: ReviewDiffRow[];
}) {
  const changedRows = rows.filter((row) => row.changed);
  const unchangedLabels = rows.filter((row) => !row.changed).map((row) => row.label);

  return (
    <div className="mt-4 rounded-2xl border border-[var(--color-border)] bg-[var(--porcelain)] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-[var(--ink)]">
          当前内容与 v{baselineVersion} 对比
        </p>
        <StatusBadge tone={changedRows.length > 0 ? "warning" : "success"}>
          {changedRows.length > 0 ? `${changedRows.length} 个字段变更` : "无变更"}
        </StatusBadge>
      </div>

      {changedRows.length > 0 ? (
        <div className="mt-3 space-y-3">
          {changedRows.map((row) => (
            <div
              key={row.key}
              className="rounded-xl border border-[var(--color-warning)]/35 bg-[var(--color-warning-light)]/45 p-3"
            >
              <p className="text-xs font-semibold text-[var(--ink)]">{row.label}</p>
              <div className="mt-2 grid gap-2 lg:grid-cols-2">
                <div className="rounded-lg border border-[var(--color-border)]/70 bg-white/55 px-3 py-2">
                  <p className="text-[11px] font-semibold text-[var(--color-text-hint)]">
                    变更前
                  </p>
                  <div className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words text-xs leading-5 text-[var(--color-text-secondary)]">
                    {row.previous || "—"}
                  </div>
                </div>
                <div className="rounded-lg border border-[var(--color-success)]/25 bg-white/85 px-3 py-2">
                  <p className="text-[11px] font-semibold text-[var(--color-success)]">
                    变更后
                  </p>
                  <div className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words text-xs leading-5 text-[var(--ink)]">
                    {row.current || "—"}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-xs text-[var(--color-text-secondary)]">
          当前内容与该历史版本一致。
        </p>
      )}

      {unchangedLabels.length > 0 ? (
        <p className="mt-3 text-[11px] text-[var(--color-text-hint)]">
          未变更：{unchangedLabels.join("、")}
        </p>
      ) : null}
    </div>
  );
}

function VersionHistory({
  versions,
  currentVersion,
  baselineVersion,
  canRollback,
  questionId,
  onSelectBaseline,
  onRollback,
}: {
  versions: QuestionVersion[];
  currentVersion: number | undefined;
  baselineVersion: number | undefined;
  canRollback: boolean;
  questionId: number;
  onSelectBaseline: (version: number) => void;
  onRollback: (id: number, version: number) => void;
}) {
  if (versions.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-[var(--color-border)] bg-white/50 px-3 py-4 text-center text-xs text-[var(--color-text-hint)]">
        该题暂无历史版本记录。
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {versions.map((version) => {
        const current = version.version === currentVersion;
        const selected = version.version === baselineVersion;
        return (
          <div
            key={version.version}
            className={
              selected
                ? "flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--color-primary)] bg-[var(--color-primary-light)]/40 px-3 py-2"
                : "flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--porcelain)] px-3 py-2"
            }
          >
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs font-semibold text-[var(--ink)]">
                  v{version.version}
                </span>
                {current ? <StatusBadge tone="primary">当前</StatusBadge> : null}
                {selected ? (
                  <span className="text-[10px] font-semibold text-[var(--color-primary-dark)]">
                    对比基线
                  </span>
                ) : null}
              </div>
              <p className="mt-1 truncate text-[11px] text-[var(--color-text-hint)]">
                {formatChinaDateTime(version.created_at)} ·{" "}
                {version.edited_by_name ||
                  (version.edited_by != null
                    ? `编辑者 #${version.edited_by}`
                    : "系统")}{" "}
                · {version.edit_reason || "无编辑原因"}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {!current ? (
                <Button
                  variant={selected ? "secondary" : "ghost"}
                  size="sm"
                  onClick={() => onSelectBaseline(version.version)}
                >
                  对比
                </Button>
              ) : null}
              {canRollback && !current ? (
                <Button
                  variant="dangerOutline"
                  size="sm"
                  onClick={() => onRollback(questionId, version.version)}
                >
                  回滚
                </Button>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function ReviewDetailDrawer({
  open,
  questionId,
  question,
  isLoading,
  isError,
  onRetry,
  onClose,
  canReview,
  canRollback,
  versions,
  versionsLoading,
  versionsError,
  baselineVersion,
  onSelectBaseline,
  baselineDetail,
  baselineLoading,
  baselineError,
  onApprove,
  onReject,
  onRollback,
}: ReviewDetailDrawerProps) {
  const tableCount = unresolvedTableCount(question?.content);
  const tableBlocked = tableCount > 0;
  const currentVersion = versions[0]?.version;
  const diffRows =
    question && baselineDetail ? buildReviewDiff(question, baselineDetail) : [];
  const options = question
    ? normalizeQuestionOptions(resolveQuestionOptions(question))
    : [];
  const blankGroups = question ? resolveQuestionBlankOptionGroups(question) : [];

  return (
    <Drawer
      open={open}
      onClose={onClose}
      className="w-full max-w-3xl"
      ariaLabel={questionId ? `题目 #${questionId} 重审详情` : "题目重审详情"}
      title={
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="font-display text-xl font-bold text-[var(--ink)]">
            题目 #{questionId ?? "—"}
          </h2>
          {question ? (
            <StatusBadge tone={statusTone(question.review_status)}>
              {reviewStatusLabel(question.review_status)}
            </StatusBadge>
          ) : null}
          <span className="text-xs text-[var(--color-text-hint)]">重审详情</span>
        </div>
      }
    >
      {isLoading && !question ? (
        <div className="space-y-3" aria-busy="true">
          <div className="h-11 animate-pulse rounded-xl bg-[var(--color-bg-input)]/75" />
          <div className="h-28 animate-pulse rounded-2xl bg-[var(--color-bg-input)]/60" />
          <div className="h-44 animate-pulse rounded-2xl bg-[var(--color-bg-input)]/50" />
        </div>
      ) : null}

      {isError && !question ? (
        <div className="flex flex-col items-center gap-3 py-12 text-center">
          <AlertTriangle className="h-9 w-9 text-red-400" aria-hidden="true" />
          <p className="text-sm font-semibold text-red-700">题目详情加载失败</p>
          <Button variant="secondary" size="sm" onClick={onRetry}>
            重新加载
          </Button>
        </div>
      ) : null}

      {question ? (
        <div className="space-y-4">
          <div className="sticky top-0 z-10 -mx-6 -mt-5 mb-4 flex flex-wrap items-center gap-2 border-b border-[var(--color-border)] bg-white/94 px-6 py-3 backdrop-blur">
            {canReview ? (
              <>
                <Button
                  variant="success"
                  size="sm"
                  disabled={tableBlocked}
                  title={
                    tableBlocked
                      ? `仍有 ${tableCount} 个结构化表格待核验，请先在题库编辑页完成核验`
                      : undefined
                  }
                  onClick={() => onApprove(question.id)}
                >
                  <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                  {question.review_status === "rejected" ? "恢复通过" : "通过"}
                </Button>
                {question.review_status === "re_pending" ? (
                  <Button
                    variant="dangerOutline"
                    size="sm"
                    onClick={() => onReject(question.id)}
                  >
                    <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
                    拒绝
                  </Button>
                ) : null}
              </>
            ) : null}
            <Link
              href={`/questions?selected_id=${question.id}`}
              className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-xl px-3 text-xs font-semibold text-[var(--color-text-secondary)] transition hover:bg-[var(--color-primary-light)] hover:text-[var(--color-primary-dark)]"
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
              在题库中打开
            </Link>
          </div>

          {tableBlocked ? (
            <div className="rounded-2xl border border-[var(--color-warning)]/45 bg-[var(--color-warning-light)] p-4 text-sm text-[var(--ink)]">
              当前题目仍有 {tableCount} 个结构化表格需要人工核验，暂不能审核通过。
            </div>
          ) : null}

          {question.import_record?.duplicate_status === "possible_duplicate" ? (
            <DuplicateAlert record={question.import_record} />
          ) : null}

          <ContentSection title="题干">
            <div className="whitespace-pre-wrap text-base leading-8 text-[var(--ink)]">
              <QuestionContentRenderer
                content={question.content}
                fallbackText={textFromContent(question.content)}
                showTableMetadata
                preserveCodeText
              />
            </div>
          </ContentSection>

          <ContentSection title="选项">
            {isMultiBlankChoice(question.question_type) ? (
              <MultiBlankQuestionOptions groups={blankGroups} />
            ) : (
              <QuestionOptions options={options} />
            )}
          </ContentSection>

          <ContentSection title="答案">
            <div className="inline-flex min-h-9 items-center rounded-md bg-[var(--color-bg-input)] px-2.5 py-1.5 text-sm font-semibold leading-6 text-[var(--ink)]">
              <AnswerValue questionType={question.question_type} answer={question.answer} />
            </div>
          </ContentSection>

          <ContentSection title="解析">
            <QuestionAnalysis value={question.analysis} compact />
          </ContentSection>

          <ContentSection title="题目信息">
            <div className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-3">
              {[
                ["科目", question.subject_name || question.subject_code || "未分类"],
                ["题型", getQuestionTypeLabel(question.question_type)],
                ["难度", reviewDifficultyLabel(question.difficulty)],
                ["启用状态", question.is_active ? "启用" : "停用"],
                ["最近更新", formatChinaDateTime(question.updated_at)],
                ["导入批次", question.import_batch_id || "—"],
              ].map(([label, value]) => (
                <div
                  key={label}
                  className="rounded-xl border border-[var(--color-border)] bg-[var(--porcelain)] px-3 py-2"
                >
                  <p className="text-[11px] text-[var(--color-text-hint)]">{label}</p>
                  <p className="mt-1 break-words font-medium text-[var(--color-text-secondary)]">
                    {value}
                  </p>
                </div>
              ))}
            </div>
            {question.import_record ? (
              <p className="mt-2 break-all text-[11px] text-[var(--color-text-hint)]">
                重复检测：
                {question.import_record.duplicate_status === "possible_duplicate"
                  ? "疑似重复"
                  : "正常"}
                {question.import_record.question_hash
                  ? ` · hash ${question.import_record.question_hash.slice(0, 20)}${question.import_record.question_hash.length > 20 ? "…" : ""}`
                  : ""}
              </p>
            ) : null}
          </ContentSection>

          <section className="rounded-2xl border border-[var(--color-border)] bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="inline-flex items-center gap-2 text-sm font-semibold text-[var(--ink)]">
                  <History className="h-4 w-4 text-[var(--color-primary)]" aria-hidden="true" />
                  版本历史与对比
                </h3>
                <p className="mt-1 text-[11px] text-[var(--color-text-hint)]">
                  选择历史版本作为对比基线；回滚会生成新版本并恢复审核通过。
                </p>
              </div>
              {versionsLoading ? (
                <Loader2 className="h-4 w-4 animate-spin text-[var(--color-text-hint)]" aria-hidden="true" />
              ) : null}
            </div>

            <div className="mt-3">
              {versionsError ? (
                <p className="rounded-xl border border-red-200 bg-red-50/60 px-3 py-2 text-xs text-red-700">
                  版本历史加载失败，可稍后重试。
                </p>
              ) : (
                <VersionHistory
                  versions={versions}
                  currentVersion={currentVersion}
                  baselineVersion={baselineVersion}
                  canRollback={canRollback}
                  questionId={question.id}
                  onSelectBaseline={onSelectBaseline}
                  onRollback={onRollback}
                />
              )}
            </div>

            {baselineLoading ? (
              <div className="mt-4 h-24 animate-pulse rounded-2xl bg-[var(--color-bg-input)]/60" />
            ) : null}

            {baselineError ? (
              <p className="mt-4 rounded-xl border border-red-200 bg-red-50/60 px-3 py-2 text-xs text-red-700">
                对比版本加载失败，无法展示差异。
              </p>
            ) : null}

            {!baselineLoading && !baselineError && baselineDetail && baselineVersion ? (
              <DiffPanel baselineVersion={baselineVersion} rows={diffRows} />
            ) : null}
          </section>
        </div>
      ) : null}
    </Drawer>
  );
}

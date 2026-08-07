"use client";

import { useQuery } from "@tanstack/react-query";
import { FileSearch, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { DataTable } from "@/components/data-table/data-table";
import { Drawer } from "@/components/ui/drawer";
import { apiRequest } from "@/lib/api/client";
import type {
  HealthReportResponse,
  KnowledgeQualityReport,
  RecommendationQualityReport,
} from "@/lib/api/types";

const QUALITY_SUMMARY_LABELS: Record<string, string> = {
  total_logs_30d: "30天推荐日志",
  recent_logs_7d: "近7天日志",
  hot_question_count: "热门题目数",
  fallback_ratio: "兜底比例",
  avg_similarity: "平均相似度",
};

const KNOWLEDGE_SUMMARY_LABELS: Record<string, string> = {
  total_knowledge_points: "知识点总数",
  total_edges: "知识边总数",
  isolated_count: "孤立知识点",
  no_question_count: "无题知识点",
  low_confidence_edge_count: "低置信度边",
  cycle_count: "前驱循环",
};

const RATIO_KEYS = new Set(["fallback_ratio", "avg_similarity"]);

function summaryItems(summary: Record<string, unknown> | undefined, labels: Record<string, string>): [string, string][] {
  return Object.entries(summary ?? {}).map(([k, v]) => {
    let text = v == null ? "—" : String(v);
    if (RATIO_KEYS.has(k) && typeof v === "number" && !Number.isNaN(v)) {
      text = `${(v * 100).toFixed(1)}%`;
    }
    return [labels[k] ?? k, text];
  });
}

function percent(v: number | undefined | null): string {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return `${(Number(v) * 100).toFixed(1)}%`;
}

function KVCard({ title, items }: { title: string; items: [string, string][] }) {
  return (
    <Card>
      <CardHeader className="text-sm font-bold text-[var(--color-text-primary)]">{title}</CardHeader>
      <CardContent className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-3">
        {items.map(([k, v]) => (
          <div key={k} className="flex flex-col">
            <span className="text-xs text-[var(--color-text-secondary)]">{k}</span>
            <span className="text-lg font-bold text-[var(--color-text-primary)]">{v}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function Warnings({ warnings }: { warnings: string[] }) {
  if (!warnings || warnings.length === 0) return null;
  return (
    <div className="rounded-2xl border border-[var(--color-danger)]/20 bg-[#fdf3f3] p-4">
      <div className="mb-2 text-xs font-bold text-[var(--color-danger)]">告警（{warnings.length}）</div>
      <ul className="list-disc pl-5 text-sm text-[var(--color-text-secondary)]">
        {warnings.map((w, i) => (
          <li key={i}>{w}</li>
        ))}
      </ul>
    </div>
  );
}

function DictRows({ rows, label }: { rows: Record<string, unknown>[] | undefined; label: string }) {
  if (!rows || rows.length === 0) return null;
  const columns = Object.keys(rows[0] ?? {}).map((key) => ({ id: key, header: key, accessorKey: key }));
  return (
    <div className="mt-4">
      <div className="mb-2 text-xs font-bold text-[var(--color-text-secondary)]">{label}</div>
      <DataTable<Record<string, unknown>> data={rows} columns={columns} emptyText="无数据" />
    </div>
  );
}

export default function RecommendationReportsPage() {
  const health = useQuery({
    queryKey: ["recommendation", "reports", "health"],
    queryFn: () => apiRequest<HealthReportResponse>("/recommendation/health-report"),
  });
  const quality = useQuery({
    queryKey: ["recommendation", "reports", "quality"],
    queryFn: () => apiRequest<RecommendationQualityReport>("/recommendation/quality-report"),
  });
  const knowledge = useQuery({
    queryKey: ["recommendation", "reports", "knowledge-quality"],
    queryFn: () => apiRequest<KnowledgeQualityReport>("/recommendation/knowledge-quality-report"),
  });

  const [viewQuestion, setViewQuestion] = useState<Record<string, unknown> | null>(null);

  const h = health.data;

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">推荐报表</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">推荐健康度 / 推荐质量 / 知识图谱质量</p>
        </div>
        {(health.isFetching || quality.isFetching || knowledge.isFetching) && (
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-hint)]">
            <RefreshCw className="h-3.5 w-3.5 animate-spin" /> 加载中…
          </div>
        )}
      </div>

      {h && (
        <>
          <KVCard
            title="健康度"
            items={[
              ["推荐日志总数", String(h.total_recommendation_logs)],
              ["兜底率", percent(h.fallback_rate)],
              ["空推荐数", String(h.empty_recommendation_count)],
              ["低相似率", percent(h.low_similarity_rate)],
              ["策略解析失败", String(h.strategy_resolve_failed_count)],
              ["实验分配用户", String(h.experiment_assignment_count)],
              ["向量召回失败", String(h.vector_recall_failure_count)],
              ["知识路径为空", String(h.knowledge_path_empty_count)],
            ]}
          />
          <Warnings warnings={h.warnings} />
          <DictRows rows={h.top_fallback_scenes} label="兜底场景 Top" />
          <DictRows rows={h.top_error_strategies} label="出错策略 Top" />
        </>
      )}

      {quality.data && (
        <>
          <KVCard title="推荐质量" items={summaryItems(quality.data.summary, QUALITY_SUMMARY_LABELS)} />
          <Warnings warnings={quality.data.warnings} />
          {quality.data.hot_questions && quality.data.hot_questions.length > 0 && (
            <div className="mt-4">
              <div className="mb-2 text-xs font-bold text-[var(--color-text-secondary)]">热门题目</div>
              <DataTable<Record<string, unknown>>
                data={quality.data.hot_questions}
                emptyText="无数据"
                columns={[
                  { id: "question_id", header: "题目ID", accessorKey: "question_id" },
                  {
                    id: "question_title",
                    header: "题目名称",
                    accessorKey: "question_title",
                    cell: ({ row }) => {
                      const title = String(row.original.question_title ?? "");
                      const fallback = `#${row.original.question_id ?? ""}`;
                      return (
                        <button
                          type="button"
                          onClick={() => setViewQuestion(row.original)}
                          className="block max-w-[320px] truncate text-left text-sm text-[var(--color-primary-dark)] underline-offset-2 hover:underline"
                          title={title || fallback}
                        >
                          {title || fallback}
                        </button>
                      );
                    },
                  },
                  { id: "recommend_count", header: "推荐次数", accessorKey: "recommend_count" },
                ]}
              />
            </div>
          )}
          <DictRows rows={quality.data.high_fallback_scenes} label="高兜底场景" />
          <DictRows rows={quality.data.low_similarity_samples} label="低相似样本" />
        </>
      )}

      {knowledge.data && (
        <>
          <KVCard
            title="知识图谱质量"
            items={summaryItems(knowledge.data.summary, KNOWLEDGE_SUMMARY_LABELS)}
          />
          <Warnings warnings={knowledge.data.warnings} />
          <DictRows rows={knowledge.data.isolated_knowledge_points} label="孤立知识点" />
          <DictRows rows={knowledge.data.low_question_count_points} label="低题量知识点" />
        </>
      )}

      {!health.isLoading && !health.data && (
        <Card>
          <CardContent className="py-10 text-center text-sm text-[var(--color-text-hint)]">
            <FileSearch className="mx-auto mb-2 h-6 w-6" />
            暂无健康报告数据（可能推荐日志为空）
          </CardContent>
        </Card>
      )}

      <Drawer
        open={viewQuestion != null}
        onClose={() => setViewQuestion(null)}
        title="题目详情"
        ariaLabel="题目详情"
      >
        <div className="text-xs text-[var(--color-text-hint)]">
          题目ID：{String(viewQuestion?.question_id ?? "")}
        </div>
        <div className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-[var(--color-text-primary)]">
          {String(viewQuestion?.question_title ?? "暂无题干")}
        </div>
      </Drawer>
    </div>
  );
}

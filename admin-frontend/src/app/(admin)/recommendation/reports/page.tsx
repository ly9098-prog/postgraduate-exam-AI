"use client";

import { useQuery } from "@tanstack/react-query";
import { FileSearch, RefreshCw } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { DataTable } from "@/components/data-table/data-table";
import { apiRequest } from "@/lib/api/client";
import type {
  HealthReportResponse,
  KnowledgeQualityReport,
  RecommendationQualityReport,
} from "@/lib/api/types";

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
          <KVCard title="推荐质量" items={Object.entries(quality.data.summary ?? {}).map(([k, v]) => [k, String(v)])} />
          <Warnings warnings={quality.data.warnings} />
          <DictRows rows={quality.data.hot_questions} label="热门题目" />
          <DictRows rows={quality.data.high_fallback_scenes} label="高兜底场景" />
          <DictRows rows={quality.data.low_similarity_samples} label="低相似样本" />
        </>
      )}

      {knowledge.data && (
        <>
          <KVCard
            title="知识图谱质量"
            items={Object.entries(knowledge.data.summary ?? {}).map(([k, v]) => [k, String(v)])}
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
    </div>
  );
}

"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, BookOpen, Check, ChevronDown, GitMerge, Layers3, Link2, Plus, RefreshCw, Save, Search, ShieldCheck, Trash2, X } from "lucide-react";

import {
  EmptyState,
  FieldLabel,
  ManagementNotice,
  ManagementPage,
  ManagementPageHeader,
  ManagementPanel,
  ManagementProgress,
  ManagementSkeletonRows,
  MetricCard,
  MetricStrip,
  StatusBadge,
} from "@/components/admin/management-ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiRequest } from "@/lib/api/client";
import type {
  SyllabusCatalogResponse,
  SyllabusCoverageResponse,
  SyllabusMappingItem,
  SyllabusVersionDetail,
  SyllabusVersionSummary,
} from "@/lib/api/types";
import { useAuthStore } from "@/lib/auth/auth-store";
import { hasPermission } from "@/lib/permissions/permissions";
import {
  filterCatalogItems,
  groupCatalogBySubject,
  extractIncludedIds,
  isMembershipDirty,
} from "@/lib/syllabus-utils";

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  active: "当前生效",
  archived: "已归档",
};

const RELATION_LABEL: Record<string, string> = {
  unchanged: "保持",
  renamed: "重命名",
  added: "新增",
  removed: "移除",
  merged: "合并",
  split: "拆分",
  replaced: "替换",
};

function statusTone(status: string) {
  if (status === "active") return "success" as const;
  if (status === "draft") return "warning" as const;
  return "neutral" as const;
}

const selectClass = "h-11 w-full rounded-xl border border-[var(--color-border)] bg-white px-3 text-sm text-[var(--ink)] outline-none transition focus:border-[var(--color-primary)] focus:ring-4 focus:ring-[rgba(74,111,138,0.12)] disabled:cursor-not-allowed disabled:opacity-50";

export default function SyllabusPage() {
  const queryClient = useQueryClient();
  const permissions = useAuthStore((state) => state.permissions);
  const canWrite = hasPermission(permissions, "knowledge:write");
  const [selectedVersionId, setSelectedVersionId] = useState<number | null>(null);
  const [selectedKnowledgePointIds, setSelectedKnowledgePointIds] = useState<Set<number>>(new Set());
  const [createForm, setCreateForm] = useState({
    code: "",
    name: "",
    effective_year: new Date().getFullYear() + 1,
    description: "",
  });
  const [mappingSourceVersionId, setMappingSourceVersionId] = useState<number | null>(null);
  const [mappingForm, setMappingForm] = useState({
    from_syllabus_knowledge_point_id: 0,
    to_syllabus_knowledge_point_id: 0,
    relation_type: "replaced" as "merged" | "split" | "replaced",
    note: "",
  });
  const [catalogKeyword, setCatalogKeyword] = useState("");
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [collapsedSubjects, setCollapsedSubjects] = useState<Set<string>>(new Set());

  const versionsQuery = useQuery({
    queryKey: ["syllabus", "versions"],
    queryFn: () => apiRequest<SyllabusVersionSummary[]>("/knowledge/syllabus/versions"),
  });

  useEffect(() => {
    if (selectedVersionId || !versionsQuery.data?.length) return;
    const preferred = versionsQuery.data.find((item) => item.status === "draft")
      ?? versionsQuery.data.find((item) => item.status === "active")
      ?? versionsQuery.data[0];
    setSelectedVersionId(preferred.id);
  }, [selectedVersionId, versionsQuery.data]);

  const detailQuery = useQuery({
    queryKey: ["syllabus", "detail", selectedVersionId],
    enabled: Boolean(selectedVersionId),
    queryFn: () => apiRequest<SyllabusVersionDetail>(`/knowledge/syllabus/versions/${selectedVersionId}`),
  });

  const catalogQuery = useQuery({
    queryKey: ["syllabus", "catalog", selectedVersionId],
    enabled: Boolean(selectedVersionId),
    queryFn: () => apiRequest<SyllabusCatalogResponse>(`/knowledge/syllabus/versions/${selectedVersionId}/catalog`),
  });

  const coverageQuery = useQuery({
    queryKey: ["syllabus", "coverage", selectedVersionId],
    enabled: Boolean(selectedVersionId),
    queryFn: () => apiRequest<SyllabusCoverageResponse>(`/knowledge/syllabus/versions/${selectedVersionId}/coverage`),
  });

  const mappingsQuery = useQuery({
    queryKey: ["syllabus", "mappings", selectedVersionId],
    enabled: Boolean(selectedVersionId),
    queryFn: () => apiRequest<SyllabusMappingItem[]>(`/knowledge/syllabus/versions/${selectedVersionId}/mappings`),
  });

  const sourceDetailQuery = useQuery({
    queryKey: ["syllabus", "mapping-source", mappingSourceVersionId],
    enabled: Boolean(mappingSourceVersionId),
    queryFn: () => apiRequest<SyllabusVersionDetail>(`/knowledge/syllabus/versions/${mappingSourceVersionId}`),
  });

  useEffect(() => {
    if (!catalogQuery.data) return;
    setSelectedKnowledgePointIds(new Set(
      catalogQuery.data.items.filter((item) => item.included).map((item) => item.knowledge_point_id),
    ));
  }, [catalogQuery.data]);

  useEffect(() => {
    if (!catalogKeyword.trim()) return;
    setCollapsedSubjects(new Set());
  }, [catalogKeyword]);

  useEffect(() => {
    if (!detailQuery.data || detailQuery.data.status !== "draft") return;
    const source = (versionsQuery.data ?? []).find((item) => item.status === "active" && item.id !== detailQuery.data?.id)
      ?? (versionsQuery.data ?? []).find((item) => item.status === "archived" && item.id !== detailQuery.data?.id)
      ?? null;
    setMappingSourceVersionId(source?.id ?? null);
  }, [detailQuery.data, versionsQuery.data]);

  useEffect(() => {
    const fromId = sourceDetailQuery.data?.knowledge_points?.[0]?.id ?? 0;
    const toId = detailQuery.data?.knowledge_points?.[0]?.id ?? 0;
    setMappingForm((value) => ({
      ...value,
      from_syllabus_knowledge_point_id: fromId,
      to_syllabus_knowledge_point_id: toId,
    }));
  }, [sourceDetailQuery.data, detailQuery.data]);

  async function refreshAll() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["syllabus", "versions"] }),
      queryClient.invalidateQueries({ queryKey: ["syllabus", "detail"] }),
      queryClient.invalidateQueries({ queryKey: ["syllabus", "catalog"] }),
      queryClient.invalidateQueries({ queryKey: ["syllabus", "coverage"] }),
      queryClient.invalidateQueries({ queryKey: ["syllabus", "mappings"] }),
      queryClient.invalidateQueries({ queryKey: ["syllabus", "mapping-source"] }),
    ]);
  }

  const createMutation = useMutation({
    mutationFn: () => apiRequest<SyllabusVersionDetail>("/knowledge/syllabus/versions", {
      method: "POST",
      body: JSON.stringify({
        ...createForm,
        code: createForm.code.trim(),
        name: createForm.name.trim(),
        description: createForm.description.trim() || null,
      }),
    }),
    onSuccess: async (data) => {
      setSelectedVersionId(data.id);
      setCreateForm((value) => ({ ...value, code: "", name: "", description: "" }));
      setShowCreateForm(false);
      await refreshAll();
    },
  });

  const membershipMutation = useMutation({
    mutationFn: () => apiRequest<SyllabusVersionDetail>(`/knowledge/syllabus/versions/${selectedVersionId}/knowledge-points`, {
      method: "PUT",
      body: JSON.stringify({ knowledge_point_ids: [...selectedKnowledgePointIds].sort((a, b) => a - b) }),
    }),
    onSuccess: refreshAll,
  });

  const activateMutation = useMutation({
    mutationFn: () => apiRequest<SyllabusVersionDetail>(`/knowledge/syllabus/versions/${selectedVersionId}/activate`, { method: "POST" }),
    onSuccess: refreshAll,
  });

  const archiveMutation = useMutation({
    mutationFn: () => apiRequest<SyllabusVersionDetail>(`/knowledge/syllabus/versions/${selectedVersionId}/archive`, { method: "POST" }),
    onSuccess: refreshAll,
  });

  const mappingMutation = useMutation({
    mutationFn: () => apiRequest<SyllabusMappingItem>("/knowledge/syllabus/mappings", {
      method: "POST",
      body: JSON.stringify({
        ...mappingForm,
        note: mappingForm.note.trim() || null,
      }),
    }),
    onSuccess: async () => {
      setMappingForm((value) => ({ ...value, note: "" }));
      await refreshAll();
    },
  });

  const deleteMappingMutation = useMutation({
    mutationFn: (mappingId: number) => apiRequest<{ success: boolean; id: number }>(`/knowledge/syllabus/mappings/${mappingId}`, { method: "DELETE" }),
    onSuccess: refreshAll,
  });

  const detail = detailQuery.data;
  const catalog = catalogQuery.data?.items ?? [];
  const normalizedCatalogKeyword = catalogKeyword.trim().toLowerCase();
  const visibleCatalog = useMemo(() => {
    return filterCatalogItems(catalog, normalizedCatalogKeyword);
  }, [catalog, normalizedCatalogKeyword]);
  const groupedCatalog = useMemo(() => {
    return groupCatalogBySubject(visibleCatalog);
  }, [visibleCatalog]);
  const activeVersion = versionsQuery.data?.find((item) => item.status === "active");
  const coveragePct = Math.round((coverageQuery.data?.coverage_ratio ?? 0) * 100);
  const saving = membershipMutation.isPending || activateMutation.isPending || archiveMutation.isPending || mappingMutation.isPending || deleteMappingMutation.isPending;
  const includedIds = useMemo(() => extractIncludedIds(catalog), [catalog]);
  const membershipDirty = isMembershipDirty(selectedKnowledgePointIds, includedIds);

  function toggleKnowledgePoint(id: number) {
    if (!detail || detail.status !== "draft" || !canWrite) return;
    setSelectedKnowledgePointIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function toggleSubjectGroup(subjectKey: string) {
    setCollapsedSubjects((current) => {
      const next = new Set(current);
      if (next.has(subjectKey)) next.delete(subjectKey); else next.add(subjectKey);
      return next;
    });
  }

  function expandAllSubjects() {
    setCollapsedSubjects(new Set());
  }

  function collapseAllSubjects() {
    setCollapsedSubjects(new Set(groupedCatalog.map(([subjectKey]) => subjectKey)));
  }

  const error = createMutation.isError || membershipMutation.isError || activateMutation.isError || archiveMutation.isError || mappingMutation.isError || deleteMappingMutation.isError;

  return (
    <ManagementPage className="space-y-6">
      <ManagementPageHeader
        icon={<BookOpen className="h-5 w-5" />}
        title="考纲版本"
        description="管理考纲版本、知识点范围与跨版本语义映射。科目保持稳定，版本负责冻结当期知识点集合及名称描述。"
        meta={
          <>
            <StatusBadge tone={activeVersion ? "success" : "warning"}>{activeVersion ? `当前版本：${activeVersion.name}` : "尚未设置当前版本"}</StatusBadge>
            <span>当前版本只读，草稿版本可调整成员</span>
          </>
        }
        actions={
          <Button variant="secondary" onClick={() => refreshAll()} disabled={versionsQuery.isFetching}>
            <RefreshCw className={`h-4 w-4 ${versionsQuery.isFetching ? "animate-spin" : ""}`} />
            刷新
          </Button>
        }
      />

      <MetricStrip className="sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard icon={<ShieldCheck className="h-4 w-4" />} label="当前生效版本" value={activeVersion?.effective_year ?? "未设置"} hint={activeVersion?.name ?? "需要激活一个草稿版本"} tone={activeVersion ? "success" : "warning"} />
        <MetricCard icon={<BookOpen className="h-4 w-4" />} label="所选知识点" value={detail?.knowledge_point_count ?? 0} hint={detail?.name ?? "请选择版本"} />
        <MetricCard icon={<Check className="h-4 w-4" />} label="基础题库覆盖" value={`${coveragePct}%`} hint={`${coverageQuery.data?.covered_knowledge_points ?? 0} / ${coverageQuery.data?.total_knowledge_points ?? 0} 个知识点有题`} tone={coveragePct >= 90 ? "success" : coveragePct > 0 ? "warning" : "default"} progress={coveragePct} />
        <MetricCard icon={<GitMerge className="h-4 w-4" />} label="跨版本映射" value={mappingsQuery.data?.length ?? 0} hint="包含自动映射与手工补充关系" tone="accent" />
      </MetricStrip>

      <div className="grid gap-5 xl:grid-cols-[328px_minmax(0,1fr)] xl:items-start">
        <div className="space-y-5 xl:sticky xl:top-5">
          <ManagementPanel variant="quiet" title="版本索引" description={`${versionsQuery.data?.length ?? 0} 个版本 · 选择后在右侧编辑范围`} contentClassName="p-2.5">
            <div className="space-y-1.5">
              {(versionsQuery.data ?? []).map((item) => {
                const selected = selectedVersionId === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => setSelectedVersionId(item.id)}
                    className={`group relative flex w-full items-center gap-3 rounded-[13px] border px-3 py-2.5 text-left transition-[background-color,border-color,transform,box-shadow] duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] active:scale-[0.99] motion-reduce:transition-none ${selected ? "border-[rgba(74,111,138,0.32)] bg-[var(--mgmt-steel)] shadow-[0_8px_20px_rgba(45,80,104,0.07)]" : "border-transparent hover:border-[var(--mgmt-line)] hover:bg-white"}`}
                    aria-pressed={selected}
                  >
                    <span className={`grid h-12 w-12 shrink-0 place-items-center rounded-[11px] border text-[13px] font-bold tabular-nums transition-colors ${selected ? "border-[rgba(74,111,138,0.26)] bg-white text-[var(--color-primary-dark)]" : "border-[var(--mgmt-line)] bg-[rgba(237,243,246,0.52)] text-[var(--color-text-secondary)] group-hover:bg-[var(--mgmt-steel)]"}`}>{item.effective_year}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-start justify-between gap-2">
                        <span className="min-w-0 truncate text-sm font-semibold text-[var(--ink)]">{item.name}</span>
                        <StatusBadge tone={statusTone(item.status)}>{STATUS_LABEL[item.status]}</StatusBadge>
                      </span>
                      <span className="mt-1.5 flex items-center gap-2 text-[10px] text-[var(--color-text-tertiary)]">
                        <span className="min-w-0 truncate">{item.code}</span>
                        <span aria-hidden="true">·</span>
                        <span className="shrink-0 tabular-nums">{item.knowledge_point_count} KP</span>
                      </span>
                    </span>
                    {selected ? <span aria-hidden="true" className="absolute inset-y-3 left-0 w-[2px] rounded-r-full bg-[var(--color-primary)]" /> : null}
                  </button>
                );
              })}
              {versionsQuery.isLoading ? <ManagementSkeletonRows rows={4} /> : null}
              {!versionsQuery.isLoading && !versionsQuery.data?.length ? <EmptyState>暂无考纲版本。</EmptyState> : null}
            </div>
          </ManagementPanel>

          {canWrite ? (
            <ManagementPanel
              variant="quiet"
              title="新建考纲版本"
              description="从当前版本继承范围后生成草稿，再完成知识点调整与映射。"
              icon={<Plus className="h-4 w-4" />}
              actions={
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setShowCreateForm((value) => !value)}
                  aria-expanded={showCreateForm}
                >
                  {showCreateForm ? "收起" : "展开"}
                  <ChevronDown className={`h-4 w-4 transition-transform duration-200 motion-reduce:transition-none ${showCreateForm ? "rotate-180" : ""}`} />
                </Button>
              }
              contentClassName={showCreateForm ? "p-4" : "p-0"}
            >
              <div className={`grid transition-[grid-template-rows,opacity] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none ${showCreateForm ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`}>
                <div className="overflow-hidden">
                  <div className="space-y-3">
                    <label>
                      <FieldLabel>版本编码</FieldLabel>
                      <Input placeholder="例如 syllabus-2027" value={createForm.code} onChange={(event) => setCreateForm({ ...createForm, code: event.target.value })} />
                    </label>
                    <label>
                      <FieldLabel>版本名称</FieldLabel>
                      <Input placeholder="例如 2027 考纲" value={createForm.name} onChange={(event) => setCreateForm({ ...createForm, name: event.target.value })} />
                    </label>
                    <label>
                      <FieldLabel>生效年份</FieldLabel>
                      <Input type="number" min={2000} max={2200} value={createForm.effective_year} onChange={(event) => setCreateForm({ ...createForm, effective_year: Number(event.target.value) || new Date().getFullYear() })} />
                    </label>
                    <label>
                      <FieldLabel>说明（可选）</FieldLabel>
                      <Input placeholder="记录本次版本变化" value={createForm.description} onChange={(event) => setCreateForm({ ...createForm, description: event.target.value })} />
                    </label>
                    <Button className="w-full" disabled={!createForm.code.trim() || !createForm.name.trim() || createMutation.isPending} onClick={() => createMutation.mutate()}>
                      <Plus className="h-4 w-4" />
                      创建草稿
                    </Button>
                  </div>
                </div>
              </div>
            </ManagementPanel>
          ) : null}
        </div>

        <div className="space-y-5">
          <ManagementPanel
            variant="focus"
            title={detail?.name ?? "版本范围"}
            description={detail ? `${detail.code} · 生效年份 ${detail.effective_year} · ${STATUS_LABEL[detail.status]}` : "从左侧选择一个版本查看详情。"}
            actions={detail && canWrite && detail.status === "draft" ? (
              <>
                <Button variant="secondary" disabled={saving || selectedKnowledgePointIds.size === 0} onClick={() => activateMutation.mutate()}>
                  <ShieldCheck className="h-4 w-4" />
                  设为当前版本
                </Button>
                <Button variant="secondary" disabled={saving} onClick={() => archiveMutation.mutate()}>
                  归档
                </Button>
              </>
            ) : detail ? <StatusBadge tone={statusTone(detail.status)}>{STATUS_LABEL[detail.status]}</StatusBadge> : undefined}
            contentClassName="p-0"
          >
            {!detail ? <EmptyState>请选择一个考纲版本。</EmptyState> : (
              <>
                <div className="border-b border-[var(--color-border-light)] bg-[rgba(74,111,138,0.025)]">
                  <div className="flex flex-col gap-3 px-5 py-3.5 lg:flex-row lg:items-center lg:justify-between">
                    <div className="flex flex-wrap items-center gap-2 text-sm text-[var(--color-text-secondary)]">
                      <span>已选择 <b className="text-[var(--ink)]">{selectedKnowledgePointIds.size}</b> 个知识点</span>
                      {detail.status === "draft" ? <StatusBadge tone={membershipDirty ? "warning" : "success"}>{membershipDirty ? "有未保存变更" : "范围已保存"}</StatusBadge> : <StatusBadge tone="neutral">只读</StatusBadge>}
                    </div>
                    {detail.status === "draft" && canWrite ? (
                      <div className="flex flex-wrap gap-2">
                        <Button variant="secondary" size="sm" onClick={() => setSelectedKnowledgePointIds(new Set(catalog.map((item) => item.knowledge_point_id)))}>全选</Button>
                        <Button size="sm" disabled={membershipMutation.isPending || selectedKnowledgePointIds.size === 0 || !membershipDirty} onClick={() => membershipMutation.mutate()}>
                          <Save className="h-4 w-4" />
                          保存范围
                        </Button>
                      </div>
                    ) : null}
                  </div>
                  <div className="flex flex-col gap-2 border-t border-[var(--mgmt-line)]/70 bg-[rgba(255,254,250,0.84)] px-5 py-3 backdrop-blur-md sm:flex-row sm:items-center sm:justify-between">
                    <label className="relative block w-full sm:max-w-sm">
                      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
                      <Input
                        className="h-10 bg-white pl-9 pr-9 shadow-[inset_0_0_0_1px_rgba(255,255,255,0.55)]"
                        value={catalogKeyword}
                        onChange={(event) => setCatalogKeyword(event.target.value)}
                        placeholder="搜索知识点或科目"
                        aria-label="搜索知识点"
                      />
                      {catalogKeyword ? (
                        <button
                          type="button"
                          onClick={() => setCatalogKeyword("")}
                          className="absolute right-2 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-md text-[var(--color-text-hint)] transition hover:bg-[var(--mgmt-steel)] hover:text-[var(--ink)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]"
                          aria-label="清空知识点搜索"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      ) : null}
                    </label>
                    <div className="flex flex-wrap items-center justify-end gap-2.5">
                      <span className="mr-1 text-xs tabular-nums text-[var(--color-text-tertiary)]">{groupedCatalog.length} 个科目 · 显示 {visibleCatalog.length} / {catalog.length}</span>
                      <Button variant="ghost" size="sm" onClick={expandAllSubjects} disabled={groupedCatalog.length === 0 || collapsedSubjects.size === 0}>
                        全部展开
                      </Button>
                      <Button variant="ghost" size="sm" onClick={collapseAllSubjects} disabled={groupedCatalog.length === 0 || groupedCatalog.every(([subjectKey]) => collapsedSubjects.has(subjectKey))}>
                        全部收起
                      </Button>
                    </div>
                  </div>
                </div>

                <div className="space-y-3 p-4 sm:p-5">
                  {groupedCatalog.map(([subjectKey, items]) => {
                    const subjectName = items[0]?.subject_name ?? "未分类科目";
                    const subjectCode = items[0]?.subject_code ?? "unknown";
                    const isCoreSubject = ["data_structure", "computer_organization", "operating_system", "computer_network"].includes(subjectCode);
                    const selectedCount = items.filter((item) => selectedKnowledgePointIds.has(item.knowledge_point_id)).length;
                    const collapsed = collapsedSubjects.has(subjectKey);
                    return (
                      <section key={subjectKey} className="overflow-hidden rounded-[15px] border border-[var(--mgmt-line)] bg-white shadow-[0_6px_18px_rgba(31,49,61,0.02)] transition-[border-color,box-shadow] duration-200 hover:border-[rgba(74,111,138,0.27)] hover:shadow-[0_10px_24px_rgba(31,49,61,0.035)] motion-reduce:transition-none">
                        <button
                          type="button"
                          onClick={() => toggleSubjectGroup(subjectKey)}
                          aria-expanded={!collapsed}
                          className="group flex w-full items-center gap-3 px-4 py-3 text-left transition-colors duration-200 hover:bg-[rgba(237,243,246,0.42)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--color-primary)] motion-reduce:transition-none"
                        >
                          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[10px] border border-[rgba(74,111,138,0.16)] bg-[var(--mgmt-steel)] text-[var(--color-primary-dark)]">
                            <Layers3 className="h-4 w-4" />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="flex flex-wrap items-center gap-2">
                              <span className="text-sm font-bold leading-5 tracking-[-0.01em] text-[var(--ink)]">{subjectName}</span>
                              <StatusBadge tone={isCoreSubject ? "accent" : "neutral"}>{isCoreSubject ? "核心科目" : "扩展科目"}</StatusBadge>
                            </span>
                            <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] leading-4 text-[var(--color-text-tertiary)]">
                              <span>{subjectCode}</span>
                              <span aria-hidden="true" className="text-slate-300">·</span>
                              <span className="tabular-nums">已选 {selectedCount} / {items.length}</span>
                            </span>
                            <ManagementProgress className="mt-2 max-w-sm" value={selectedCount} max={items.length} tone={selectedCount === items.length ? "success" : "accent"} />
                          </span>
                          <ChevronDown className={`h-4 w-4 shrink-0 text-[var(--color-text-hint)] transition-transform duration-200 group-hover:text-[var(--color-primary-dark)] motion-reduce:transition-none ${collapsed ? "-rotate-90" : "rotate-0"}`} />
                        </button>
                        <div className={`grid transition-[grid-template-rows,opacity] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none ${collapsed ? "grid-rows-[0fr] opacity-0" : "grid-rows-[1fr] opacity-100"}`}>
                          <div className="overflow-hidden">
                            <div className="grid gap-2 border-t border-[var(--mgmt-line)] bg-[rgba(250,251,251,0.72)] p-3 md:grid-cols-2">
                              {items.map((item) => {
                                const checked = selectedKnowledgePointIds.has(item.knowledge_point_id);
                                const disabled = detail.status !== "draft" || !canWrite;
                                return (
                                  <button
                                    key={item.knowledge_point_id}
                                    disabled={disabled}
                                    onClick={() => toggleKnowledgePoint(item.knowledge_point_id)}
                                    className={`flex min-h-[72px] items-start gap-3 rounded-[11px] border px-3.5 py-3 text-left transition-[background-color,border-color,box-shadow,transform] duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] active:scale-[0.99] disabled:cursor-default disabled:active:scale-100 motion-reduce:transition-none ${checked ? "border-[rgba(74,111,138,0.30)] bg-[var(--mgmt-steel)] shadow-[inset_2px_0_0_var(--color-primary),0_5px_16px_rgba(45,80,104,0.035)]" : "border-[var(--mgmt-line)] bg-white hover:border-[rgba(74,111,138,0.28)] hover:bg-slate-50/55"}`}
                                  >
                                    <span className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-md border transition-[background-color,border-color,transform] duration-200 ${checked ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-white" : "border-[var(--color-border)] bg-white text-transparent"}`}>
                                      <Check className="h-3 w-3" strokeWidth={3} />
                                    </span>
                                    <span className="min-w-0">
                                      <span className="block text-sm font-medium leading-5 text-[var(--ink)]">{item.name}</span>
                                      <span className="mt-1 block text-[11px] leading-4 text-[var(--color-text-tertiary)]">难度 {item.difficulty_level} · KP #{item.knowledge_point_id}</span>
                                    </span>
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        </div>
                      </section>
                    );
                  })}
                  {!catalogQuery.isLoading && groupedCatalog.length === 0 ? <EmptyState>{catalogKeyword ? "没有匹配的知识点。尝试缩短关键词或清空搜索。" : "当前版本没有可展示的知识点目录。"}</EmptyState> : null}
                  {catalogQuery.isLoading ? <ManagementSkeletonRows rows={6} /> : null}
                </div>
              </>
            )}
          </ManagementPanel>

          {detail ? (
            <div className="grid gap-3 md:grid-cols-2">
              <ManagementPanel variant="quiet" title="基础覆盖" description="至少有 1 道已审核且启用的题目即视为覆盖。">
                <div className="flex items-end justify-between gap-4">
                  <div>
                    <p className="text-3xl font-semibold tracking-[-0.03em] tabular-nums text-[var(--ink)]">{coverageQuery.data?.covered_knowledge_points ?? 0}<span className="text-base font-medium text-[var(--color-text-tertiary)]"> / {coverageQuery.data?.total_knowledge_points ?? 0}</span></p>
                    <p className="mt-1 text-xs text-[var(--color-text-secondary)]">覆盖率 {coveragePct}%</p>
                  </div>
                  <StatusBadge tone={coveragePct >= 90 ? "success" : "warning"}>{coveragePct >= 90 ? "覆盖良好" : "仍有缺口"}</StatusBadge>
                </div>
                <ManagementProgress className="mt-4" value={coveragePct} tone={coveragePct >= 90 ? "success" : "warning"} />
                {coverageQuery.data?.items.some((item) => !item.covered) ? (
                  <div className="mt-4 flex flex-wrap gap-1.5">
                    {coverageQuery.data.items.filter((item) => !item.covered).slice(0, 8).map((item) => (
                      <StatusBadge key={item.syllabus_knowledge_point_id} tone="warning">缺题 · {item.name}</StatusBadge>
                    ))}
                  </div>
                ) : null}
              </ManagementPanel>
              <ManagementPanel variant="quiet" title="跨版本映射" description="自动关系与手工关系统一在当前版本下查看。" icon={<GitMerge className="h-4 w-4" />}>
                <p className="text-3xl font-semibold tracking-[-0.03em] tabular-nums text-[var(--ink)]">{mappingsQuery.data?.length ?? 0}</p>
                <p className="mt-2 text-xs leading-5 text-[var(--color-text-secondary)]">激活时自动生成 unchanged、renamed、added、removed；合并、拆分、替换关系可手工补充。</p>
              </ManagementPanel>
            </div>
          ) : null}

          {detail?.status === "draft" && canWrite ? (
            <ManagementPanel title="手工跨版本映射" description="仅维护无法由同一知识点 ID 自动表达的合并、拆分或替换关系。" icon={<Link2 className="h-4 w-4" />}>
              <div className="grid gap-4 lg:grid-cols-2">
                <label>
                  <FieldLabel>来源版本</FieldLabel>
                  <select className={selectClass} value={mappingSourceVersionId ?? ""} onChange={(event) => setMappingSourceVersionId(Number(event.target.value) || null)}>
                    {(versionsQuery.data ?? []).filter((item) => item.id !== detail.id).map((item) => <option key={item.id} value={item.id}>{item.name} · {STATUS_LABEL[item.status]}</option>)}
                  </select>
                </label>
                <label>
                  <FieldLabel>关系类型</FieldLabel>
                  <select className={selectClass} value={mappingForm.relation_type} onChange={(event) => setMappingForm({ ...mappingForm, relation_type: event.target.value as "merged" | "split" | "replaced" })}>
                    <option value="replaced">替换 replaced</option>
                    <option value="merged">合并 merged</option>
                    <option value="split">拆分 split</option>
                  </select>
                </label>
                <label>
                  <FieldLabel>旧版知识点</FieldLabel>
                  <select className={selectClass} value={mappingForm.from_syllabus_knowledge_point_id || ""} onChange={(event) => setMappingForm({ ...mappingForm, from_syllabus_knowledge_point_id: Number(event.target.value) })}>
                    <option value="">请选择</option>
                    {(sourceDetailQuery.data?.knowledge_points ?? []).map((item) => <option key={item.id} value={item.id}>{item.subject_name} · {item.name}</option>)}
                  </select>
                </label>
                <label>
                  <FieldLabel>新版知识点</FieldLabel>
                  <select className={selectClass} value={mappingForm.to_syllabus_knowledge_point_id || ""} onChange={(event) => setMappingForm({ ...mappingForm, to_syllabus_knowledge_point_id: Number(event.target.value) })}>
                    <option value="">请选择</option>
                    {(detail.knowledge_points ?? []).map((item) => <option key={item.id} value={item.id}>{item.subject_name} · {item.name}</option>)}
                  </select>
                </label>
              </div>
              <div className="mt-4 flex flex-col gap-3 sm:flex-row">
                <Input className="flex-1" placeholder="映射说明（可选）" value={mappingForm.note} onChange={(event) => setMappingForm({ ...mappingForm, note: event.target.value })} />
                <Button disabled={!mappingForm.from_syllabus_knowledge_point_id || !mappingForm.to_syllabus_knowledge_point_id || mappingMutation.isPending} onClick={() => mappingMutation.mutate()}>
                  <Link2 className="h-4 w-4" />
                  新增映射
                </Button>
              </div>
            </ManagementPanel>
          ) : null}

          {detail && (mappingsQuery.data?.length ?? 0) > 0 ? (
            <ManagementPanel title="映射明细" description={`展示当前版本前 ${Math.min(mappingsQuery.data?.length ?? 0, 60)} 条映射关系。`} contentClassName="p-0">
              <div className="divide-y divide-[var(--color-border-light)]">
                {(mappingsQuery.data ?? []).slice(0, 60).map((item) => (
                  <div key={item.id} className="grid gap-2 px-4 py-3.5 text-sm transition-colors hover:bg-[rgba(237,243,246,0.38)] md:grid-cols-[110px_minmax(0,1fr)_30px_minmax(0,1fr)_40px] md:items-center md:px-5">
                    <StatusBadge tone={["merged", "split", "replaced"].includes(item.relation_type) ? "accent" : "neutral"}>{RELATION_LABEL[item.relation_type] ?? item.relation_type}</StatusBadge>
                    <span className="truncate text-[var(--ink)]">{item.from_name ?? "无"}</span>
                    <span className="hidden place-items-center text-[var(--color-text-tertiary)] md:grid"><ArrowRight className="h-4 w-4" /></span>
                    <span className="min-w-0 truncate text-[var(--ink)]">{item.to_name ?? "无"}{item.note ? <span className="ml-2 text-xs text-[var(--color-text-tertiary)]">{item.note}</span> : null}</span>
                    {detail.status === "draft" && canWrite && ["merged", "split", "replaced"].includes(item.relation_type) ? (
                      <Button className="h-8 w-8 px-0 text-red-600 hover:bg-red-50 hover:text-red-700" size="sm" variant="ghost" disabled={deleteMappingMutation.isPending} onClick={() => deleteMappingMutation.mutate(item.id)} aria-label="删除映射">
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    ) : <span />}
                  </div>
                ))}
              </div>
            </ManagementPanel>
          ) : null}

          {error ? <ManagementNotice tone="danger" title="操作未完成">请刷新数据后重试；若问题持续，请检查写入权限和接口状态。</ManagementNotice> : null}
        </div>
      </div>
    </ManagementPage>
  );
}

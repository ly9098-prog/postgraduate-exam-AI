"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, CheckCircle2, Link2, RefreshCw, Save, ShieldCheck, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
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

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  active: "当前生效",
  archived: "已归档",
};

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
  const groupedCatalog = useMemo(() => {
    const groups = new Map<string, typeof catalog>();
    for (const item of catalog) {
      const bucket = groups.get(item.subject_name) ?? [];
      bucket.push(item);
      groups.set(item.subject_name, bucket);
    }
    return [...groups.entries()];
  }, [catalog]);
  const activeVersion = versionsQuery.data?.find((item) => item.status === "active");
  const coveragePct = Math.round((coverageQuery.data?.coverage_ratio ?? 0) * 100);
  const saving = membershipMutation.isPending || activateMutation.isPending || archiveMutation.isPending || mappingMutation.isPending || deleteMappingMutation.isPending;

  function toggleKnowledgePoint(id: number) {
    if (!detail || detail.status !== "draft" || !canWrite) return;
    setSelectedKnowledgePointIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  const error = createMutation.isError || membershipMutation.isError || activateMutation.isError || archiveMutation.isError || mappingMutation.isError || deleteMappingMutation.isError;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-[var(--color-primary)]">408-SYLLABUS</p>
          <h1 className="font-display text-3xl font-bold text-[var(--ink)]">408 考纲版本治理</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--color-text-secondary)]">
            Subject 保持稳定；考纲版本只冻结当前版本包含哪些知识点及其名称/描述语义。active 版本不可直接改成员，切换版本时会保留跨版本映射。
          </p>
        </div>
        <Button variant="secondary" onClick={() => refreshAll()} disabled={versionsQuery.isFetching}>
          <RefreshCw className={`mr-2 h-4 w-4 ${versionsQuery.isFetching ? "animate-spin" : ""}`} />刷新
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card><CardContent className="flex items-center gap-4"><div className="rounded-2xl bg-blue-50 p-3 text-blue-700"><BookOpen className="h-5 w-5" /></div><div><p className="text-lg font-bold">{activeVersion?.name ?? "未设置"}</p><p className="text-sm text-[var(--color-text-secondary)]">当前 active 考纲</p></div></CardContent></Card>
        <Card><CardContent><p className="text-2xl font-bold">{detail?.knowledge_point_count ?? 0}</p><p className="text-sm text-[var(--color-text-secondary)]">所选版本知识点</p></CardContent></Card>
        <Card><CardContent><p className="text-2xl font-bold">{coveragePct}%</p><p className="text-sm text-[var(--color-text-secondary)]">所选版本基础题库覆盖</p></CardContent></Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-[340px_minmax(0,1fr)]">
        <div className="space-y-6">
          <Card>
            <CardHeader><h2 className="font-display text-lg font-bold">版本列表</h2></CardHeader>
            <CardContent className="space-y-2">
              {(versionsQuery.data ?? []).map((item) => (
                <button key={item.id} onClick={() => setSelectedVersionId(item.id)} className={`w-full rounded-xl border px-3 py-3 text-left transition ${selectedVersionId === item.id ? "border-[var(--color-primary)] bg-blue-50/60" : "border-[var(--color-border)] hover:bg-slate-50"}`}>
                  <div className="flex items-center justify-between gap-2"><span className="font-semibold text-[var(--ink)]">{item.name}</span><span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">{STATUS_LABEL[item.status]}</span></div>
                  <p className="mt-1 text-xs text-[var(--color-text-tertiary)]">{item.code} · {item.effective_year} · {item.knowledge_point_count} KP</p>
                </button>
              ))}
              {!versionsQuery.isLoading && !versionsQuery.data?.length ? <p className="py-6 text-center text-sm text-[var(--color-text-secondary)]">暂无版本</p> : null}
            </CardContent>
          </Card>

          {canWrite ? (
            <Card>
              <CardHeader><h2 className="font-display text-lg font-bold">新建 draft</h2></CardHeader>
              <CardContent className="space-y-3">
                <Input placeholder="code，例如 exam408-2027" value={createForm.code} onChange={(e) => setCreateForm({ ...createForm, code: e.target.value })} />
                <Input placeholder="版本名称" value={createForm.name} onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })} />
                <Input type="number" min={2000} max={2200} value={createForm.effective_year} onChange={(e) => setCreateForm({ ...createForm, effective_year: Number(e.target.value) || new Date().getFullYear() })} />
                <Input placeholder="说明（可选）" value={createForm.description} onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })} />
                <Button className="w-full" disabled={!createForm.code.trim() || !createForm.name.trim() || createMutation.isPending} onClick={() => createMutation.mutate()}>创建版本</Button>
                <p className="text-xs leading-5 text-[var(--color-text-tertiary)]">新 draft 默认继承当前 active 考纲范围，并用知识点当前名称/描述重新冻结快照。</p>
              </CardContent>
            </Card>
          ) : null}
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div><h2 className="font-display text-xl font-bold">{detail?.name ?? "选择一个考纲版本"}</h2>{detail ? <p className="mt-1 text-sm text-[var(--color-text-secondary)]">{detail.code} · 生效年份 {detail.effective_year} · {STATUS_LABEL[detail.status]}</p> : null}</div>
                {detail && canWrite ? <div className="flex gap-2">{detail.status === "draft" ? <Button variant="secondary" disabled={saving || selectedKnowledgePointIds.size === 0} onClick={() => activateMutation.mutate()}><ShieldCheck className="mr-2 h-4 w-4" />设为 active</Button> : null}{detail.status === "draft" ? <Button variant="secondary" disabled={saving} onClick={() => archiveMutation.mutate()}>归档</Button> : null}</div> : null}
              </div>
            </CardHeader>
            <CardContent>
              {!detail ? <p className="py-10 text-center text-sm text-[var(--color-text-secondary)]">请选择版本</p> : (
                <div className="space-y-5">
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-slate-50 px-4 py-3 text-sm">
                    <span>当前选择 <b>{selectedKnowledgePointIds.size}</b> 个知识点；active/archived 版本只读。</span>
                    {detail.status === "draft" && canWrite ? <div className="flex gap-2"><Button variant="secondary" onClick={() => setSelectedKnowledgePointIds(new Set(catalog.map((item) => item.knowledge_point_id)))}>全选当前 408 KP</Button><Button disabled={membershipMutation.isPending || selectedKnowledgePointIds.size === 0} onClick={() => membershipMutation.mutate()}><Save className="mr-2 h-4 w-4" />保存范围</Button></div> : null}
                  </div>

                  {groupedCatalog.map(([subject, items]) => (
                    <div key={subject}>
                      <div className="mb-2 flex items-center justify-between"><h3 className="font-semibold text-[var(--ink)]">{subject}</h3><span className="text-xs text-[var(--color-text-tertiary)]">{items.filter((item) => selectedKnowledgePointIds.has(item.knowledge_point_id)).length}/{items.length}</span></div>
                      <div className="grid gap-2 md:grid-cols-2">
                        {items.map((item) => {
                          const checked = selectedKnowledgePointIds.has(item.knowledge_point_id);
                          return <button key={item.knowledge_point_id} disabled={detail.status !== "draft" || !canWrite} onClick={() => toggleKnowledgePoint(item.knowledge_point_id)} className={`flex items-start gap-3 rounded-xl border px-3 py-3 text-left ${checked ? "border-blue-200 bg-blue-50/60" : "border-[var(--color-border)]"}`}><span className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded border ${checked ? "border-blue-600 bg-blue-600 text-white" : "border-slate-300"}`}>{checked ? "✓" : ""}</span><span><span className="block text-sm font-semibold text-[var(--ink)]">{item.name}</span><span className="mt-1 block text-xs text-[var(--color-text-tertiary)]">难度 {item.difficulty_level} · KP #{item.knowledge_point_id}</span></span></button>;
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {detail ? <div className="grid gap-4 md:grid-cols-2">
            <Card><CardHeader><h3 className="font-semibold">版本覆盖</h3></CardHeader><CardContent><div className="flex items-center gap-3"><CheckCircle2 className="h-5 w-5 text-emerald-600" /><div><p className="text-xl font-bold">{coverageQuery.data?.covered_knowledge_points ?? 0} / {coverageQuery.data?.total_knowledge_points ?? 0}</p><p className="text-sm text-[var(--color-text-secondary)]">至少有 1 道 approved active 题即计为基础覆盖</p></div></div>{coverageQuery.data?.items.some((item) => !item.covered) ? <div className="mt-4 flex flex-wrap gap-2">{coverageQuery.data.items.filter((item) => !item.covered).slice(0, 8).map((item) => <span key={item.syllabus_knowledge_point_id} className="rounded-full bg-amber-50 px-2.5 py-1 text-xs text-amber-800">缺题 · {item.name}</span>)}</div> : null}</CardContent></Card>
            <Card><CardHeader><h3 className="font-semibold">跨版本映射</h3></CardHeader><CardContent><p className="text-xl font-bold">{mappingsQuery.data?.length ?? 0}</p><p className="mt-1 text-sm text-[var(--color-text-secondary)]">激活时自动生成 unchanged / renamed / added / removed；merge/split/replaced 可在下方手工补充。</p></CardContent></Card>
          </div> : null}

          {detail?.status === "draft" && canWrite ? <Card>
            <CardHeader><h3 className="font-semibold">手工跨版本映射</h3></CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-[var(--color-text-secondary)]">用于同一知识点 ID 无法表达的合并、拆分、替换关系。自动 unchanged / renamed / added / removed 无需手工维护。</p>
              <div className="grid gap-3 lg:grid-cols-2">
                <label className="space-y-1 text-sm"><span className="text-[var(--color-text-secondary)]">来源版本</span><select className="h-10 w-full rounded-lg border border-[var(--color-border)] bg-white px-3" value={mappingSourceVersionId ?? ""} onChange={(e) => setMappingSourceVersionId(Number(e.target.value) || null)}>{(versionsQuery.data ?? []).filter((item) => item.id !== detail.id).map((item) => <option key={item.id} value={item.id}>{item.name} · {STATUS_LABEL[item.status]}</option>)}</select></label>
                <label className="space-y-1 text-sm"><span className="text-[var(--color-text-secondary)]">关系类型</span><select className="h-10 w-full rounded-lg border border-[var(--color-border)] bg-white px-3" value={mappingForm.relation_type} onChange={(e) => setMappingForm({ ...mappingForm, relation_type: e.target.value as "merged" | "split" | "replaced" })}><option value="replaced">replaced · 替换</option><option value="merged">merged · 合并</option><option value="split">split · 拆分</option></select></label>
                <label className="space-y-1 text-sm"><span className="text-[var(--color-text-secondary)]">旧版知识点</span><select className="h-10 w-full rounded-lg border border-[var(--color-border)] bg-white px-3" value={mappingForm.from_syllabus_knowledge_point_id || ""} onChange={(e) => setMappingForm({ ...mappingForm, from_syllabus_knowledge_point_id: Number(e.target.value) })}><option value="">请选择</option>{(sourceDetailQuery.data?.knowledge_points ?? []).map((item) => <option key={item.id} value={item.id}>{item.subject_name} · {item.name}</option>)}</select></label>
                <label className="space-y-1 text-sm"><span className="text-[var(--color-text-secondary)]">新版知识点</span><select className="h-10 w-full rounded-lg border border-[var(--color-border)] bg-white px-3" value={mappingForm.to_syllabus_knowledge_point_id || ""} onChange={(e) => setMappingForm({ ...mappingForm, to_syllabus_knowledge_point_id: Number(e.target.value) })}><option value="">请选择</option>{(detail.knowledge_points ?? []).map((item) => <option key={item.id} value={item.id}>{item.subject_name} · {item.name}</option>)}</select></label>
              </div>
              <div className="flex flex-wrap gap-2"><Input placeholder="映射说明（可选）" value={mappingForm.note} onChange={(e) => setMappingForm({ ...mappingForm, note: e.target.value })} /><Button disabled={!mappingForm.from_syllabus_knowledge_point_id || !mappingForm.to_syllabus_knowledge_point_id || mappingMutation.isPending} onClick={() => mappingMutation.mutate()}><Link2 className="mr-2 h-4 w-4" />新增映射</Button></div>
            </CardContent>
          </Card> : null}

          {detail && (mappingsQuery.data?.length ?? 0) > 0 ? <Card>
            <CardHeader><h3 className="font-semibold">映射明细</h3></CardHeader>
            <CardContent className="space-y-2">
              {(mappingsQuery.data ?? []).slice(0, 60).map((item) => <div key={item.id} className="grid gap-2 rounded-xl border border-[var(--color-border)] px-3 py-2 text-sm md:grid-cols-[110px_1fr_auto_1fr_auto] md:items-center"><span className="font-mono text-xs text-[var(--color-text-secondary)]">{item.relation_type}</span><span>{item.from_name ?? "∅"}</span><span className="text-[var(--color-text-tertiary)]">→</span><span>{item.to_name ?? "∅"}{item.note ? <span className="ml-2 text-xs text-[var(--color-text-tertiary)]">{item.note}</span> : null}</span>{detail.status === "draft" && canWrite && ["merged", "split", "replaced"].includes(item.relation_type) ? <Button variant="secondary" disabled={deleteMappingMutation.isPending} onClick={() => deleteMappingMutation.mutate(item.id)}><Trash2 className="h-4 w-4" /></Button> : <span />}</div>)}
            </CardContent>
          </Card> : null}

          {error ? <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">操作失败，请刷新数据后重试。</div> : null}
        </div>
      </div>
    </div>
  );
}

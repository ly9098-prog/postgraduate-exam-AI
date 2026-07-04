"use client";

import { useCallback, useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { apiRequest, toQuery } from "@/lib/api/client";
import { AuditLogFilters } from "@/components/audit-logs/audit-log-filters";
import { AuditLogList } from "@/components/audit-logs/audit-log-list";
import { AuditLogDrawer } from "@/components/audit-logs/audit-log-drawer";
import { localDateToUtcIso, localDateToUtcIsoNext } from "@/components/audit-logs/date-utils";
import type { AuditLogListItem, PaginatedResponse } from "@/lib/api/types";
import type { AuditLogFiltersState } from "@/components/audit-logs/audit-log-filters";

export default function AuditLogsPage() {
  // ── Filters ──
  const [filters, setFilters] = useState<AuditLogFiltersState>({
    keyword: "",
    debouncedKeyword: "",
    severity: "",
    status: "",
    action: "",
    resourceType: "",
    dateFrom: "",
    dateTo: "",
  });
  const [page, setPage] = useState(1);
  const [detailId, setDetailId] = useState<number | null>(null);

  const handleFilterChange = useCallback((patch: Partial<AuditLogFiltersState>) => {
    setFilters((prev) => ({ ...prev, ...patch }));
    if ("debouncedKeyword" in patch || "severity" in patch || "status" in patch || "action" in patch ||
        "resourceType" in patch || "dateFrom" in patch || "dateTo" in patch) {
      setPage(1);
    }
  }, []);

  const handleReset = useCallback(() => {
    setFilters({
      keyword: "",
      debouncedKeyword: "",
      severity: "",
      status: "",
      action: "",
      resourceType: "",
      dateFrom: "",
      dateTo: "",
    });
    setPage(1);
  }, []);

  const openDetail = useCallback((id: number) => {
    setDetailId(id);
  }, []);

  const closeDetail = useCallback(() => {
    setDetailId(null);
  }, []);

  // ── API params ──
  const queryParams = useMemo(() => {
    const params: Record<string, string | number | boolean | undefined | null> = {
      page,
      pageSize: 20,
      severity: filters.severity,
      status: filters.status,
      action: filters.action,
      resourceType: filters.resourceType,
      keyword: filters.debouncedKeyword,
    };
    if (filters.dateFrom) {
      params["from"] = localDateToUtcIso(filters.dateFrom);
    }
    if (filters.dateTo) {
      params["to"] = localDateToUtcIsoNext(filters.dateTo);
    }
    return params;
  }, [page, filters.severity, filters.status, filters.action, filters.resourceType, filters.debouncedKeyword, filters.dateFrom, filters.dateTo]);

  // ── Queries ──
  const logs = useQuery({
    queryKey: ["audit-logs", "list", queryParams],
    queryFn: () => apiRequest<PaginatedResponse<AuditLogListItem>>(`/audit-logs${toQuery(queryParams)}`),
    retry: 1,
    staleTime: 10_000,
    refetchOnMount: "always",
    placeholderData: keepPreviousData,
  });

  const hasFilters = Boolean(
    filters.severity || filters.status || filters.action || filters.resourceType ||
    filters.debouncedKeyword || filters.dateFrom || filters.dateTo,
  );

  // ── Render ──
  return (
    <div className="space-y-5">
      {/* ── Filters (no title above) ── */}
      <AuditLogFilters
        filters={filters}
        onFilterChange={handleFilterChange}
        onReset={handleReset}
        onRefresh={() => logs.refetch()}
        isRefreshing={logs.isFetching}
      />

      {/* ── List ── */}
      <AuditLogList
        data={logs.data}
        isLoading={logs.isLoading}
        isError={logs.isError}
        isFetching={logs.isFetching}
        error={logs.error}
        page={page}
        totalPages={logs.data?.total_pages ?? 1}
        onPageChange={setPage}
        onOpenDetail={openDetail}
        onRefresh={() => logs.refetch()}
        onReset={handleReset}
        hasFilters={hasFilters}
      />

      {/* ── Detail Drawer ── */}
      <AuditLogDrawer detailId={detailId} onClose={closeDetail} />
    </div>
  );
}

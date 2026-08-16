"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  CheckCircle2,
  Download,
  RefreshCw,
  Search,
  ShieldCheck,
  UserCheck,
  UserPlus,
  UsersRound,
  UserX,
} from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { CustomCheckbox } from "@/components/ui/custom-checkbox";
import { CustomSelect } from "@/components/ui/custom-select";
import { Input } from "@/components/ui/input";
import { apiRequest, toQuery } from "@/lib/api/client";
import type { AppUser, PaginatedResponse } from "@/lib/api/types";
import { chinaDateString, chinaDateToUtcIso, formatChinaDateTime } from "@/lib/time";
import { cn } from "@/lib/utils";

type UserStatusFilter = "all" | "active" | "banned";
type UserAction = "ban" | "unban";
type ConfirmState = {
  action: UserAction;
  userIds: number[];
  label: string;
} | null;
type Notice = { tone: "success" | "error"; text: string } | null;
type PaginationItem = number | "ellipsis-left" | "ellipsis-right";

const STATUS_OPTIONS = [
  { value: "all", label: "全部状态" },
  { value: "active", label: "正常用户" },
  { value: "banned", label: "已封禁" },
];

const PAGE_SIZE_OPTIONS = [
  { value: "10", label: "10 条/页" },
  { value: "20", label: "20 条/页" },
  { value: "50", label: "50 条/页" },
  { value: "100", label: "100 条/页" },
];

function statusToQueryValue(status: UserStatusFilter): boolean | undefined {
  if (status === "active") return false;
  if (status === "banned") return true;
  return undefined;
}

function endOfChinaDateUtcIso(date: string): string {
  const nextDay = chinaDateToUtcIso(date, 1);
  if (!nextDay) return "";
  // The backend filter is inclusive (<=). Emit the final microsecond before
  // the next China calendar day so PostgreSQL microsecond precision is covered.
  return new Date(new Date(nextDay).getTime() - 1000).toISOString().replace(/\.\d{3}Z$/, ".999999Z");
}

function buildPagination(current: number, total: number): PaginationItem[] {
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1);

  if (current <= 4) return [1, 2, 3, 4, 5, "ellipsis-right", total];
  if (current >= total - 3) return [1, "ellipsis-left", total - 4, total - 3, total - 2, total - 1, total];

  return [1, "ellipsis-left", current - 1, current, current + 1, "ellipsis-right", total];
}

function csvEscape(value: string | number | null | undefined): string {
  const text = value === null || value === undefined ? "" : String(value);
  return `"${text.replaceAll('"', '""')}"`;
}

function UserAvatar({ user }: { user: AppUser }) {
  const initial = (user.nickname || "用户").trim().charAt(0).toUpperCase() || "U";

  if (user.avatar_url) {
    return (
      <img
        src={user.avatar_url}
        alt=""
        className="h-9 w-9 shrink-0 rounded-full border border-[var(--color-border-light)] bg-[var(--color-primary-light)] object-cover"
      />
    );
  }

  return (
    <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-[var(--color-primary)]/15 bg-[var(--color-primary-light)] text-sm font-bold text-[var(--color-primary-dark)]">
      {initial}
    </div>
  );
}

function MetricCard({
  label,
  value,
  helper,
  icon,
  tone = "primary",
  loading,
}: {
  label: string;
  value: number;
  helper: string;
  icon: ReactNode;
  tone?: "primary" | "success" | "danger" | "neutral";
  loading?: boolean;
}) {
  const toneClass = {
    primary: "border-[var(--color-primary)]/15 bg-[var(--color-primary-light)] text-[var(--color-primary-dark)]",
    success: "border-[var(--color-success)]/15 bg-[var(--color-success-light)] text-[var(--color-success)]",
    danger: "border-[var(--color-danger)]/15 bg-[var(--color-danger-light)] text-[var(--color-danger)]",
    neutral: "border-[var(--color-border)] bg-white text-[var(--color-text-secondary)]",
  }[tone];

  return (
    <div className="rounded-2xl border border-[var(--color-border-light)] bg-white/80 p-4 shadow-[0_1px_3px_rgba(27,39,51,0.04)]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium text-[var(--color-text-secondary)]">{label}</p>
          <p className="mt-2 text-2xl font-bold tracking-tight text-[var(--ink)] tabular-nums">
            {loading ? <span className="inline-block h-7 w-16 animate-pulse rounded-lg bg-[var(--color-border-light)]" /> : value.toLocaleString("zh-CN")}
          </p>
        </div>
        <span className={cn("grid h-9 w-9 place-items-center rounded-xl border", toneClass)}>{icon}</span>
      </div>
      <p className="mt-2 text-[11px] text-[var(--color-text-hint)]">{helper}</p>
    </div>
  );
}

export default function AppUsersPage() {
  const queryClient = useQueryClient();
  const [searchInput, setSearchInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState<UserStatusFilter>("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [batchAction, setBatchAction] = useState("");
  const [confirmState, setConfirmState] = useState<ConfirmState>(null);
  const [banReason, setBanReason] = useState("后台人工封禁");
  const [notice, setNotice] = useState<Notice>(null);
  const [exporting, setExporting] = useState(false);

  const today = chinaDateString();
  const isBanned = statusToQueryValue(status);
  const createdFrom = dateFrom ? chinaDateToUtcIso(dateFrom) : undefined;
  const createdTo = dateTo ? endOfChinaDateUtcIso(dateTo) : undefined;

  const users = useQuery({
    queryKey: ["app-users", page, pageSize, keyword, status, createdFrom, createdTo],
    queryFn: () =>
      apiRequest<PaginatedResponse<AppUser>>(
        `/app-users${toQuery({
          page,
          page_size: pageSize,
          keyword: keyword || undefined,
          is_banned: isBanned,
          created_from: createdFrom,
          created_to: createdTo,
        })}`,
      ),
  });

  const totalUsers = useQuery({
    queryKey: ["app-users-summary", "total"],
    queryFn: () => apiRequest<PaginatedResponse<AppUser>>(`/app-users${toQuery({ page: 1, page_size: 1 })}`),
    staleTime: 30_000,
  });

  const activeUsers = useQuery({
    queryKey: ["app-users-summary", "active"],
    queryFn: () => apiRequest<PaginatedResponse<AppUser>>(`/app-users${toQuery({ page: 1, page_size: 1, is_banned: false })}`),
    staleTime: 30_000,
  });

  const bannedUsers = useQuery({
    queryKey: ["app-users-summary", "banned"],
    queryFn: () => apiRequest<PaginatedResponse<AppUser>>(`/app-users${toQuery({ page: 1, page_size: 1, is_banned: true })}`),
    staleTime: 30_000,
  });

  const todayUsers = useQuery({
    queryKey: ["app-users-summary", "today", today],
    queryFn: () =>
      apiRequest<PaginatedResponse<AppUser>>(
        `/app-users${toQuery({
          page: 1,
          page_size: 1,
          created_from: chinaDateToUtcIso(today),
          created_to: endOfChinaDateUtcIso(today),
        })}`,
      ),
    staleTime: 30_000,
  });

  const actionMutation = useMutation({
    mutationFn: async ({ action, userIds }: Exclude<ConfirmState, null>) => {
      // There is no bulk endpoint today. Use small chunks instead of firing up to
      // 100 admin writes at once when the operator selects an entire page.
      for (let index = 0; index < userIds.length; index += 5) {
        const chunk = userIds.slice(index, index + 5);
        await Promise.all(
          chunk.map((id) =>
            apiRequest(`/app-users/${id}/${action}`, {
              method: "POST",
              body: action === "ban" ? JSON.stringify({ reason: banReason.trim() || null }) : undefined,
            }),
          ),
        );
      }
    },
    onSuccess: (_result, variables) => {
      const actionLabel = variables.action === "ban" ? "封禁" : "解封";
      setNotice({ tone: "success", text: `${variables.userIds.length > 1 ? `已${actionLabel} ${variables.userIds.length} 位用户` : `${actionLabel}成功`}。` });
      setConfirmState(null);
      setSelectedIds(new Set());
      setBatchAction("");
      queryClient.invalidateQueries({ queryKey: ["app-users"] });
      queryClient.invalidateQueries({ queryKey: ["app-users-summary"] });
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : "操作失败，请稍后重试。" });
    },
  });

  const currentItems = users.data?.items ?? [];
  const totalPages = Math.max(users.data?.total_pages ?? 1, 1);
  const pagination = useMemo(() => buildPagination(page, totalPages), [page, totalPages]);
  const selectedOnPage = currentItems.filter((user) => selectedIds.has(user.id));
  const allPageSelected = currentItems.length > 0 && selectedOnPage.length === currentItems.length;
  const somePageSelected = selectedOnPage.length > 0 && !allPageSelected;

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  useEffect(() => {
    setSelectedIds(new Set());
    setBatchAction("");
  }, [page, pageSize, keyword, status, createdFrom, createdTo]);

  const applySearch = () => {
    setKeyword(searchInput.trim());
    setPage(1);
  };

  const resetFilters = () => {
    setSearchInput("");
    setKeyword("");
    setStatus("all");
    setDateFrom("");
    setDateTo("");
    setPage(1);
  };

  const togglePageSelection = (checked: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      currentItems.forEach((user) => {
        if (checked) next.add(user.id);
        else next.delete(user.id);
      });
      return next;
    });
  };

  const toggleUserSelection = (userId: number, checked: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (checked) next.add(userId);
      else next.delete(userId);
      return next;
    });
  };

  const openSingleAction = (user: AppUser) => {
    setConfirmState({
      action: user.is_banned ? "unban" : "ban",
      userIds: [user.id],
      label: user.nickname || user.openid,
    });
  };

  const openBatchAction = (action: UserAction) => {
    const candidates = selectedOnPage.filter((user) => (action === "ban" ? !user.is_banned : user.is_banned));
    setBatchAction("");
    if (!candidates.length) {
      setNotice({
        tone: "error",
        text: action === "ban" ? "所选用户均已处于封禁状态。" : "所选用户均为正常状态，无需解封。",
      });
      return;
    }
    setConfirmState({
      action,
      userIds: candidates.map((user) => user.id),
      label: `${candidates.length} 位已选用户`,
    });
  };

  const exportUsers = async () => {
    setExporting(true);
    setNotice(null);
    try {
      const first = await apiRequest<PaginatedResponse<AppUser>>(
        `/app-users${toQuery({
          page: 1,
          page_size: 100,
          keyword: keyword || undefined,
          is_banned: isBanned,
          created_from: createdFrom,
          created_to: createdTo,
        })}`,
      );
      const records = [...first.items];
      for (let currentPage = 2; currentPage <= first.total_pages; currentPage += 1) {
        const result = await apiRequest<PaginatedResponse<AppUser>>(
          `/app-users${toQuery({
            page: currentPage,
            page_size: 100,
            keyword: keyword || undefined,
            is_banned: isBanned,
            created_from: createdFrom,
            created_to: createdTo,
          })}`,
        );
        records.push(...result.items);
      }

      const header = ["ID", "昵称", "OpenID", "状态", "封禁原因", "封禁时间（北京时间）", "创建时间（北京时间）"];
      const rows = records.map((user) => [
        user.id,
        user.nickname || "未设置昵称",
        user.openid,
        user.is_banned ? "已封禁" : "正常",
        user.banned_reason || "",
        user.banned_at ? formatChinaDateTime(user.banned_at) : "",
        user.created_at ? formatChinaDateTime(user.created_at) : "",
      ]);
      const csv = `\uFEFF${[header, ...rows].map((row) => row.map(csvEscape).join(",")).join("\n")}`;
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `app-users-${today}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setNotice({ tone: "success", text: `已导出 ${records.length.toLocaleString("zh-CN")} 条用户数据。` });
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : "导出失败，请稍后重试。" });
    } finally {
      setExporting(false);
    }
  };

  const refreshAll = () => {
    setNotice(null);
    queryClient.invalidateQueries({ queryKey: ["app-users"] });
    queryClient.invalidateQueries({ queryKey: ["app-users-summary"] });
  };

  return (
    <div className="mx-auto w-full max-w-[1600px] space-y-5 pb-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.26em] text-[var(--color-text-hint)]">User Management</p>
          <h1 className="mt-1.5 font-display text-3xl font-bold tracking-tight text-[var(--ink)]">小程序用户管理</h1>
          <p className="mt-1.5 text-sm text-[var(--color-text-secondary)]">管理小程序用户信息，支持筛选、批量操作及数据导出。</p>
        </div>
        <div className="hidden text-xs text-[var(--color-text-hint)] md:block">首页 / 用户管理 / <span className="text-[var(--color-text-secondary)]">小程序用户</span></div>
      </header>

      <Card className="overflow-visible rounded-2xl">
        <CardContent className="p-4 lg:p-5">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
            <label className="relative min-w-0 flex-1 xl:max-w-md">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-hint)]" />
              <Input
                className="h-10 bg-white pl-9"
                placeholder="搜索 OpenID / 昵称"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") applySearch();
                }}
              />
            </label>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:flex xl:items-center">
              <CustomSelect
                value={status}
                onChange={(value) => {
                  setStatus(value as UserStatusFilter);
                  setPage(1);
                }}
                options={STATUS_OPTIONS}
                clearable={false}
                className="w-full sm:min-w-32 xl:w-36"
              />

              <div className="flex items-center gap-2 rounded-xl border border-[var(--color-border)] bg-white px-3">
                <input
                  type="date"
                  aria-label="开始日期"
                  className="h-[38px] min-w-0 bg-transparent text-xs text-[var(--color-text-secondary)] outline-none"
                  value={dateFrom}
                  max={dateTo || undefined}
                  onChange={(event) => {
                    setDateFrom(event.target.value);
                    setPage(1);
                  }}
                />
                <span className="text-[var(--color-text-hint)]">—</span>
                <input
                  type="date"
                  aria-label="结束日期"
                  className="h-[38px] min-w-0 bg-transparent text-xs text-[var(--color-text-secondary)] outline-none"
                  value={dateTo}
                  min={dateFrom || undefined}
                  onChange={(event) => {
                    setDateTo(event.target.value);
                    setPage(1);
                  }}
                />
              </div>
            </div>

            <div className="flex items-center gap-2 xl:ml-auto">
              <Button size="sm" onClick={applySearch} className="h-10 min-w-20 shadow-none">
                <Search className="h-4 w-4" />
                查询
              </Button>
              <Button size="sm" variant="secondary" onClick={resetFilters} className="h-10 px-3">
                重置
              </Button>
              <Button size="sm" variant="secondary" onClick={exportUsers} disabled={exporting} className="h-10 px-3">
                <Download className="h-4 w-4" />
                {exporting ? "导出中" : "导出"}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <section className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <MetricCard
          label="用户总数"
          value={totalUsers.data?.total ?? 0}
          helper="全部小程序用户"
          icon={<UsersRound className="h-4 w-4" />}
          loading={totalUsers.isLoading}
        />
        <MetricCard
          label="正常用户"
          value={activeUsers.data?.total ?? 0}
          helper="当前可正常使用"
          icon={<UserCheck className="h-4 w-4" />}
          tone="success"
          loading={activeUsers.isLoading}
        />
        <MetricCard
          label="封禁用户"
          value={bannedUsers.data?.total ?? 0}
          helper="当前限制使用"
          icon={<UserX className="h-4 w-4" />}
          tone="danger"
          loading={bannedUsers.isLoading}
        />
        <MetricCard
          label="今日新增"
          value={todayUsers.data?.total ?? 0}
          helper={`北京时间 ${today}`}
          icon={<UserPlus className="h-4 w-4" />}
          tone="neutral"
          loading={todayUsers.isLoading}
        />
      </section>

      {notice ? (
        <div
          role="status"
          className={cn(
            "flex items-center gap-2 rounded-xl border px-4 py-3 text-sm",
            notice.tone === "success"
              ? "border-[var(--color-success)]/25 bg-[var(--color-success-light)] text-[var(--color-success)]"
              : "border-[var(--color-danger)]/25 bg-[var(--color-danger-light)] text-[var(--color-danger)]",
          )}
        >
          {notice.tone === "success" ? <ShieldCheck className="h-4 w-4 shrink-0" /> : <UserX className="h-4 w-4 shrink-0" />}
          <span>{notice.text}</span>
        </div>
      ) : null}

      <Card className="overflow-visible rounded-2xl">
        <CardContent className="p-0">
          <div className="flex flex-col gap-3 border-b border-[var(--color-border-light)] px-4 py-3 sm:flex-row sm:items-center sm:justify-between lg:px-5">
            <div className="flex items-center gap-3">
              <CustomSelect
                value={batchAction}
                onChange={(value) => {
                  setBatchAction(value);
                  if (value === "ban" || value === "unban") openBatchAction(value);
                }}
                options={[
                  { value: "ban", label: "批量封禁" },
                  { value: "unban", label: "批量解封" },
                ]}
                placeholder={selectedIds.size ? `批量操作 · 已选 ${selectedIds.size}` : "批量操作"}
                clearable={false}
                disabled={!selectedIds.size || actionMutation.isPending}
                className="w-44"
              />
              {selectedIds.size ? <span className="text-xs text-[var(--color-text-hint)]">仅操作当前页选中用户</span> : null}
            </div>
            <Button variant="ghost" size="sm" onClick={refreshAll} disabled={users.isFetching} className="self-start sm:self-auto">
              <RefreshCw className={cn("h-4 w-4", users.isFetching && "animate-spin")} />
              刷新
            </Button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[940px] border-collapse text-sm">
              <thead className="bg-[rgba(232,240,245,0.55)] text-left">
                <tr className="border-b border-[var(--color-border-light)]">
                  <th className="w-12 px-4 py-3 lg:px-5">
                    <CustomCheckbox
                      checked={allPageSelected}
                      indeterminate={somePageSelected}
                      onCheckedChange={togglePageSelection}
                      aria-label="选择当前页全部用户"
                    />
                  </th>
                  {[
                    ["ID", "w-20"],
                    ["用户信息", "min-w-72"],
                    ["封禁原因", "min-w-48"],
                    ["状态", "w-28"],
                    ["操作", "w-36"],
                  ].map(([label, width]) => (
                    <th key={label} className={cn("px-4 py-3 text-[11px] font-semibold tracking-[0.08em] text-[var(--color-text-secondary)]", width)}>
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {users.isLoading ? (
                  Array.from({ length: Math.min(pageSize, 8) }, (_, index) => (
                    <tr key={index} className="border-b border-[var(--color-border-light)] last:border-b-0">
                      <td className="px-4 py-3 lg:px-5"><div className="h-[18px] w-[18px] animate-pulse rounded bg-[var(--color-border-light)]" /></td>
                      <td className="px-4 py-3"><div className="h-4 w-10 animate-pulse rounded bg-[var(--color-border-light)]" /></td>
                      <td className="px-4 py-3"><div className="h-10 w-56 animate-pulse rounded-lg bg-[var(--color-border-light)]" /></td>
                      <td className="px-4 py-3"><div className="h-4 w-32 animate-pulse rounded bg-[var(--color-border-light)]" /></td>
                      <td className="px-4 py-3"><div className="h-6 w-14 animate-pulse rounded-full bg-[var(--color-border-light)]" /></td>
                      <td className="px-4 py-3"><div className="h-8 w-20 animate-pulse rounded-lg bg-[var(--color-border-light)]" /></td>
                    </tr>
                  ))
                ) : users.isError ? (
                  <tr>
                    <td colSpan={6} className="px-5 py-16 text-center text-sm text-[var(--color-danger)]">用户列表加载失败，请点击刷新后重试。</td>
                  </tr>
                ) : currentItems.length ? (
                  currentItems.map((user) => (
                    <tr key={user.id} className="border-b border-[var(--color-border-light)] transition-colors last:border-b-0 hover:bg-[rgba(74,111,138,0.035)]">
                      <td className="px-4 py-3 lg:px-5">
                        <CustomCheckbox
                          checked={selectedIds.has(user.id)}
                          onCheckedChange={(checked) => toggleUserSelection(user.id, checked)}
                          aria-label={`选择用户 ${user.nickname || user.openid}`}
                        />
                      </td>
                      <td className="px-4 py-3 font-mono text-xs font-semibold text-[var(--color-text-secondary)] tabular-nums">{user.id}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <UserAvatar user={user} />
                          <div className="min-w-0">
                            <div className="truncate font-semibold text-[var(--ink)]">{user.nickname || "未设置昵称"}</div>
                            <div className="mt-0.5 max-w-[320px] truncate font-mono text-[11px] text-[var(--color-text-hint)]">{user.openid}</div>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {user.banned_reason ? (
                          <span className="line-clamp-2 max-w-sm text-xs leading-5 text-[var(--color-text-secondary)]" title={user.banned_reason}>{user.banned_reason}</span>
                        ) : (
                          <span className="text-[var(--color-text-hint)]">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge tone={user.is_banned ? "danger" : "success"}>{user.is_banned ? "已封禁" : "正常"}</StatusBadge>
                      </td>
                      <td className="px-4 py-3">
                        <Button
                          variant={user.is_banned ? "secondary" : "ghost"}
                          size="sm"
                          disabled={actionMutation.isPending}
                          onClick={() => openSingleAction(user)}
                          className={cn(
                            "h-8 min-w-20 rounded-lg px-2.5 text-xs shadow-none",
                            !user.is_banned && "border border-[var(--color-danger)]/20 text-[var(--color-danger)] hover:border-[var(--color-danger)]/35 hover:bg-[var(--color-danger-light)] hover:text-[var(--color-danger)]",
                          )}
                        >
                          {user.is_banned ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Ban className="h-3.5 w-3.5" />}
                          {user.is_banned ? "解封" : "封禁"}
                        </Button>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={6} className="px-5 py-16 text-center">
                      <UsersRound className="mx-auto h-8 w-8 text-[var(--color-text-hint)]" />
                      <p className="mt-3 text-sm font-medium text-[var(--color-text-secondary)]">暂无符合条件的用户</p>
                      <p className="mt-1 text-xs text-[var(--color-text-hint)]">可调整搜索词、状态或日期范围后重新查询。</p>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="flex flex-col gap-3 border-t border-[var(--color-border-light)] px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between lg:px-5">
            <div className="flex items-center gap-3 text-xs text-[var(--color-text-secondary)]">
              <span>共 <strong className="font-semibold text-[var(--ink)]">{(users.data?.total ?? 0).toLocaleString("zh-CN")}</strong> 条</span>
              <CustomSelect
                value={String(pageSize)}
                onChange={(value) => {
                  setPageSize(Number(value));
                  setPage(1);
                }}
                options={PAGE_SIZE_OPTIONS}
                clearable={false}
                className="w-28"
              />
            </div>

            <nav className="flex items-center gap-1" aria-label="用户列表分页">
              <button
                type="button"
                aria-label="上一页"
                disabled={page <= 1}
                onClick={() => setPage((value) => Math.max(1, value - 1))}
                className="grid h-8 w-8 place-items-center rounded-lg border border-transparent text-sm text-[var(--color-text-secondary)] transition hover:border-[var(--color-border)] hover:bg-white disabled:pointer-events-none disabled:opacity-30"
              >
                ‹
              </button>
              {pagination.map((item) =>
                typeof item === "number" ? (
                  <button
                    type="button"
                    key={item}
                    aria-current={page === item ? "page" : undefined}
                    onClick={() => setPage(item)}
                    className={cn(
                      "grid h-8 min-w-8 place-items-center rounded-lg border px-2 text-xs font-semibold transition",
                      page === item
                        ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-white"
                        : "border-transparent text-[var(--color-text-secondary)] hover:border-[var(--color-border)] hover:bg-white",
                    )}
                  >
                    {item}
                  </button>
                ) : (
                  <span key={item} className="grid h-8 w-7 place-items-center text-xs text-[var(--color-text-hint)]">…</span>
                ),
              )}
              <button
                type="button"
                aria-label="下一页"
                disabled={page >= totalPages}
                onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
                className="grid h-8 w-8 place-items-center rounded-lg border border-transparent text-sm text-[var(--color-text-secondary)] transition hover:border-[var(--color-border)] hover:bg-white disabled:pointer-events-none disabled:opacity-30"
              >
                ›
              </button>
            </nav>
          </div>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={confirmState !== null}
        title={confirmState?.action === "unban" ? "确认解封用户" : "确认封禁用户"}
        description={
          confirmState
            ? `即将${confirmState.action === "unban" ? "解封" : "封禁"} ${confirmState.label}${confirmState.userIds.length > 1 ? `（共 ${confirmState.userIds.length} 位）` : ""}。`
            : undefined
        }
        confirmText={confirmState?.action === "unban" ? "确认解封" : "确认封禁"}
        danger={confirmState?.action === "ban"}
        loading={actionMutation.isPending}
        onCancel={() => {
          setConfirmState(null);
          setBatchAction("");
        }}
        onConfirm={() => {
          if (!confirmState) return;
          actionMutation.mutate(confirmState);
        }}
      >
        {confirmState?.action === "ban" ? (
          <label className="block">
            <span className="mb-2 block text-xs font-semibold text-[var(--color-text-secondary)]">封禁原因</span>
            <textarea
              className="min-h-24 w-full resize-y rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3 text-sm text-[var(--color-text-primary)] outline-none transition placeholder:text-[var(--color-text-hint)] focus:border-[var(--color-primary)] focus:bg-white focus:ring-4 focus:ring-[rgba(91,123,154,0.14)]"
              placeholder="请输入封禁原因"
              value={banReason}
              maxLength={256}
              onChange={(event) => setBanReason(event.target.value)}
            />
            <span className="mt-1.5 block text-right text-[10px] text-[var(--color-text-hint)]">{banReason.length}/256</span>
          </label>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}

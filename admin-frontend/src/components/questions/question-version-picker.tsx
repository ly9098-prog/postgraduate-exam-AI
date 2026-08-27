"use client";

import { createPortal } from "react-dom";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  CalendarDays,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Search,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { QuestionVersion } from "@/lib/api/types";

export type QuestionVersionSelection = "current" | number;

type VersionGroup = {
  label: "今天" | "本周" | "上周" | "更早";
  items: QuestionVersion[];
};

type CalendarCell = {
  key: string;
  day: number;
  inMonth: boolean;
};

function pad(value: number) {
  return String(value).padStart(2, "0");
}

function formatVersionDate(value?: string) {
  if (!value) return "时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function localDateKey(value?: string | Date) {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function formatDateFilterLabel(key: string) {
  const [year, month, day] = key.split("-").map(Number);
  if (!year || !month || !day) return key;
  const now = new Date();
  return year === now.getFullYear()
    ? `${pad(month)}月${pad(day)}日`
    : `${year}年${pad(month)}月${pad(day)}日`;
}

function startOfLocalDay(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function startOfLocalWeek(date: Date) {
  const dayStart = startOfLocalDay(date);
  const mondayOffset = (dayStart.getDay() + 6) % 7;
  dayStart.setDate(dayStart.getDate() - mondayOffset);
  return dayStart;
}

function startOfMonth(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

function addMonths(date: Date, count: number) {
  return new Date(date.getFullYear(), date.getMonth() + count, 1);
}

function buildCalendarCells(month: Date): CalendarCell[] {
  const first = startOfMonth(month);
  const mondayOffset = (first.getDay() + 6) % 7;
  const gridStart = new Date(first);
  gridStart.setDate(first.getDate() - mondayOffset);

  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(gridStart);
    date.setDate(gridStart.getDate() + index);
    return {
      key: localDateKey(date)!,
      day: date.getDate(),
      inMonth: date.getMonth() === month.getMonth() && date.getFullYear() === month.getFullYear(),
    };
  });
}

function groupVersionsByTime(versions: QuestionVersion[]): VersionGroup[] {
  const now = new Date();
  const todayStart = startOfLocalDay(now).getTime();
  const thisWeekStart = startOfLocalWeek(now).getTime();
  const lastWeekStartDate = new Date(thisWeekStart);
  lastWeekStartDate.setDate(lastWeekStartDate.getDate() - 7);
  const lastWeekStart = lastWeekStartDate.getTime();

  const buckets: Record<VersionGroup["label"], QuestionVersion[]> = {
    今天: [],
    本周: [],
    上周: [],
    更早: [],
  };

  versions.forEach((version) => {
    const timestamp = version.created_at ? new Date(version.created_at).getTime() : Number.NaN;
    if (!Number.isFinite(timestamp) || timestamp < lastWeekStart) {
      buckets.更早.push(version);
    } else if (timestamp >= todayStart) {
      buckets.今天.push(version);
    } else if (timestamp >= thisWeekStart) {
      buckets.本周.push(version);
    } else {
      buckets.上周.push(version);
    }
  });

  return (["今天", "本周", "上周", "更早"] as const)
    .map((label) => ({ label, items: buckets[label] }))
    .filter((group) => group.items.length > 0);
}

function versionEditorName(version: QuestionVersion) {
  return version.edited_by_name?.trim() || `管理员 #${version.edited_by}`;
}

export function QuestionVersionPicker({
  value,
  onChange,
  versions,
  disabledValue,
  disabled = false,
  loading = false,
  className,
}: {
  value: QuestionVersionSelection | null;
  onChange: (value: QuestionVersionSelection) => void;
  versions: QuestionVersion[];
  disabledValue?: QuestionVersionSelection | null;
  disabled?: boolean;
  loading?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [dateFilter, setDateFilter] = useState<string | null>(null);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [calendarMonth, setCalendarMonth] = useState(() => startOfMonth(new Date()));
  const triggerRef = useRef<HTMLDivElement | null>(null);
  const dropdownRef = useRef<HTMLDivElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const [position, setPosition] = useState<{
    left: number;
    width: number;
    maxHeight: number;
    top?: number;
    bottom?: number;
  } | null>(null);

  const selectedVersion =
    typeof value === "number"
      ? versions.find((version) => version.version === value)
      : undefined;

  const versionDateCounts = useMemo(() => {
    const counts = new Map<string, number>();
    versions.forEach((version) => {
      const key = localDateKey(version.created_at);
      if (!key) return;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    });
    return counts;
  }, [versions]);

  const filteredVersions = useMemo(() => {
    const keyword = search.trim().toLowerCase().replace(/^v/, "");
    return versions.filter((version) => {
      if (dateFilter && localDateKey(version.created_at) !== dateFilter) return false;
      if (!keyword) return true;
      const haystack = [
        String(version.version),
        `v${version.version}`,
        version.edit_reason ?? "",
        version.edited_by_name ?? "",
        String(version.edited_by),
        formatVersionDate(version.created_at),
        localDateKey(version.created_at) ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(keyword) || haystack.includes(`v${keyword}`);
    });
  }, [dateFilter, search, versions]);

  const groups = useMemo(
    () => groupVersionsByTime(filteredVersions),
    [filteredVersions],
  );

  const currentMatchesSearch = useMemo(() => {
    if (dateFilter) return false;
    const keyword = search.trim().toLowerCase();
    return !keyword || "当前版本 当前题目 current".includes(keyword);
  }, [dateFilter, search]);

  const close = useCallback(() => {
    setOpen(false);
    setSearch("");
    setDateFilter(null);
    setCalendarOpen(false);
  }, []);

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const viewportPadding = 12;
    const desiredWidth = Math.max(rect.width, 410);
    const width = Math.min(desiredWidth, window.innerWidth - viewportPadding * 2);
    const left = Math.min(
      Math.max(viewportPadding, rect.left),
      Math.max(viewportPadding, window.innerWidth - width - viewportPadding),
    );
    const spaceBelow = window.innerHeight - rect.bottom;
    const spaceAbove = rect.top;
    const openUp = spaceBelow < 390 && spaceAbove > spaceBelow;
    const availableHeight = Math.max(
      220,
      (openUp ? spaceAbove : spaceBelow) - viewportPadding - 8,
    );
    const maxHeight = Math.min(560, availableHeight);
    setPosition(
      openUp
        ? {
            left,
            width,
            maxHeight,
            bottom: window.innerHeight - rect.top + 8,
          }
        : { left, width, maxHeight, top: rect.bottom + 8 },
    );
  }, []);

  useEffect(() => {
    if (!open) return;
    updatePosition();
    const handleViewportChange = () => updatePosition();
    window.addEventListener("resize", handleViewportChange);
    window.addEventListener("scroll", handleViewportChange, true);
    return () => {
      window.removeEventListener("resize", handleViewportChange);
      window.removeEventListener("scroll", handleViewportChange, true);
    };
  }, [open, updatePosition]);

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (
        triggerRef.current?.contains(target) ||
        dropdownRef.current?.contains(target)
      ) {
        return;
      }
      close();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (calendarOpen) {
          setCalendarOpen(false);
          return;
        }
        close();
        triggerRef.current?.querySelector("button")?.focus();
      }
    };
    document.addEventListener("pointerdown", handlePointerDown, { capture: true });
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown, { capture: true });
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [calendarOpen, close, open]);

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => searchRef.current?.focus(), 30);
    return () => window.clearTimeout(timer);
  }, [open]);

  useEffect(() => {
    if (!calendarOpen) return;
    if (dateFilter) {
      const [year, month] = dateFilter.split("-").map(Number);
      if (year && month) setCalendarMonth(new Date(year, month - 1, 1));
      return;
    }
    const referenceDate = selectedVersion?.created_at
      ? new Date(selectedVersion.created_at)
      : versions[0]?.created_at
        ? new Date(versions[0].created_at)
        : new Date();
    if (!Number.isNaN(referenceDate.getTime())) {
      setCalendarMonth(startOfMonth(referenceDate));
    }
  }, [calendarOpen, dateFilter, selectedVersion?.created_at, versions]);

  const choose = (nextValue: QuestionVersionSelection) => {
    if (disabledValue === nextValue) return;
    onChange(nextValue);
    close();
  };

  const calendarCells = useMemo(
    () => buildCalendarCells(calendarMonth),
    [calendarMonth],
  );

  return (
    <div ref={triggerRef} className={cn("relative", className)}>
      <button
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-haspopup="dialog"
        disabled={disabled || loading}
        onClick={() => {
          if (disabled || loading) return;
          setOpen((current) => !current);
        }}
        className={cn(
          "flex min-h-14 w-full items-center gap-3 rounded-xl border bg-white px-3 py-2.5 text-left outline-none transition-all duration-200",
          open
            ? "border-[var(--color-primary)] ring-4 ring-[rgba(91,123,154,0.12)]"
            : "border-slate-200 hover:-translate-y-px hover:border-slate-300 hover:bg-slate-50/60 hover:shadow-sm",
          "disabled:cursor-not-allowed disabled:opacity-60",
        )}
      >
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-slate-800">
            {loading
              ? "正在加载版本…"
              : value === null
                ? "请选择版本"
                : value === "current"
                  ? "当前版本"
                  : `v${value}`}
          </p>
          <p className="mt-0.5 truncate text-[11px] text-slate-400">
            {value === null
              ? "选择一个版本开始对比"
              : value === "current"
                ? "当前题目数据"
                : selectedVersion
                  ? `${formatVersionDate(selectedVersion.created_at)} · ${versionEditorName(selectedVersion)}`
                  : "历史版本"}
          </p>
        </div>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-slate-400 transition-transform duration-200",
            open && "rotate-180",
          )}
        />
      </button>

      {open && position && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={dropdownRef}
              role="dialog"
              aria-label="选择题目版本"
              className="z-[120] flex animate-fade-in flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl shadow-slate-900/10"
              style={{
                position: "fixed",
                left: position.left,
                width: position.width,
                maxHeight: position.maxHeight,
                top: position.top,
                bottom: position.bottom,
              }}
            >
              <div className="shrink-0 border-b border-slate-100 bg-white p-3">
                <div className="flex h-10 items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 transition-all focus-within:border-[var(--color-primary)] focus-within:bg-white focus-within:ring-4 focus-within:ring-[rgba(91,123,154,0.10)]">
                  <Search className="h-4 w-4 shrink-0 text-slate-400" />
                  <input
                    ref={searchRef}
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="搜索版本号、修改人或修改原因"
                    className="min-w-0 flex-1 bg-transparent text-sm text-slate-700 outline-none placeholder:text-slate-400"
                  />
                  {search ? (
                    <button
                      type="button"
                      onClick={() => setSearch("")}
                      className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-slate-400 transition hover:bg-slate-200/70 hover:text-slate-600"
                      aria-label="清除搜索"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  ) : null}
                </div>

                <div className="mt-2 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setCalendarOpen((current) => !current)}
                    className={cn(
                      "inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-[11px] font-medium transition",
                      dateFilter || calendarOpen
                        ? "border-[var(--color-primary)] bg-[rgba(91,123,154,0.08)] text-[var(--color-primary)]"
                        : "border-slate-200 bg-white text-slate-500 hover:border-slate-300 hover:bg-slate-50",
                    )}
                    aria-expanded={calendarOpen}
                  >
                    <CalendarDays className="h-3.5 w-3.5" />
                    {dateFilter ? formatDateFilterLabel(dateFilter) : "按日期筛选"}
                    <ChevronDown
                      className={cn(
                        "h-3 w-3 transition-transform duration-200",
                        calendarOpen && "rotate-180",
                      )}
                    />
                  </button>
                  {dateFilter ? (
                    <button
                      type="button"
                      onClick={() => setDateFilter(null)}
                      className="inline-flex h-8 items-center gap-1 rounded-lg px-2 text-[11px] text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
                    >
                      <X className="h-3 w-3" />
                      清除日期
                    </button>
                  ) : null}
                  <span className="ml-auto text-[10px] tabular-nums text-slate-400">
                    {filteredVersions.length} 个历史版本
                  </span>
                </div>

                {calendarOpen ? (
                  <MiniVersionCalendar
                    month={calendarMonth}
                    cells={calendarCells}
                    selectedDate={dateFilter}
                    versionDateCounts={versionDateCounts}
                    onPreviousMonth={() => setCalendarMonth((current) => addMonths(current, -1))}
                    onNextMonth={() => setCalendarMonth((current) => addMonths(current, 1))}
                    onSelect={(key) => {
                      setDateFilter(key);
                      setCalendarOpen(false);
                    }}
                  />
                ) : null}
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2 [scrollbar-gutter:stable]">
                {currentMatchesSearch ? (
                  <div className="mb-1">
                    <p className="px-2 py-1.5 text-[10px] font-semibold tracking-wide text-slate-400">
                      当前
                    </p>
                    <VersionOption
                      active={value === "current"}
                      disabled={disabledValue === "current"}
                      title="当前版本"
                      meta="当前题目数据"
                      reason={disabledValue === "current" ? "另一侧已选择" : undefined}
                      onClick={() => choose("current")}
                    />
                  </div>
                ) : null}

                {groups.map((group) => (
                  <div key={group.label} className="mb-1 last:mb-0">
                    <div className="flex items-center justify-between px-2 py-1.5">
                      <p className="text-[10px] font-semibold tracking-wide text-slate-400">
                        {group.label}
                      </p>
                      <span className="text-[9px] tabular-nums text-slate-300">
                        {group.items.length}
                      </span>
                    </div>
                    <div className="space-y-0.5">
                      {group.items.map((version) => {
                        const isDisabled = disabledValue === version.version;
                        return (
                          <VersionOption
                            key={version.id}
                            active={value === version.version}
                            disabled={isDisabled}
                            title={`v${version.version}`}
                            meta={`${formatVersionDate(version.created_at)} · ${versionEditorName(version)}`}
                            reason={
                              isDisabled
                                ? "另一侧已选择"
                                : version.edit_reason?.trim() || "未填写修改原因"
                            }
                            onClick={() => choose(version.version)}
                          />
                        );
                      })}
                    </div>
                  </div>
                ))}

                {!currentMatchesSearch && groups.length === 0 ? (
                  <div className="px-4 py-10 text-center animate-fade-in">
                    <p className="text-sm font-medium text-slate-500">没有匹配的版本</p>
                    <p className="mt-1 text-xs text-slate-400">
                      可调整日期，或搜索 v35、修改人姓名、修改原因
                    </p>
                    {dateFilter ? (
                      <button
                        type="button"
                        onClick={() => setDateFilter(null)}
                        className="mt-3 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[11px] font-medium text-slate-500 transition hover:border-slate-300 hover:bg-slate-50"
                      >
                        清除日期筛选
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}

function MiniVersionCalendar({
  month,
  cells,
  selectedDate,
  versionDateCounts,
  onPreviousMonth,
  onNextMonth,
  onSelect,
}: {
  month: Date;
  cells: CalendarCell[];
  selectedDate: string | null;
  versionDateCounts: Map<string, number>;
  onPreviousMonth: () => void;
  onNextMonth: () => void;
  onSelect: (key: string) => void;
}) {
  const todayKey = localDateKey(new Date());
  return (
    <div className="mt-2 rounded-xl border border-slate-200 bg-slate-50/70 p-2.5 animate-fade-in">
      <div className="mb-2 flex items-center justify-between">
        <button
          type="button"
          onClick={onPreviousMonth}
          className="grid h-7 w-7 place-items-center rounded-lg text-slate-400 transition hover:bg-white hover:text-slate-700 hover:shadow-sm"
          aria-label="上个月"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <p className="text-[11px] font-semibold text-slate-600">
          {month.getFullYear()} 年 {month.getMonth() + 1} 月
        </p>
        <button
          type="button"
          onClick={onNextMonth}
          className="grid h-7 w-7 place-items-center rounded-lg text-slate-400 transition hover:bg-white hover:text-slate-700 hover:shadow-sm"
          aria-label="下个月"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="grid grid-cols-7 gap-1 px-0.5 text-center text-[9px] font-medium text-slate-400">
        {['一', '二', '三', '四', '五', '六', '日'].map((weekday) => (
          <span key={weekday} className="py-1">{weekday}</span>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {cells.map((cell) => {
          const count = versionDateCounts.get(cell.key) ?? 0;
          const active = selectedDate === cell.key;
          const isToday = todayKey === cell.key;
          const disabled = !cell.inMonth || count === 0;
          return (
            <button
              type="button"
              key={cell.key}
              disabled={disabled}
              onClick={() => onSelect(cell.key)}
              className={cn(
                "relative grid h-8 place-items-center rounded-lg text-[10px] tabular-nums transition",
                active
                  ? "bg-[var(--color-primary)] font-semibold text-white shadow-sm"
                  : disabled
                    ? "cursor-default text-slate-300"
                    : "bg-white text-slate-600 hover:-translate-y-px hover:bg-slate-100 hover:shadow-sm",
                isToday && !active && !disabled && "ring-1 ring-inset ring-[var(--color-primary)]",
              )}
              aria-label={`${cell.key}，${count} 个版本`}
            >
              <span>{cell.day}</span>
              {count > 0 && !active ? (
                <span className="absolute bottom-0.5 h-1 w-1 rounded-full bg-[var(--color-primary)]" />
              ) : null}
            </button>
          );
        })}
      </div>
      <p className="mt-2 px-1 text-[9px] leading-4 text-slate-400">
        仅可选择存在历史版本的日期，圆点表示当天有修改记录。
      </p>
    </div>
  );
}

function VersionOption({
  active,
  disabled,
  title,
  meta,
  reason,
  onClick,
}: {
  active: boolean;
  disabled: boolean;
  title: string;
  meta: string;
  reason?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "group flex w-full items-start gap-3 rounded-xl px-2.5 py-2.5 text-left transition-all duration-150",
        active
          ? "bg-slate-100 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.12)]"
          : "hover:translate-x-0.5 hover:bg-slate-50",
        disabled && "cursor-not-allowed opacity-45",
      )}
    >
      <span
        className={cn(
          "mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-md border transition-all duration-150",
          active
            ? "scale-100 border-[var(--color-primary)] bg-[var(--color-primary)] text-white"
            : "border-slate-200 bg-white text-transparent group-hover:border-slate-300",
        )}
      >
        <Check className="h-3.5 w-3.5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center justify-between gap-3">
          <span className="shrink-0 text-sm font-semibold text-slate-700">{title}</span>
          <span className="truncate text-[10px] text-slate-400">{meta}</span>
        </span>
        {reason ? (
          <span className="mt-1 block truncate text-[11px] text-slate-500">
            {reason}
          </span>
        ) : null}
      </span>
    </button>
  );
}

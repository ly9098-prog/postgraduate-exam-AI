import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isValidElement, type ReactElement } from "react";
import DashboardPage from "./page";
import { DashboardTrendChart } from "./components/dashboard-trend-chart";

type Query = {
  queryKey: unknown[]; queryFn: () => Promise<unknown>;
  enabled?: boolean; staleTime?: number; retry?: boolean | number;
};
type Element = ReactElement<Record<string, unknown>>;
const h = vi.hoisted(() => ({
  states: [] as unknown[], index: 0, setters: [] as ReturnType<typeof vi.fn>[],
  queries: [] as Query[], refetches: [] as ReturnType<typeof vi.fn>[],
  authenticated: true, bootstrapping: false,
  request: vi.fn(), toQuery: vi.fn((query: Record<string, unknown>) => {
    void query;
    return "?fixture";
  }),
}));
vi.mock("react", async (original) => ({
  ...await original<typeof import("react")>(),
  useMemo: (compute: () => unknown) => compute(),
  useState: (initial: unknown) => {
    const index = h.index++;
    const setter = vi.fn();
    h.setters.push(setter);
    return [index in h.states ? h.states[index] : initial, setter];
  },
}));
vi.mock("@tanstack/react-query", () => ({
  useQuery: (query: Query) => {
    h.queries.push(query);
    const refetch = vi.fn().mockResolvedValue(undefined);
    h.refetches.push(refetch);
    return { data: undefined, isLoading: false, isError: false, refetch };
  },
}));
vi.mock("@/lib/auth/auth-store", () => ({
  useAuthStore: (select: (state: unknown) => unknown) => select({
    isAuthenticated: h.authenticated, isBootstrapping: h.bootstrapping,
  }),
}));
vi.mock("@/lib/api/client", () => ({ apiRequest: h.request, toQuery: h.toQuery }));

function find(node: unknown, predicate: (element: Element) => boolean): Element | undefined {
  if (Array.isArray(node)) return node.map((item) => find(item, predicate)).find(Boolean);
  if (!isValidElement<Record<string, unknown>>(node)) return;
  if (predicate(node)) return node;
  return find(node.props.children, predicate);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  // UTC October 29 is already October 30 in the product timezone.
  vi.setSystemTime(new Date("2026-10-29T18:00:00Z"));
  h.states = []; h.index = 0; h.setters = []; h.queries = []; h.refetches = [];
  h.authenticated = true; h.bootstrapping = false;
  h.request.mockReset().mockResolvedValue({});
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("dashboard page request ownership", () => {
  it.each([
    { authenticated: false, bootstrapping: false },
    { authenticated: true, bootstrapping: true },
    { authenticated: false, bootstrapping: true },
  ])("gates all six requests during authentication transition (%j)", (state) => {
    h.authenticated = state.authenticated;
    h.bootstrapping = state.bootstrapping;
    DashboardPage();
    expect(h.queries).toHaveLength(6);
    expect(h.queries.every((query) => query.enabled === false)).toBe(true);
    expect(h.request).not.toHaveBeenCalled();
  });

  it("keeps the five owned contracts and shared task diagnostic read separate", async () => {
    DashboardPage();
    expect(h.queries.every((query) => query.enabled === true)).toBe(true);
    await Promise.all(h.queries.map((query) => query.queryFn()));
    expect(h.request.mock.calls).toEqual([
      ["/dashboard/overview"], ["/dashboard/daily?fixture"],
      ["/dashboard/questions-stats"], ["/health/ready"],
      ["/dashboard/ai-stats?days=7"], ["/tasks/diagnostics"],
    ]);
    expect(h.queries.map((query) => query.staleTime)).toEqual([
      30_000, 30_000, 60_000, 30_000, 60_000, 30_000,
    ]);
    expect(h.queries.slice(3).map((query) => query.retry)).toEqual([1, false, false]);
  });

  it.each([
    { period: "7d", from: "2026-10-24" },
    { period: "30d", from: "2026-10-01" },
  ])("uses an inclusive Shanghai date window for $period", async ({ period, from }) => {
    h.states[0] = period;
    DashboardPage();
    await h.queries[1].queryFn();
    expect(h.toQuery).toHaveBeenCalledExactlyOnceWith({ from, to: "2026-10-30" });
    expect(h.queries[1].queryKey).toEqual(["dashboard", "daily", { from, to: "2026-10-30" }]);
  });

  it("passes the current period and period setter to the existing chart component", () => {
    h.states[0] = "30d";
    const chart = find(DashboardPage(), (element) => element.type === DashboardTrendChart)!;
    expect(chart.props.period).toBe("30d");
    const onPeriodChange = chart.props.onPeriodChange as (value: string) => void;
    onPeriodChange("7d");
    expect(h.setters[0]).toHaveBeenCalledWith("7d");
  });

  it("waits for every refresh despite one rejection and clears the busy state last", async () => {
    const root = DashboardPage();
    let release!: () => void;
    h.refetches[0].mockReturnValue(new Promise<void>((resolve) => { release = resolve; }));
    h.refetches[2].mockRejectedValue(new Error("synthetic offline"));
    const button = find(root, (element) => element.type === "button")!;
    (button.props.onClick as () => void)();
    expect(h.refetches.map((refetch) => refetch.mock.calls.length)).toEqual([1, 1, 1, 1, 1, 1]);
    await Promise.resolve();
    expect(h.setters[1].mock.calls).toEqual([[true]]);
    release();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    expect(h.setters[1].mock.calls).toEqual([[true], [false]]);
  });

  it("disables manual refresh while an earlier refresh is busy", () => {
    h.states[1] = true;
    const root = DashboardPage();
    const button = find(root, (element) => element.type === "button")!;
    expect(button.props.disabled).toBe(true);
    expect(find(root, (element) => element.props["aria-label"] === "正在刷新仪表盘数据")).toBeDefined();
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AISettingsPage from "./page";
import ExperimentsPage from "../recommendation/experiments/page";
import MetricsPage from "../recommendation/metrics/page";
import ReportsPage from "../recommendation/reports/page";
import StrategiesPage from "../recommendation/strategies/page";
import SystemTasksPage from "../system/tasks/page";
import { VectorConfigSection } from "./components/vector-config-section";

type Query = {
  queryKey: unknown[]; queryFn: () => Promise<unknown>;
  enabled?: boolean; refetchInterval?: number; retry?: boolean | number;
};
type Mutation = {
  mutationFn: (input?: never) => Promise<unknown>;
  onSuccess?: (result: never) => unknown; onError?: (error: Error) => unknown;
};
const h = vi.hoisted(() => ({
  states: [] as unknown[], index: 0, setters: [] as ReturnType<typeof vi.fn>[],
  queries: [] as Query[], mutations: [] as Mutation[],
  data: {} as Record<string, unknown>, refetches: [] as ReturnType<typeof vi.fn>[],
  request: vi.fn(), toQuery: vi.fn((query: Record<string, unknown>) => {
    void query;
    return "?fixture";
  }),
  invalidate: vi.fn(), setData: vi.fn(),
}));
vi.mock("react", async (original) => ({
  ...await original<typeof import("react")>(),
  useMemo: (compute: () => unknown) => compute(),
  useCallback: (callback: unknown) => callback,
  useRef: (current: unknown) => ({ current }),
  useEffect: () => undefined,
  useState: (initial: unknown) => {
    const index = h.index++;
    const setter = vi.fn();
    h.setters.push(setter);
    return [index in h.states ? h.states[index] : initial, setter];
  },
}));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: h.invalidate, setQueryData: h.setData }),
  useQuery: (query: Query) => {
    h.queries.push(query);
    const refetch = vi.fn().mockResolvedValue(undefined);
    h.refetches.push(refetch);
    return {
      data: h.data[JSON.stringify(query.queryKey)],
      isLoading: false, isFetching: false, refetch,
    };
  },
  useMutation: (mutation: Mutation) => {
    h.mutations.push(mutation);
    return { mutate: vi.fn(), isPending: false };
  },
}));
vi.mock("@/lib/auth/auth-store", () => ({
  useAuthStore: (select: (s: unknown) => unknown) =>
    select({ role: { name: "super_admin" }, permissions: ["question:write"] }),
}));
vi.mock("@/lib/api/client", () => ({ apiRequest: h.request, toQuery: h.toQuery }));

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-30T04:00:00Z"));
  h.states = []; h.index = 0; h.setters = [];
  h.queries = []; h.mutations = []; h.data = {}; h.refetches = [];
  h.request.mockReset().mockResolvedValue({});
  vi.stubGlobal("document", {
    createElement: () => ({ remove: vi.fn() }),
    body: { appendChild: vi.fn() },
  });
});

describe("AI configuration request ownership", () => {
  it("keeps settings hydration and 30-day statistics separate from model registration", async () => {
    AISettingsPage();
    const settings = { ai_parse_enabled: false, monthly_call_limit: 42 };
    h.request.mockResolvedValue(settings);
    await h.queries[0].queryFn();
    expect(h.setters[0]).toHaveBeenCalledWith("42");
    expect(h.setters[1]).toHaveBeenCalledWith(false);
    await h.queries[1].queryFn();
    expect(h.toQuery).toHaveBeenCalledWith({ days: 30 });
    await h.queries[2].queryFn();
    await h.queries[3].queryFn();
    expect(h.request.mock.calls.map(([url]) => url)).toEqual([
      "/ai-settings", "/ai-settings/stats?fixture", "/ai-configs", "/ai-models",
    ]);
  });

  it("publishes the server-confirmed settings into cache after PATCH", async () => {
    AISettingsPage();
    const result = { ai_parse_enabled: false, monthly_call_limit: 0 };
    await h.mutations[0].mutationFn(result as never);
    expect(h.request).toHaveBeenCalledWith("/ai-settings", {
      method: "PATCH", body: JSON.stringify(result),
    });
    h.mutations[0].onSuccess!(result as never);
    expect(h.setData).toHaveBeenCalledWith(["ai-settings"], result);
    expect(h.setters[2]).toHaveBeenCalledWith(false);
  });

  it("tests the selected embedding ID and draft dimensions without sending provider credentials", async () => {
    h.states = [{ embedding_model_config_id: 7, embedding_dim: 256, embedding_timeout: 9 }];
    VectorConfigSection();
    await h.mutations[1].mutationFn();
    expect(h.request).toHaveBeenCalledWith("/vector-config/test-embedding", {
      method: "POST", body: JSON.stringify({ model_config_id: 7, dim: 256, timeout: 9 }),
    });
  });

  it("rejects an absent embedding selection before issuing a connection test", () => {
    VectorConfigSection();
    expect(() => h.mutations[1].mutationFn()).toThrow();
    expect(h.request).not.toHaveBeenCalled();
  });

  it("clears vector drafts and stale test results only on successful save", async () => {
    VectorConfigSection();
    const result = { vector_enabled: false };
    await h.mutations[0].mutationFn(result as never);
    expect(h.request).toHaveBeenCalledWith("/vector-config", {
      method: "PATCH", body: JSON.stringify(result),
    });
    h.mutations[0].onSuccess!(result as never);
    expect(h.setData).toHaveBeenCalledWith(["vector-config"], result);
    expect(h.setters[0]).toHaveBeenCalledWith({});
    expect(h.setters[1]).toHaveBeenCalledWith(null);
  });
});

describe("recommendation page request ownership", () => {
  it("gates comparison reads on a selected experiment and preserves the date window", async () => {
    ExperimentsPage();
    expect(h.queries[1].enabled).toBe(false);
    h.index = 0; h.queries = []; h.states[4] = 19;
    ExperimentsPage();
    expect(h.queries[1].enabled).toBe(true);
    await h.queries[1].queryFn();
    expect(h.request).toHaveBeenCalledWith("/recommendation/experiments/19/compare?fixture");
    expect(h.toQuery).toHaveBeenCalledWith({
      date_from: "2026-09-30", date_to: "2026-10-30",
    });
  });

  it("keeps status PATCH, safety POST and creation POST distinct", async () => {
    ExperimentsPage();
    await h.mutations[0].mutationFn({ id: 19, status: "paused" } as never);
    await h.mutations[1].mutationFn(19 as never);
    const payload = { name: "synthetic", scene: "practice_smart", variants: [] };
    await h.mutations[2].mutationFn(payload as never);
    expect(h.request.mock.calls).toEqual([
      ["/recommendation/experiments/19/status", { method: "PATCH", body: '{"status":"paused"}' }],
      ["/recommendation/experiments/19/safety-check?fixture", { method: "POST" }],
      ["/recommendation/experiments", { method: "POST", body: JSON.stringify(payload) }],
    ]);
    expect(h.toQuery).toHaveBeenCalledExactlyOnceWith({
      date_from: "2026-09-30", date_to: "2026-10-30",
    });
  });

  it("resets only creation drafts after success and invalidates experiment consumers", () => {
    ExperimentsPage();
    h.mutations[2].onSuccess!({} as never);
    expect(h.invalidate).toHaveBeenCalledWith({ queryKey: ["recommendation", "experiments"] });
    expect(h.setters[0]).toHaveBeenCalledWith(false);
    expect(h.setters[1]).toHaveBeenCalledWith("");
    expect(h.setters[3]).toHaveBeenCalledWith("");
    expect(h.setters[4]).not.toHaveBeenCalled();
  });

  it("uses the selected range for reads/backfill and leaves aggregate date to the server", async () => {
    h.states = ["2026-10-01", "2026-10-30"];
    MetricsPage();
    await h.queries[0].queryFn();
    await h.mutations[0].mutationFn();
    await h.mutations[1].mutationFn();
    expect(h.toQuery).toHaveBeenCalledWith({ date_from: h.states[0], date_to: h.states[1] });
    expect(h.request.mock.calls).toEqual([
      ["/recommendation/metrics?fixture"],
      ["/recommendation/metrics/aggregate", { method: "POST", body: "{}" }],
      ["/recommendation/metrics/backfill", {
        method: "POST", body: '{"date_from":"2026-10-01","date_to":"2026-10-30"}',
      }],
    ]);
  });

  it("keeps all three quality reports as independent read requests", async () => {
    ReportsPage();
    await Promise.all(h.queries.map((query) => query.queryFn()));
    expect(h.request.mock.calls.map(([url]) => url)).toEqual([
      "/recommendation/health-report", "/recommendation/quality-report",
      "/recommendation/knowledge-quality-report",
    ]);
  });

  it("preserves nested strategy configuration on the save port and separates seeding", async () => {
    StrategiesPage();
    const payload = { name: "synthetic", config_json: { unknown_field: [1, 2] } };
    await h.mutations[0].mutationFn();
    await h.mutations[1].mutationFn(payload as never);
    expect(h.request.mock.calls).toEqual([
      ["/recommendation/strategies/seed", { method: "POST" }],
      ["/recommendation/strategies", { method: "POST", body: JSON.stringify(payload) }],
    ]);
  });
});

describe("system task page request ownership", () => {
  it("disables Redis and detail reads without diagnostics or selections", () => {
    SystemTasksPage();
    expect(h.queries.slice(2).map((q) => q.enabled)).toEqual([false, false, false, false]);
    expect(h.queries[0].refetchInterval).toBe(15_000);
    expect(h.queries[2].refetchInterval).toBe(10_000);
  });

  it("encodes selected trace/task identifiers and enables Redis-backed reads", async () => {
    h.states[1] = "trace/a b"; h.states[6] = "task/a b";
    h.data['["task-diagnostics"]'] = { redis: { available: true, totals: {} }, outbox: { counts: {} } };
    SystemTasksPage();
    expect(h.queries[2].enabled).toBe(true);
    expect(h.queries[4].enabled).toBe(true);
    await h.queries[3].queryFn();
    await h.queries[4].queryFn();
    expect(h.request.mock.calls).toEqual([
      ["/tasks/trace/trace%2Fa%20b"], ["/tasks/task%2Fa%20b"],
    ]);
  });

  it("keeps outbox retry, scheduled run, async retry and cancellation as separate operations", async () => {
    SystemTasksPage();
    await h.mutations[0].mutationFn(12 as never);
    for (const mutation of h.mutations.slice(1)) await mutation.mutationFn("task/a b" as never);
    expect(h.request.mock.calls).toEqual([
      ["/tasks/outbox/12/retry", { method: "POST" }],
      ["/tasks/scheduled/task%2Fa%20b/run", { method: "POST" }],
      ["/tasks/task%2Fa%20b/retry", { method: "POST" }],
      ["/tasks/task%2Fa%20b/cancel", { method: "POST" }],
    ]);
  });

  it("refreshes the open task drawer after cancellation even when another refresh rejects", async () => {
    h.states[6] = "task-1";
    h.data['["task-diagnostics"]'] = { redis: { available: true, totals: {} }, outbox: { counts: {} } };
    SystemTasksPage();
    h.refetches[0].mockRejectedValue(new Error("offline"));
    h.mutations[3].onSuccess!({ success: true, message: "requested" } as never);
    await Promise.resolve();
    expect(h.refetches.map((refetch) => refetch.mock.calls.length)).toEqual([1, 1, 1, 0, 1, 0]);
    expect(h.setters[7]).toHaveBeenCalledWith(null);
    expect(h.setters[8]).toHaveBeenCalledWith({ tone: "success", message: "requested" });
  });

  it("closes confirmation and records an error without refreshing after a failed cancellation", () => {
    SystemTasksPage();
    h.mutations[3].onError!(new Error("failed"));
    expect(h.setters[7]).toHaveBeenCalledWith(null);
    expect(h.setters[8]).toHaveBeenCalledWith(expect.objectContaining({ tone: "danger" }));
    expect(h.refetches.every((refetch) => refetch.mock.calls.length === 0)).toBe(true);
  });
});

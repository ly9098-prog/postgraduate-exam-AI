import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import BatchImagePage from "./batch-image/page";
import HistoryPage from "./history/page";
import MaintenancePage from "./maintenance/page";
import QuestionsPage from "./questions/page";
import TasksPage from "./tasks/page";
import TextPage from "./text-import/page";

type Mutation = {
  mutationFn: (input?: unknown) => Promise<unknown>;
  onSuccess?: (...args: unknown[]) => void;
  onError?: (error: unknown) => void;
};
type Query = {
  queryKey: unknown[];
  queryFn: () => Promise<unknown>;
  enabled?: boolean;
  refetchInterval?: (query: { state: { data?: { status: string } } }) => unknown;
};
type StreamEvents = {
  onTrace: (event: { seq: number; item_seq?: number }) => void;
  onDone: () => void;
  onError: () => void;
};
const ports = vi.hoisted(() => ({
  states: [] as unknown[],
  refs: [] as Array<{ current: unknown }>,
  stateIndex: 0,
  refIndex: 0,
  callbacks: [] as Array<() => Promise<void>>,
  effects: [] as Array<() => void | (() => void)>,
  queries: [] as Query[],
  mutations: [] as Mutation[],
  streams: [] as Array<{ url: string; events: StreamEvents; close: ReturnType<typeof vi.fn> }>,
  searchParams: new URLSearchParams(),
  request: vi.fn(),
  toQuery: vi.fn(() => "?fixture"),
  invalidate: vi.fn(),
}));

vi.mock("react", async (original) => ({
  ...await original<typeof import("react")>(),
  useId: () => "import-fixture",
  useMemo: (compute: () => unknown) => compute(),
  useCallback: (callback: () => Promise<void>) => {
    ports.callbacks.push(callback);
    return callback;
  },
  useEffect: (effect: () => void | (() => void)) => { ports.effects.push(effect); },
  useRef: (initial: unknown) => {
    const index = ports.refIndex++;
    ports.refs[index] ??= { current: initial };
    return ports.refs[index];
  },
  useState: (initial: unknown) => {
    const index = ports.stateIndex++;
    if (!(index in ports.states)) ports.states[index] = initial;
    return [ports.states[index], (next: unknown) => {
      ports.states[index] = typeof next === "function" ? next(ports.states[index]) : next;
    }];
  },
}));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: ports.invalidate }),
  useQuery: (query: Query) => {
    ports.queries.push(query);
    return { data: undefined, isLoading: false, isFetching: false, refetch: vi.fn() };
  },
  useMutation: (mutation: Mutation) => {
    ports.mutations.push(mutation);
    return { mutate: vi.fn(), isPending: false };
  },
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => ports.searchParams }));
vi.mock("@/lib/auth/auth-store", () => ({
  useAuthStore: (select: (state: { permissions: string[] }) => unknown) =>
    select({ permissions: [] }),
}));
vi.mock("@/lib/api/client", () => ({
  apiRequest: ports.request,
  toQuery: ports.toQuery,
  getApiAccessToken: () => "test-import-token",
}));
vi.mock("@/lib/api/sse", () => ({
  connectSSE: (url: string, _token: string, events: StreamEvents) => {
    const stream = { url, events, close: vi.fn() };
    ports.streams.push(stream);
    return stream;
  },
}));
vi.mock("./hooks/useImportConfig", () => ({
  useImportConfig: () => ({ ocrMode: "auto", setOcrMode: vi.fn() }),
}));

function render(page: () => unknown) {
  ports.stateIndex = ports.refIndex = 0;
  ports.callbacks = [];
  ports.effects = [];
  ports.queries = [];
  ports.mutations = [];
  return page();
}
function seed(values: Record<number, unknown>) {
  for (const [index, value] of Object.entries(values)) ports.states[Number(index)] = value;
}
function job(id: string, status = "running", count = 0) {
  return {
    job_id: id, status,
    items: [{
      seq: 1, item_id: 91, status: status === "completed" ? "succeeded" : "processing",
      question_count: count, error_message: null,
    }],
  };
}
function uploadFixture(status = "running") {
  ports.request.mockImplementation(async (url: string) =>
    url.startsWith("/imports/batch-image/upload")
      ? { job_id: "job-1" } : job("job-1", status, 2));
  seed({ 0: [new File(["image"], "one.png", { type: "image/png" })] });
  render(BatchImagePage);
}
function tasks() {
  return ports.states[6] as Array<{
    seq: number; status: string; jobId: string; questionCount: number;
    jobStatus: { job_id: string }; traceEvents: unknown[];
  }>;
}
function textOf(node: unknown): string {
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (!node || typeof node !== "object") return "";
  return textOf((node as { props?: { children?: unknown } }).props?.children);
}
function click(node: unknown, label: string): (() => Promise<void>) | undefined {
  if (Array.isArray(node)) {
    for (const child of node) {
      const found = click(child, label);
      if (found) return found;
    }
  } else if (node && typeof node === "object") {
    const props = (node as { props?: Record<string, unknown> }).props;
    if (!props) return;
    if (typeof props.onClick === "function" && textOf(props.children).includes(label)) {
      return props.onClick as () => Promise<void>;
    }
    for (const value of Object.values(props)) {
      const found = click(value, label);
      if (found) return found;
    }
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-30T00:00:00Z"));
  vi.clearAllMocks();
  ports.request.mockReset().mockResolvedValue({});
  ports.states = [];
  ports.refs = [];
  ports.streams = [];
  ports.searchParams = new URLSearchParams();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("batch image page lifecycle", () => {
  it("rejects an empty queue without sending a request", async () => {
    render(BatchImagePage);
    await ports.callbacks[0]();
    expect(ports.request).not.toHaveBeenCalled();
    expect(ports.states[4]).toMatchObject({ type: "error" });
  });

  it("sends all files once and bounds backend concurrency", async () => {
    uploadFixture();
    seed({ 0: [
      new File(["first"], "one.png"), new File(["second"], "two.png"),
    ], 1: "12", 3: 99 });
    render(BatchImagePage);
    await ports.callbacks[0]();
    const uploads = ports.request.mock.calls.filter(([url]) =>
      String(url).startsWith("/imports/batch-image/upload"));
    expect(uploads).toHaveLength(1);
    expect((uploads[0][1].body as FormData).getAll("files")).toHaveLength(2);
    expect(ports.toQuery).toHaveBeenCalledWith(expect.objectContaining({
      subject_id: 12, concurrency: 4, enable_ai_repair: true,
      batch_fast_mode: true, ocr_mode: "auto",
    }));
    expect(ports.streams[0].url).toBe("/imports/batch-image/job-1/stream");
    expect(ports.states[7]).toBe("polling");
  });

  it("closes the stream immediately when the initial status is terminal", async () => {
    uploadFixture("completed");
    await ports.callbacks[0]();
    expect(tasks()[0]).toMatchObject({ status: "succeeded", questionCount: 2 });
    expect(ports.streams[0].close).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("uses a watchdog and clears it after a terminal response", async () => {
    uploadFixture();
    await ports.callbacks[0]();
    expect(vi.getTimerCount()).toBe(1);
    ports.request.mockResolvedValue(job("job-1", "completed", 3));
    await vi.advanceTimersByTimeAsync(2500);
    expect(tasks()[0].questionCount).toBe(3);
    expect(ports.streams[0].close).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("deduplicates stream events and synchronizes after a stream error", async () => {
    uploadFixture();
    await ports.callbacks[0]();
    const events = ports.streams[0].events;
    events.onTrace({ seq: 1, item_seq: 1 });
    events.onTrace({ seq: 1, item_seq: 1 });
    expect(tasks()[0].traceEvents).toHaveLength(1);
    ports.request.mockResolvedValue(job("job-1", "completed"));
    events.onError();
    await Promise.resolve();
    expect(tasks()[0].status).toBe("succeeded");
  });

  it("aborts upload/status work and closes all resources on reset", async () => {
    uploadFixture();
    await ports.callbacks[0]();
    const signal = ports.request.mock.calls[0][1].signal as AbortSignal;
    await ports.callbacks[1]();
    expect(signal.aborted).toBe(true);
    expect(ports.streams[0].close).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
    expect(tasks()).toEqual([]);
    expect(ports.states[7]).toBe("idle");
  });

  it("runs the same resource cleanup when the page unmounts", async () => {
    uploadFixture();
    const cleanup = ports.effects[1]();
    await ports.callbacks[0]();
    if (typeof cleanup !== "function") throw new Error("missing unmount cleanup");
    cleanup();
    expect((ports.request.mock.calls[0][1].signal as AbortSignal).aborted).toBe(true);
    expect(ports.streams[0].close).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("marks upload failures locally without starting a stream", async () => {
    uploadFixture();
    ports.request.mockRejectedValueOnce(new Error("upload failed"));
    await ports.callbacks[0]();
    expect(tasks()[0].status).toBe("failed");
    expect(ports.states[4]).toEqual({ text: "upload failed", type: "error" });
    expect(ports.streams).toEqual([]);
  });

  it("invalidates the review queue once when all tasks finish", async () => {
    uploadFixture("completed");
    await ports.callbacks[0]();
    render(BatchImagePage);
    ports.effects[2]();
    ports.effects[2]();
    expect(ports.invalidate.mock.calls).toEqual([[{ queryKey: ["import-review-queue"] }]]);
    expect(ports.states[7]).toBe("done");
  });

  it("sends reparse requests to the item endpoint", async () => {
    render(BatchImagePage);
    await ports.mutations[0].mutationFn(91);
    expect(ports.request).toHaveBeenCalledWith("/imports/batch-image/items/91/reparse", {
      method: "POST",
    });
  });

  it("ignores a post-cancel status response after a new queue starts", async () => {
    let release!: (value: ReturnType<typeof job>) => void;
    const oldStatus = new Promise<ReturnType<typeof job>>((resolve) => { release = resolve; });
    let uploads = 0;
    ports.request.mockImplementation(async (url: string) => {
      if (url.startsWith("/imports/batch-image/upload")) return { job_id: `job-${++uploads}` };
      return url.endsWith("/job-1") ? oldStatus : job("job-2");
    });
    seed({ 0: [new File(["old"], "old.png")] });
    render(BatchImagePage);
    const firstRun = ports.callbacks[0]();
    await Promise.resolve();
    expect(ports.streams).toHaveLength(1);
    await ports.callbacks[1]();
    seed({ 0: [new File(["new"], "new.png")] });
    render(BatchImagePage);
    await ports.callbacks[0]();
    expect(tasks()[0]).toMatchObject({ jobId: "job-2", questionCount: 0 });

    release(job("job-1", "completed", 99));
    await firstRun;
    expect(tasks()[0]).toMatchObject({
      jobId: "job-2", status: "processing", questionCount: 0,
      jobStatus: { job_id: "job-2" },
    });
  });

  it("exposes upload cancellation and discards an upload response arriving after reset", async () => {
    let release!: (value: { job_id: string }) => void;
    ports.request.mockReturnValueOnce(new Promise((resolve) => { release = resolve; }));
    seed({ 0: [new File(["old"], "old.png")] });
    render(BatchImagePage);
    const run = ports.callbacks[0]();
    const tree = render(BatchImagePage);
    const cancel = click(tree, "取消上传");
    expect(cancel).toBeTypeOf("function");
    await cancel!();
    expect((ports.request.mock.calls[0][1].signal as AbortSignal).aborted).toBe(true);
    release({ job_id: "cancelled-upload" });
    await run;
    expect(ports.states[7]).toBe("idle");
    expect(tasks()).toEqual([]);
    expect(ports.streams).toEqual([]);
    expect(ports.request).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("discards queued trace callbacks and does not recreate a watchdog after reset", async () => {
    let release!: (value: ReturnType<typeof job>) => void;
    const oldStatus = new Promise<ReturnType<typeof job>>((resolve) => { release = resolve; });
    let uploads = 0;
    ports.request.mockImplementation(async (url: string) => {
      if (url.startsWith("/imports/batch-image/upload")) return { job_id: `job-${++uploads}` };
      return url.endsWith("/job-1") ? oldStatus : job("job-2");
    });
    seed({ 0: [new File(["old"], "old.png")] });
    render(BatchImagePage);
    const firstRun = ports.callbacks[0]();
    await Promise.resolve();
    const oldStream = ports.streams[0];
    await ports.callbacks[1]();
    seed({ 0: [new File(["new"], "new.png")] });
    render(BatchImagePage);
    await ports.callbacks[0]();
    const requests = ports.request.mock.calls.length;
    oldStream.events.onTrace({ seq: 99, item_seq: 1 });
    oldStream.events.onDone();
    oldStream.events.onError();
    release(job("job-1", "running", 99));
    await firstRun;
    expect(tasks()[0]).toMatchObject({ jobId: "job-2", traceEvents: [], questionCount: 0 });
    expect(ports.request).toHaveBeenCalledTimes(requests);
    expect(vi.getTimerCount()).toBe(1);
  });
});

describe("other import page requests", () => {
  it("routes CSV uploads through the detailed-diagnostics endpoint", async () => {
    seed({ 1: new File(["csv"], "questions.CSV") });
    render(TasksPage);
    ports.request.mockResolvedValueOnce({ inserted_count: 1 });
    await expect(ports.mutations[0].mutationFn()).resolves.toMatchObject({ kind: "csv" });
    expect(ports.request).toHaveBeenCalledWith("/imports/questions-csv", expect.objectContaining({
      method: "POST", timeoutMs: 120_000, exposeErrorDetail: true,
    }));
  });

  it("preserves pipeline configuration and page range for ordinary uploads", async () => {
    seed({ 1: new File(["pdf"], "questions.pdf"), 3: "12", 8: "2", 9: "5" });
    render(TasksPage);
    ports.request.mockResolvedValueOnce({ pipeline_id: "pipeline-1" });
    await expect(ports.mutations[0].mutationFn()).resolves.toMatchObject({ kind: "pipeline" });
    expect(ports.toQuery).toHaveBeenCalledWith(expect.objectContaining({
      subject_id: 12, import_mode: "auto", enable_ai_repair: true,
      image_fast_mode: true, page_start: "2", page_end: "5",
    }));
    expect(ports.request).toHaveBeenCalledWith("/imports/upload?fixture",
      expect.objectContaining({ method: "POST", body: expect.any(FormData) }));
    expect(ports.queries[0].enabled).toBe(false);
    expect(ports.queries[0].refetchInterval?.({ state: { data: { status: "completed" } } }))
      .toBe(false);
    expect(ports.queries[0].refetchInterval?.({ state: { data: { status: "running" } } }))
      .toBe(2500);
  });

  it("reports missing uploads before requesting the server", async () => {
    render(TasksPage);
    await expect(ports.mutations[0].mutationFn()).rejects.toThrow("请选择要导入的文件");
    expect(ports.request).not.toHaveBeenCalled();
  });

  it("keeps CSV success and pipeline success in their distinct UI/cache paths", () => {
    render(TasksPage);
    ports.mutations[0].onSuccess?.({
      kind: "csv", data: { total_rows: 3, inserted_count: 2, skipped_count: 1 },
    });
    expect(ports.states[10]).toBeNull();
    expect(ports.states[0]).toBe("upload");
    expect(ports.invalidate.mock.calls).toEqual([[{ queryKey: ["questions"] }]]);
    ports.invalidate.mockClear();
    ports.mutations[0].onSuccess?.({ kind: "pipeline", data: { pipeline_id: "p-1" } });
    expect(ports.states[10]).toBe("p-1");
    expect(ports.states[0]).toBe("progress");
    expect(ports.invalidate).not.toHaveBeenCalled();
  });

  it("sends text verbatim to parsing and imports only currently valid questions", async () => {
    const valid = {
      block_index: 1, question_type: "single_choice", stem: "question",
      options: [], knowledge_points: [], answer: "A", analysis: null, difficulty: 2,
      is_valid: true, errors: [], warnings: [], question_hash: null,
      stem_hash: null, detection_method: "fixture",
    };
    seed({ 0: "source $x$", 5: {
      questions: [valid, { ...valid, block_index: 2, is_valid: false }],
      raw_count: 2, valid_count: 1, warnings: [],
    } });
    render(TextPage);
    await ports.mutations[0].mutationFn();
    await ports.mutations[1].mutationFn();
    expect(ports.request.mock.calls).toEqual([
      ["/imports/text-parse", {
        method: "POST", body: JSON.stringify({ text: "source $x$", subject_id: null }),
      }],
      ["/imports/text-import", {
        method: "POST", body: JSON.stringify({ subject_id: null, questions: [valid] }),
      }],
    ]);
    ports.mutations[1].onSuccess?.({ batch_id: "b-1" });
    expect(ports.invalidate.mock.calls).toEqual([[{ queryKey: ["import-review-queue"] }]]);
  });

  it("keeps history publishing separate from deletion and clears matching selection", async () => {
    seed({ 1: "batch-1" });
    render(HistoryPage);
    await ports.mutations[0].mutationFn({ action: "publish", batchId: "batch-1" });
    await ports.mutations[0].mutationFn({ action: "delete", batchId: "batch-1" });
    expect(ports.request.mock.calls).toEqual([
      ["/imports/batch-1/publish", { method: "POST" }],
      ["/imports/batch-1", { method: "DELETE" }],
    ]);
    ports.mutations[0].onSuccess?.({ deleted_count: 1 }, { action: "delete", batchId: "batch-1" });
    expect(ports.states[1]).toBeNull();
    expect(ports.invalidate.mock.calls).toEqual([[{ queryKey: ["import-batches"] }]]);
  });

  it("performs a maintenance dry run and restores its local busy state", async () => {
    const tree = render(MaintenancePage);
    const runDryRun = click(tree, "运行 Dry-Run");
    if (!runDryRun) throw new Error("missing dry-run action");
    ports.request.mockResolvedValueOnce({ dry_run: true });
    await runDryRun();
    expect(ports.request).toHaveBeenCalledWith("/imports/maintenance/cleanup", {
      method: "POST", body: '{"target":"all","dry_run":true}',
      headers: { "Content-Type": "application/json" },
    });
    expect(ports.states[1]).toEqual({ dry_run: true });
    expect(ports.states[3]).toBe(false);
    expect(ports.states[2]).toBe(false);
  });

  it("uses the URL batch filter while keeping full question detail disabled initially", async () => {
    ports.searchParams = new URLSearchParams("batch_id=url-batch");
    render(QuestionsPage);
    await ports.queries[0].queryFn();
    expect(ports.toQuery).toHaveBeenCalledWith(expect.objectContaining({
      page: 1, page_size: 50, batch_id: "url-batch",
    }));
    expect(ports.request).toHaveBeenCalledWith("/imports/review-queue?fixture");
    expect(ports.queries[1].queryKey).toEqual(["import-question-detail", null]);
    expect(ports.queries[1].enabled).toBe(false);
  });
});

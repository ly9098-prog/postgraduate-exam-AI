import { beforeEach, describe, expect, it, vi } from "vitest";
import ReviewPage from "./page";

type Query = {
  queryKey: unknown[];
  queryFn: () => Promise<unknown>;
  enabled?: boolean;
  retry?: boolean;
};
type Mutation = {
  mutationFn: (input: unknown) => Promise<unknown>;
  onSuccess: (result: { id: number }, input: unknown) => void;
  onError: (error: unknown) => void;
};
const harness = vi.hoisted(() => ({
  states: [] as unknown[],
  setters: [] as ReturnType<typeof vi.fn>[],
  queries: [] as Query[],
  mutations: [] as Mutation[],
  queryData: {} as Record<string, unknown>,
  stateIndex: 0,
  request: vi.fn(),
  toQuery: vi.fn(() => "?fixture"),
  invalidate: vi.fn(),
}));

vi.mock("react", async (original) => ({
  ...await original<typeof import("react")>(),
  useMemo: (compute: () => unknown) => compute(),
  useState: (initial: unknown) => {
    const index = harness.stateIndex++;
    const setter = vi.fn();
    harness.setters.push(setter);
    return [index in harness.states ? harness.states[index] : initial, setter];
  },
}));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: harness.invalidate }),
  useQuery: (options: Query) => {
    harness.queries.push(options);
    return {
      data: harness.queryData[JSON.stringify(options.queryKey)],
      isError: false,
      isLoading: false,
    };
  },
  useMutation: (options: Mutation) => {
    harness.mutations.push(options);
    return { mutate: vi.fn(), isPending: false };
  },
}));
vi.mock("@/lib/auth/auth-store", () => ({
  useAuthStore: (select: (state: { permissions: string[] }) => unknown) =>
    select({ permissions: ["question:review", "question:write", "question:batch_review"] }),
}));
vi.mock("@/lib/api/client", () => ({
  apiRequest: harness.request,
  toQuery: harness.toQuery,
}));

const question = { id: 7, content: { stem: "Seven" }, review_status: "re_pending" };
function setup(options: {
  preview?: typeof question;
  selected?: number[];
  reason?: string;
  tab?: string;
} = {}) {
  harness.states = [
    options.selected ?? [], "keyword", options.tab ?? "re_pending",
    options.preview?.id ?? null, options.reason ?? "", null, null,
  ];
  harness.queryData = {
    '["review-questions","re_pending","keyword"]': { items: [question] },
    ...(options.preview ? {
      [`["review-preview",${options.preview.id}]`]: options.preview,
    } : {}),
  };
  // Capture the real page's query/mutation closures without mounting browser UI.
  ReviewPage();
  return harness.mutations;
}

beforeEach(() => {
  vi.clearAllMocks();
  harness.request.mockReset().mockResolvedValue(question);
  harness.states = [];
  harness.setters = [];
  harness.queries = [];
  harness.mutations = [];
  harness.queryData = {};
  harness.stateIndex = 0;
});

describe("review page request contracts", () => {
  it("keeps list, preview and historical reads in separate cache scopes", async () => {
    setup({ preview: question });
    expect(harness.queries.map((query) => query.queryKey)).toEqual([
      ["review-questions", "re_pending", "keyword"],
      ["review-preview", 7],
      ["review-preview", 7, "versions"],
      ["review-preview", 7, "version-detail"],
    ]);
    await harness.queries[0].queryFn();
    expect(harness.toQuery).toHaveBeenCalledWith({
      page: 1, page_size: 50, review_status: "re_pending", keyword: "keyword",
    });
    expect(harness.request).toHaveBeenCalledWith("/questions?fixture");
    expect(harness.queries.every((query) => query.retry === false)).toBe(true);
  });

  it("does not enable preview or historical reads without a selection", () => {
    setup();
    expect(harness.queries.slice(1).map((query) => query.enabled))
      .toEqual([false, false, false]);
  });

  it("does not enable historical reads on the rejected tab", () => {
    setup({ preview: question, tab: "rejected" });
    expect(harness.queries.slice(1).map((query) => query.enabled))
      .toEqual([true, false, false]);
  });

  it("approves the matching preview without a redundant detail request", async () => {
    const [review] = setup({ preview: question });
    await review.mutationFn({ action: "approve", id: 7 });
    expect(harness.request.mock.calls).toEqual([
      ["/questions/7/approve", { method: "POST" }],
    ]);
  });

  it("loads the actual target before approving a different preview", async () => {
    const [review] = setup({ preview: { ...question, id: 8 } });
    await review.mutationFn({ action: "approve", id: 7 });
    expect(harness.request.mock.calls).toEqual([
      ["/questions/7"],
      ["/questions/7/approve", { method: "POST" }],
    ]);
  });

  it("blocks approval when the target still contains an unreviewed table", async () => {
    const [review] = setup();
    harness.request.mockResolvedValueOnce({
      ...question,
      content: { segments: [{ type: "table", rows: [["unverified"]], requires_review: true }] },
    });
    await expect(review.mutationFn({ action: "approve", id: 7 }))
      .rejects.toThrow(/结构化表格/);
    expect(harness.request).toHaveBeenCalledTimes(1);
  });

  it("preserves an individual reject reason without batch normalization", async () => {
    const [review] = setup({ reason: "  reviewer reason  " });
    await review.mutationFn({ action: "reject", id: 7 });
    expect(harness.request).toHaveBeenCalledWith("/questions/7/reject", {
      method: "POST", body: JSON.stringify({ reason: "  reviewer reason  " }),
    });
  });

  it("prunes invisible selections and trims the optional batch reject reason", async () => {
    const [, batch] = setup({ selected: [7, 99], reason: "  duplicate  " });
    await batch.mutationFn("rejected");
    expect(harness.request).toHaveBeenCalledWith("/questions/batch-reject", {
      method: "POST", body: JSON.stringify({ ids: [7], reason: "duplicate" }),
    });
  });

  it("omits reject reasons from approvals and blank batch rejections", async () => {
    const [, batch] = setup({ selected: [7], reason: "  " });
    await batch.mutationFn("approved");
    await batch.mutationFn("rejected");
    expect(harness.request.mock.calls).toEqual([
      ["/questions/batch-approve", { method: "POST", body: '{"ids":[7]}' }],
      ["/questions/batch-reject", { method: "POST", body: '{"ids":[7]}' }],
    ]);
  });

  it("sends the chosen historical revision and preserves the rollback fallback", async () => {
    const [, , rollback] = setup();
    await expect(rollback.mutationFn(null)).rejects.toThrow("缺少回滚目标");
    expect(harness.request).not.toHaveBeenCalled();
    await rollback.mutationFn({ action: "rollback", id: 7, version: 2 });
    expect(harness.request).toHaveBeenCalledWith("/questions/7/rollback", {
      method: "POST", body: JSON.stringify({ version: 2, reason: "恢复历史版本" }),
    });
  });

  it("refreshes the matching preview and clears confirmation after individual success", () => {
    const [review, , rollback] = setup({ preview: question });
    for (const mutation of [review, rollback]) {
      harness.invalidate.mockClear();
      mutation.onSuccess({ id: 7 }, { action: "approve", id: 7 });
      expect(harness.invalidate.mock.calls).toEqual([
        [{ queryKey: ["review-questions"] }],
        [{ queryKey: ["review-preview", 7] }],
      ]);
      expect(harness.setters[5]).toHaveBeenCalledWith(null);
      expect(harness.setters[4]).toHaveBeenCalledWith("");
    }
  });

  it("does not refresh an unrelated preview or claim batch preview invalidation", () => {
    const [review, batch] = setup({ preview: { ...question, id: 8 } });
    review.onSuccess({ id: 7 }, { action: "approve", id: 7 });
    expect(harness.invalidate.mock.calls).toEqual([[{ queryKey: ["review-questions"] }]]);
    harness.invalidate.mockClear();
    batch.onSuccess({ id: 7 }, "approved");
    expect(harness.invalidate.mock.calls).toEqual([[{ queryKey: ["review-questions"] }]]);
    expect(harness.setters[0]).toHaveBeenCalledWith([]);
  });

  it("reports errors without performing successful-cache invalidation", () => {
    const mutations = setup();
    for (const mutation of mutations) {
      mutation.onError(new Error("network failed"));
      expect(harness.setters[6]).toHaveBeenLastCalledWith("network failed");
    }
    expect(harness.invalidate).not.toHaveBeenCalled();
  });
});

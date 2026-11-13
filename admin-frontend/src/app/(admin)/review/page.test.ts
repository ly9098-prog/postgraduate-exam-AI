import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AdminQuestionDetail } from "@/lib/api/types";
import ReviewPage from "./page";

type Query = {
  queryKey: unknown[];
  queryFn: () => Promise<unknown>;
  enabled?: boolean;
  retry?: boolean;
};
type Mutation = {
  mutationFn: (input: unknown) => Promise<unknown>;
  onSuccess: (result: unknown, input: unknown) => void;
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
  removeQueries: vi.fn(),
}));

vi.mock("react", async (original) => ({
  ...(await original<typeof import("react")>()),
  useMemo: (compute: () => unknown) => compute(),
  useCallback: (callback: unknown) => callback,
  useEffect: () => {},
  useRef: (initial: unknown) => ({ current: initial }),
  useState: (initial: unknown) => {
    const index = harness.stateIndex++;
    const setter = vi.fn();
    harness.setters.push(setter);
    return [index in harness.states ? harness.states[index] : initial, setter];
  },
}));

vi.mock("./use-debounced-value", () => ({
  useDebouncedValue: (value: string) => value,
}));

vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({
    invalidateQueries: harness.invalidate,
    removeQueries: harness.removeQueries,
  }),
  useQuery: (options: Query) => {
    harness.queries.push(options);
    return {
      data: harness.queryData[JSON.stringify(options.queryKey)],
      isError: false,
      isLoading: false,
      isFetching: false,
    };
  },
  useMutation: (options: Mutation) => {
    harness.mutations.push(options);
    return { mutate: vi.fn(), isPending: false };
  },
}));

vi.mock("@/lib/auth/auth-store", () => ({
  useAuthStore: (select: (state: { permissions: string[] }) => unknown) =>
    select({
      permissions: [
        "question:review",
        "question:write",
        "question:batch_review",
      ],
    }),
}));

vi.mock("@/lib/api/client", () => ({
  apiRequest: harness.request,
  toQuery: harness.toQuery,
}));

const question: AdminQuestionDetail = {
  id: 7,
  question_type: "single_choice",
  content: { stem: "Seven" },
  answer: "A",
  difficulty: 3,
  review_status: "re_pending",
  is_active: false,
};

type SetupOptions = {
  preview?: AdminQuestionDetail;
  selected?: Set<number>;
  reason?: string;
  tab?: "re_pending" | "rejected";
  keyword?: string;
  subjectId?: string;
  page?: number;
  pageSize?: number;
  baselineVersion?: number | null;
  versions?: Array<{ version: number }>;
  baselineDetail?: Record<string, unknown>;
};

function listKey(options: SetupOptions) {
  const keyword = options.keyword ?? "keyword";
  const subjectId = options.subjectId ?? "";
  const numericSubjectId = Number(subjectId);
  return JSON.stringify([
    "review-questions",
    {
      page: options.page ?? 1,
      page_size: options.pageSize ?? 20,
      review_status: options.tab ?? "re_pending",
      ...(keyword.trim() ? { keyword: keyword.trim() } : {}),
      ...(Number.isInteger(numericSubjectId) && numericSubjectId > 0
        ? { subject_id: numericSubjectId }
        : {}),
    },
  ]);
}

function setup(options: SetupOptions = {}) {
  harness.stateIndex = 0;
  harness.setters = [];
  harness.queries = [];
  harness.mutations = [];
  harness.states = [
    options.selected ?? new Set<number>(),
    options.keyword ?? "keyword",
    options.subjectId ?? "",
    options.tab ?? "re_pending",
    options.page ?? 1,
    options.pageSize ?? 20,
    options.preview?.id ?? null,
    options.baselineVersion ?? null,
    options.reason ?? "",
    null,
    null,
    null,
  ];

  const versions = options.versions ?? [
    { version: 3 },
    { version: 2 },
    { version: 1 },
  ];
  const effectiveBaseline =
    options.baselineVersion ?? versions[1]?.version ?? null;

  harness.queryData = {
    [listKey(options)]: {
      items: [question],
      total: 1,
      total_pages: 1,
      page: 1,
      page_size: 20,
    },
    ...(options.preview
      ? { [`["review-preview",${options.preview.id}]`]: options.preview }
      : {}),
    ...(options.preview
      ? {
          [`["review-preview",${options.preview.id},"versions"]`]: {
            items: versions,
            total: versions.length,
            page: 1,
            page_size: 20,
            total_pages: 1,
          },
        }
      : {}),
    ...(options.preview &&
    effectiveBaseline !== null &&
    options.baselineDetail
      ? {
          [`["review-preview",${options.preview.id},"version-detail",${effectiveBaseline}]`]:
            options.baselineDetail,
        }
      : {}),
  };

  ReviewPage();
  return harness.mutations;
}

function queryByPrefix(prefix: string) {
  const query = harness.queries.find(
    (candidate) => candidate.queryKey[0] === prefix,
  );
  if (!query) throw new Error(`missing query ${prefix}`);
  return query;
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
  it("queries the active queue with pagination and keeps cache scopes separate", async () => {
    setup();
    expect(harness.queries.map((query) => query.queryKey[0])).toEqual([
      "review-questions",
      "review-subject-options",
      "review-preview",
      "review-preview",
      "review-preview",
    ]);
    await queryByPrefix("review-questions").queryFn();
    expect(harness.toQuery).toHaveBeenCalledWith({
      page: 1,
      page_size: 20,
      review_status: "re_pending",
      keyword: "keyword",
    });
    expect(harness.request).toHaveBeenCalledWith("/questions?fixture");
    expect(harness.queries.every((query) => query.retry === false)).toBe(true);
  });

  it("adds the subject filter to the list request", async () => {
    setup({ subjectId: "12", page: 2, pageSize: 50 });
    await queryByPrefix("review-questions").queryFn();
    expect(harness.toQuery).toHaveBeenCalledWith({
      page: 2,
      page_size: 50,
      review_status: "re_pending",
      keyword: "keyword",
      subject_id: 12,
    });
  });

  it("does not enable preview, versions or baseline reads without a selection", () => {
    setup();
    const preview = queryByPrefix("review-preview");
    const [, versions, baseline] = harness.queries.filter(
      (query) => query.queryKey[0] === "review-preview",
    );
    expect(preview.enabled).toBe(false);
    expect(versions.enabled).toBe(false);
    expect(baseline.enabled).toBe(false);
  });

  it("enables the preview, version list and derived baseline together", () => {
    setup({ preview: question });
    const [preview, versions, baseline] = harness.queries.filter(
      (query) => query.queryKey[0] === "review-preview",
    );
    expect(preview.enabled).toBe(true);
    expect(versions.enabled).toBe(true);
    expect(baseline.queryKey).toEqual([
      "review-preview",
      7,
      "version-detail",
      2,
    ]);
    expect(baseline.enabled).toBe(true);
  });

  it("uses an explicitly selected version as the comparison baseline", () => {
    setup({ preview: question, baselineVersion: 1 });
    const baseline = harness.queries.filter(
      (query) => query.queryKey[0] === "review-preview",
    )[2];
    expect(baseline.queryKey).toEqual([
      "review-preview",
      7,
      "version-detail",
      1,
    ]);
  });
});

describe("review page actions", () => {
  it("approves the matching preview without a redundant detail request", async () => {
    const [review] = setup({ preview: question });
    await review.mutationFn({ action: "approve", id: 7 });
    expect(harness.request.mock.calls).toEqual([
      ["/questions/7/approve", { method: "POST", exposeErrorDetail: true }],
    ]);
  });

  it("loads the actual target before approving a different preview", async () => {
    const [review] = setup({ preview: { ...question, id: 8 } });
    await review.mutationFn({ action: "approve", id: 7 });
    expect(harness.request.mock.calls).toEqual([
      ["/questions/7"],
      ["/questions/7/approve", { method: "POST", exposeErrorDetail: true }],
    ]);
  });

  it("blocks approval when the target still contains an unreviewed table", async () => {
    const [review] = setup();
    harness.request.mockResolvedValueOnce({
      ...question,
      content: {
        segments: [
          { type: "table", rows: [["unverified"]], requires_review: true },
        ],
      },
    });
    await expect(
      review.mutationFn({ action: "approve", id: 7 }),
    ).rejects.toThrow(/结构化表格/);
    expect(harness.request).toHaveBeenCalledTimes(1);
  });

  it("trims an individual reject reason", async () => {
    const [review] = setup({ reason: "  reviewer reason  " });
    await review.mutationFn({ action: "reject", id: 7 });
    expect(harness.request).toHaveBeenCalledWith("/questions/7/reject", {
      method: "POST",
      exposeErrorDetail: true,
      body: JSON.stringify({ reason: "reviewer reason" }),
    });
  });

  it("prunes invisible selections and sends a trimmed batch reason", async () => {
    const [, batch] = setup({
      selected: new Set([7, 99]),
      reason: "  duplicate  ",
    });
    await batch.mutationFn("rejected");
    expect(harness.request).toHaveBeenCalledWith("/questions/batch-reject", {
      method: "POST",
      exposeErrorDetail: true,
      headers: { "Idempotency-Key": expect.stringMatching(/^review-batch-/) },
      body: JSON.stringify({ ids: [7], reason: "duplicate" }),
    });
  });

  it("omits reject reasons from approvals and blank batch rejections", async () => {
    const [, batch] = setup({ selected: new Set([7]), reason: "  " });
    await batch.mutationFn("approved");
    await batch.mutationFn("rejected");
    const [approveCall, rejectCall] = harness.request.mock.calls;
    expect(approveCall[0]).toBe("/questions/batch-approve");
    expect(approveCall[1]).toMatchObject({
      method: "POST",
      exposeErrorDetail: true,
      body: '{"ids":[7]}',
      headers: { "Idempotency-Key": expect.stringMatching(/^review-batch-/) },
    });
    expect(rejectCall[0]).toBe("/questions/batch-reject");
    expect(rejectCall[1]).toMatchObject({
      method: "POST",
      exposeErrorDetail: true,
      body: '{"ids":[7]}',
      headers: { "Idempotency-Key": expect.stringMatching(/^review-batch-/) },
    });
  });

  it("reuses the batch idempotency key for an identical retry", async () => {
    const [, batch] = setup({ selected: new Set([7]), reason: "duplicate" });
    await batch.mutationFn("rejected");
    await batch.mutationFn("rejected");
    const [first, second] = harness.request.mock.calls;
    expect(first[1].headers["Idempotency-Key"]).toBe(
      second[1].headers["Idempotency-Key"],
    );
  });

  it("sends the chosen historical revision and preserves the rollback fallback", async () => {
    const [, , rollback] = setup({ reason: "  rollback reason  " });
    await rollback.mutationFn({ action: "rollback", id: 7, version: 2 });
    expect(harness.request).toHaveBeenCalledWith("/questions/7/rollback", {
      method: "POST",
      exposeErrorDetail: true,
      body: JSON.stringify({ version: 2, reason: "rollback reason" }),
    });
    harness.request.mockClear();
    setup({ reason: "  " });
    await harness.mutations[2].mutationFn({
      action: "rollback",
      id: 7,
      version: 2,
    });
    expect(harness.request).toHaveBeenCalledWith("/questions/7/rollback", {
      method: "POST",
      exposeErrorDetail: true,
      body: JSON.stringify({ version: 2, reason: "恢复历史版本" }),
    });
  });
});

describe("review page feedback", () => {
  it("refreshes the list and closes the matching preview after success", () => {
    const [review] = setup({ preview: question });
    review.onSuccess({ id: 7 }, { action: "approve", id: 7 });
    expect(harness.invalidate.mock.calls).toEqual([
      [{ queryKey: ["review-questions"] }],
    ]);
    expect(harness.removeQueries).toHaveBeenCalledWith({
      queryKey: ["review-preview", 7],
    });
    expect(harness.setters[9]).toHaveBeenCalledWith(null);
    expect(harness.setters[8]).toHaveBeenCalledWith("");
    expect(harness.setters[6]).toHaveBeenCalledWith(null);
    expect(harness.setters[7]).toHaveBeenCalledWith(null);
  });

  it("does not close an unrelated preview", () => {
    const [review] = setup({ preview: { ...question, id: 8 } });
    review.onSuccess({ id: 7 }, { action: "approve", id: 7 });
    expect(harness.invalidate.mock.calls).toEqual([
      [{ queryKey: ["review-questions"] }],
    ]);
    expect(harness.removeQueries).toHaveBeenCalledWith({
      queryKey: ["review-preview", 7],
    });
    expect(harness.setters[6]).not.toHaveBeenCalledWith(null);
  });

  it("surfaces batch success ids and failed items instead of a bare success claim", () => {
    const [, batch] = setup({ selected: new Set([7]) });
    batch.onSuccess(
      { success_ids: [7], failed_items: [{ id: 8, error: "状态不允许" }] },
      "approved",
    );
    expect(harness.setters[11]).toHaveBeenCalledWith({
      decision: "approved",
      result: { successIds: [7], failedItems: [{ id: 8, error: "状态不允许" }] },
    });
    expect(harness.setters[10]).toHaveBeenCalledWith({
      text: "批量通过完成：成功 1 项，失败 1 项（#8 状态不允许）。",
      tone: "danger",
    });
    expect(harness.setters[0]).toHaveBeenCalledWith(new Set());
    expect(harness.invalidate.mock.calls).toEqual([
      [{ queryKey: ["review-questions"] }],
    ]);
  });

  it("reports errors without invalidating successful caches", () => {
    setup();
    for (const mutation of harness.mutations) {
      mutation.onError(new Error("network failed"));
      expect(harness.setters[10]).toHaveBeenLastCalledWith({
        text: "network failed",
        tone: "danger",
      });
    }
    expect(harness.invalidate).not.toHaveBeenCalled();
  });
});

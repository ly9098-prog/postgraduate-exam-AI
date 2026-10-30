import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type ReactElement } from "react";
import ExamPapersPage from "./page";
import ExamPaperDetailPage from "./[id]/page";
import FormulasPage from "../formulas/page";
import EditFormulaPage from "../formulas/[id]/page";
import NewFormulaPage from "../formulas/new/page";
import FormulaCategoriesPage from "../formulas/categories/page";
import { FormulaGraphAssetPanel } from "@/components/formulas/formula-graph-asset-panel";
import { FormulaGraphSpecPanel } from "@/components/formulas/formula-graph-spec-panel";
import { FormulaEditorForm } from "@/components/formulas/formula-editor-form";

type Query = { queryKey: unknown[]; queryFn: () => Promise<unknown>; enabled?: boolean };
type Mutation = {
  mutationFn: (input?: never) => Promise<unknown>;
  onSuccess?: (result: never, input?: never) => unknown;
  onError?: (error: Error, input?: never) => unknown;
};
const h = vi.hoisted(() => ({
  states: [] as unknown[], index: 0, setters: [] as ReturnType<typeof vi.fn>[],
  effects: [] as (() => unknown)[], queries: [] as Query[], mutations: [] as Mutation[],
  data: {} as Record<string, unknown>, id: "paper-a", search: "",
  request: vi.fn(), invalidate: vi.fn(), setData: vi.fn(), remove: vi.fn(),
  push: vi.fn(), replace: vi.fn(),
  toQuery: vi.fn((query: Record<string, unknown>) => {
    void query;
    return "?fixture";
  }),
}));
vi.mock("react", async (original) => ({
  ...await original<typeof import("react")>(),
  useMemo: (compute: () => unknown) => compute(),
  useCallback: (callback: unknown) => callback,
  useRef: (current: unknown) => ({ current }),
  useEffect: (effect: () => unknown) => { h.effects.push(effect); },
  useState: (initial: unknown) => {
    const index = h.index++;
    const setter = vi.fn();
    h.setters.push(setter);
    const fallback = typeof initial === "function" ? initial() : initial;
    return [index in h.states ? h.states[index] : fallback, setter];
  },
}));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({
    invalidateQueries: h.invalidate, setQueryData: h.setData, removeQueries: h.remove,
  }),
  useQuery: (query: Query) => {
    h.queries.push(query);
    return { data: h.data[JSON.stringify(query.queryKey)], isLoading: false, isFetching: false };
  },
  useMutation: (mutation: Mutation) => {
    h.mutations.push(mutation);
    return { mutate: vi.fn(), isPending: false };
  },
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: h.push, replace: h.replace }),
  useParams: () => ({ id: h.id }),
  useSearchParams: () => new URLSearchParams(h.search),
}));
vi.mock("@/lib/auth/auth-store", () => ({
  useAuthStore: (select: (state: unknown) => unknown) => select({
    role: { name: "super_admin" },
    permissions: ["question:write", "formula:create", "formula:update", "formula:review", "formula:delete"],
  }),
}));
vi.mock("@/lib/api/client", () => ({ apiRequest: h.request, toQuery: h.toQuery }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  h.states = []; h.index = 0; h.setters = []; h.effects = [];
  h.queries = []; h.mutations = []; h.data = {}; h.id = "paper-a"; h.search = "";
  h.request.mockReset().mockResolvedValue({});
  h.invalidate.mockReset().mockResolvedValue(undefined);
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

function loadPaper() {
  const paper = {
    public_id: "public/a", status: "draft", title: "Fixture",
    paper_type: "past_exam_choice", year: 2026, items: [], validation_errors: [],
  };
  h.data[JSON.stringify(["exam-paper", h.id])] = paper;
  return paper;
}

describe("exam administration request lifecycle", () => {
  it("converts creation fields and waits for list invalidation before navigation", async () => {
    h.states = [" Fixture ", "past_exam_choice", "2026", "75"];
    ExamPapersPage();
    await h.mutations[0].mutationFn();
    expect(h.request).toHaveBeenCalledWith("/exams/papers", {
      method: "POST", exposeErrorDetail: true,
      body: '{"title":"Fixture","paper_type":"past_exam_choice","year":2026,"duration_sec":4500}',
    });
    let release!: () => void;
    h.invalidate.mockReturnValue(new Promise<void>((resolve) => { release = resolve; }));
    const pending = h.mutations[0].onSuccess!({ public_id: "public-a" } as never);
    expect(h.push).not.toHaveBeenCalled();
    release();
    await pending;
    expect(h.push).toHaveBeenCalledWith("/exams/public-a");
  });

  it("reads legacy numeric references then redirects through the returned public ID", async () => {
    h.id = "42";
    loadPaper();
    ExamPaperDetailPage();
    await h.queries[0].queryFn();
    expect(h.request).toHaveBeenCalledWith("/exams/papers/42");
    h.effects[0]();
    expect(h.replace).toHaveBeenCalledWith("/exams/public/a");
  });

  it("uses encoded public references and restricts candidate search to the existing scope", async () => {
    h.id = "paper/a"; h.states[1] = "mock_choice"; h.states[7] = "settled";
    loadPaper();
    ExamPaperDetailPage();
    await h.queries[0].queryFn();
    await h.queries[1].queryFn();
    expect(h.request).toHaveBeenCalledWith("/exams/papers/public/paper%2Fa");
    expect(h.queries[1].enabled).toBe(true);
    expect(h.toQuery).toHaveBeenCalledWith({
      page: 1, page_size: 100, question_type: "single_choice", review_status: "approved",
      is_active: true,
      subject_codes: "data_structure,computer_organization,operating_system,computer_network",
      keyword: "settled",
    });
  });

  it("saves ordered question IDs/scores without sending presentation or version fields", async () => {
    loadPaper();
    h.states[5] = [
      { question_id: 12, score: " 2.5 ", question_version_id: 901, content: { text: "fixture" } },
      { question_id: 4, score: "3", version_is_current: false },
    ];
    ExamPaperDetailPage();
    await h.mutations[1].mutationFn();
    expect(h.request).toHaveBeenCalledWith("/exams/papers/public/public%2Fa/items", {
      method: "PUT", exposeErrorDetail: true,
      body: '{"items":[{"question_id":12,"score":2.5},{"question_id":4,"score":3}]}',
    });
  });

  it.each([
    { items: [], error: "试卷至少需要 1 道选择题后才能保存组卷。" },
    {
      items: [{ question_id: 2, score: "1" }, { question_id: 2, score: "2" }],
      error: "第 2 题与前面的题目重复（Q#2），请删除重复项。",
    },
    { items: [{ question_id: 2, score: "" }], error: "第 1 题（Q#2）分值必须大于 0 且不超过 100。" },
  ])("rejects invalid draft items before transport (%j)", ({ items, error }) => {
    loadPaper(); h.states[5] = items;
    ExamPaperDetailPage();
    expect(() => h.mutations[1].mutationFn()).toThrow(error);
    expect(h.request).not.toHaveBeenCalled();
  });

  it("keeps publish/archive/restore operations on public references", async () => {
    loadPaper();
    ExamPaperDetailPage();
    for (const action of ["publish", "archive", "restore"]) {
      await h.mutations[2].mutationFn(action as never);
    }
    expect(h.request.mock.calls).toEqual(
      ["publish", "archive", "restore"].map((action) => [
        `/exams/papers/public/public%2Fa/${action}`, { method: "POST", exposeErrorDetail: true },
      ]),
    );
  });

  it("invalidates both detail and list after a failed state action", async () => {
    loadPaper();
    ExamPaperDetailPage();
    await h.mutations[2].onError!(new Error("conflict"), "restore" as never);
    expect(h.invalidate.mock.calls.map(([query]) => query.queryKey)).toEqual([
      ["exam-paper", "paper-a"], ["exam-papers"],
    ]);
    expect(h.setters[9]).toHaveBeenCalledWith(null);
    expect(h.replace).not.toHaveBeenCalled();
  });

  it("removes detail cache and waits for invalidation before leaving a deleted paper", async () => {
    loadPaper();
    ExamPaperDetailPage();
    let release!: () => void;
    h.invalidate.mockReturnValue(new Promise<void>((resolve) => { release = resolve; }));
    const pending = h.mutations[3].onSuccess!({} as never);
    expect(h.remove).toHaveBeenCalledWith({ queryKey: ["exam-paper", "paper-a"] });
    expect(h.replace).not.toHaveBeenCalled();
    release();
    await pending;
    expect(h.replace).toHaveBeenCalledWith("/exams");
  });

  it("refuses quick-fill when year/type drafts do not match the saved paper", async () => {
    loadPaper(); h.states[2] = "2025";
    ExamPaperDetailPage();
    await expect(h.mutations[4].mutationFn()).rejects.toThrow();
    expect(h.request).not.toHaveBeenCalled();
  });
});

describe("formula page and graph request lifecycle", () => {
  it("maps URL filters to list queries and enables only the selected detail", async () => {
    h.search = "q=integral&category_id=7&page=2&selected_id=19&status=draft";
    FormulasPage();
    await h.queries[0].queryFn();
    await h.queries[2].queryFn();
    expect(h.toQuery).toHaveBeenCalledWith(expect.objectContaining({
      q: "integral", category_id: 7, include_descendants: true, page: 2, page_size: 20,
      status: "draft",
    }));
    expect(h.queries[2].enabled).toBe(true);
    expect(h.request).toHaveBeenCalledWith("/formulas/19");
  });

  it("removes only successfully handled IDs from batch selection", () => {
    FormulasPage();
    h.mutations[2].onSuccess!({
      items: [{ id: 1, status: "published" }, { id: 2, status: "not_found" }, { id: 3, status: "rejected" }],
    } as never);
    const update = h.setters[10].mock.calls[0][0] as (ids: Set<number>) => Set<number>;
    expect([...update(new Set([1, 2, 3, 4]))]).toEqual([2, 4]);
    expect(h.setters[11]).toHaveBeenCalledWith(false);
    expect(h.invalidate).toHaveBeenCalledWith({ queryKey: ["admin-formulas"] });
  });

  it("keeps review reason and cache invalidation separate from deletion", async () => {
    h.id = "19";
    EditFormulaPage();
    await h.mutations[0].mutationFn({ action: "reject", reason: "needs evidence" } as never);
    expect(h.request).toHaveBeenCalledWith("/formulas/19/review", {
      method: "POST", body: '{"action":"reject","rejection_reason":"needs evidence"}',
    });
    h.mutations[0].onSuccess!({ new_status: "rejected" } as never);
    expect(h.invalidate.mock.calls.map(([query]) => query.queryKey)).toEqual([
      ["admin-formulas", 19], ["admin-formulas"],
    ]);
  });

  it("rejects external return destinations and retains the one-second delete feedback", async () => {
    h.id = "19"; h.search = "returnTo=https%3A%2F%2Fexample.invalid%2Fescape";
    EditFormulaPage();
    h.mutations[1].onSuccess!({} as never);
    expect(h.push).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(999);
    expect(h.push).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(h.push).toHaveBeenCalledWith("/formulas");
  });

  it("routes new cards to the existing editor in creation mode", () => {
    const element = NewFormulaPage() as ReactElement<{ mode: string }>;
    expect(element.props.mode).toBe("create");
    expect(element.type).toBe(FormulaEditorForm);
  });

  it("updates categories with PUT and invalidates their own query scope", async () => {
    FormulaCategoriesPage();
    const values = { name: "Fixture", description: null, sort_order: 3, is_active: false };
    await h.mutations[0].mutationFn({ id: 7, values } as never);
    expect(h.request).toHaveBeenCalledWith("/formulas/categories/7", {
      method: "PUT", body: JSON.stringify(values),
    });
    h.mutations[0].onSuccess!({} as never);
    expect(h.invalidate).toHaveBeenCalledWith({ queryKey: ["admin-formula-categories"] });
  });

  it("sends uploaded images as multipart data and deletes only the uploaded source", async () => {
    FormulaGraphAssetPanel({ cardId: 19, canUpdate: true });
    const file = new File(["synthetic"], "fixture.png", { type: "image/png" });
    await h.mutations[0].mutationFn(file as never);
    const [url, options] = h.request.mock.calls[0];
    expect(url).toBe("/formulas/19/graph-assets/upload");
    expect(options.method).toBe("POST");
    expect(options.body).toBeInstanceOf(FormData);
    expect(options.body.get("file")).toBe(file);
    await h.mutations[1].mutationFn();
    expect(h.request).toHaveBeenLastCalledWith("/formulas/19/graph-assets/uploaded", { method: "DELETE" });
  });

  it("confirms a graph with preview token/checksum/version and explicit warning acceptance", async () => {
    h.states[10] = "synthetic-preview"; h.states[11] = "synthetic-checksum"; h.states[14] = true;
    FormulaGraphSpecPanel({ cardId: 19, cardVersion: 4, initialSpec: null, initialStatus: "draft", canUpdate: true });
    await h.mutations[1].mutationFn();
    expect(h.request).toHaveBeenCalledWith("/formulas/19/graph/confirm", {
      method: "POST",
      body: '{"preview_token":"synthetic-preview","checksum":"synthetic-checksum","card_version":4,"accept_warnings":true}',
    });
    h.mutations[1].onSuccess!({} as never);
    expect(h.setters[9]).toHaveBeenCalledWith(null);
    expect(h.setters[10]).toHaveBeenCalledWith(null);
    expect(h.invalidate.mock.calls.map(([query]) => query.queryKey)).toEqual([
      ["admin-formula-graph-assets", 19], ["admin-formulas", 19], ["admin-formulas"],
    ]);
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import CoveragePage from "../coverage/page";
import KnowledgeGraphPage from "../knowledge-graph/page";
import SubjectsPage from "../subjects/page";
import SyllabusPage from "./page";
import type { AdminSubjectNode } from "@/lib/api/types";

type Query = {
  queryKey: unknown[];
  queryFn: () => Promise<unknown>;
  enabled?: boolean;
  retry?: boolean;
  placeholderData?: (data: unknown) => unknown;
};
type Variables = { subject: AdminSubjectNode; nextActive: boolean };
type Context = { previous?: { items: AdminSubjectNode[] }; inactiveAncestors: AdminSubjectNode[] };
type Mutation = {
  mutationFn: (input?: Variables | number) => Promise<unknown>;
  onMutate?: (input: Variables) => Promise<Context>;
  onError?: (error: unknown, input: Variables, context: Context) => void;
  onSuccess: (result: { id: number }, input?: Variables, context?: Context) => Promise<void> | void;
  onSettled?: () => Promise<void>;
};
const h = vi.hoisted(() => ({
  states: [] as unknown[],
  stateIndex: 0,
  setters: [] as ReturnType<typeof vi.fn>[],
  effects: [] as (() => unknown)[],
  queries: [] as Query[],
  mutations: [] as Mutation[],
  data: {} as Record<string, unknown>,
  request: vi.fn(),
  toQuery: vi.fn(() => "?fixture"),
  invalidate: vi.fn(),
  cancel: vi.fn(),
  getData: vi.fn(),
  setData: vi.fn(),
}));

vi.mock("react", async (original) => ({
  ...await original<typeof import("react")>(),
  useMemo: (compute: () => unknown) => compute(),
  useRef: (current: unknown) => ({ current }),
  useEffect: (effect: () => unknown) => { h.effects.push(effect); },
  useState: (initial: unknown) => {
    const index = h.stateIndex++;
    const setter = vi.fn();
    h.setters.push(setter);
    return [index in h.states ? h.states[index] : initial, setter];
  },
}));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({
    invalidateQueries: h.invalidate,
    cancelQueries: h.cancel,
    getQueryData: h.getData,
    setQueryData: h.setData,
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
vi.mock("@/lib/auth/auth-store", () => ({
  useAuthStore: (select: (state: { permissions: string[] }) => unknown) =>
    select({ permissions: ["subject:write", "knowledge:write"] }),
}));
vi.mock("@/lib/api/client", () => ({ apiRequest: h.request, toQuery: h.toQuery }));

beforeEach(() => {
  vi.clearAllMocks();
  h.states = [];
  h.stateIndex = 0;
  h.setters = [];
  h.effects = [];
  h.queries = [];
  h.mutations = [];
  h.data = {};
  h.request.mockReset().mockResolvedValue({ id: 12 });
  h.getData.mockReset();
});

describe("coverage and graph page request contracts", () => {
  it("keeps coverage reports disabled until a version is selected", () => {
    CoveragePage();
    expect(h.queries.map((q) => q.queryKey.slice(0, 2))).toEqual([
      ["syllabus", "versions"], ["knowledge-graph", "subjects"], ["coverage", "report"],
    ]);
    expect(h.queries[2].enabled).toBe(false);
    expect(h.queries.every((q) => q.retry === false)).toBe(true);
  });

  it("sends committed thresholds and only complete years in the coverage scope", async () => {
    h.states = ["12", "4", "unfinished", 21, "2020", "202", "local", "empty"];
    CoveragePage();
    await Promise.all(h.queries.map((q) => q.queryFn()));
    expect(h.toQuery).toHaveBeenCalledWith({
      syllabus_version_id: 12, subject_id: 4, min_questions: 21,
      year_from: 2020, year_to: undefined,
    });
    expect(h.request.mock.calls.map(([path]) => path)).toEqual([
      "/knowledge/syllabus/versions", "/knowledge/subjects", "/coverage/report?fixture",
    ]);
    const previous = { items: [] };
    expect(h.queries[2].placeholderData?.(previous)).toBe(previous);
  });

  it("selects the active coverage version before the first listed version", () => {
    h.data['["syllabus","versions","coverage"]'] = [
      { id: 5, status: "draft" }, { id: 12, status: "active" },
    ];
    CoveragePage();
    h.effects[0]();
    expect(h.setters[0]).toHaveBeenCalledWith("12");
  });

  it("does not request a graph automatically without a subject", () => {
    KnowledgeGraphPage();
    expect(h.queries[1].enabled).toBe(false);
  });

  it.each([
    { center: null, search: "", max: 24 },
    { center: 7, search: "", max: 36 },
    { center: null, search: "alias", max: 36 },
  ])("keeps graph focus/search scope and node budget: %j", async ({ center, search, max }) => {
    h.states = ["4", "parent", "3", "uncommitted", search, false, center];
    KnowledgeGraphPage();
    await h.queries[0].queryFn();
    await h.queries[1].queryFn();
    expect(h.queries[1].queryKey).toEqual(["knowledge-graph", "4", "parent", "3", search, center]);
    expect(h.toQuery).toHaveBeenCalledWith({
      subject_id: 4, relation_type: "parent", knowledge_point_id: center ?? undefined,
      search: search || undefined, depth: 3, max_nodes: max,
    });
    expect(h.request.mock.calls.map(([path]) => path)).toEqual([
      "/knowledge/subjects", "/knowledge/graph?fixture",
    ]);
  });
});

describe("syllabus page mutation contracts", () => {
  function setup() {
    h.states = [12, new Set([9, 2]), {
      code: " next ", name: " next syllabus ", effective_year: 2027, description: " ",
    }, 5, {
      from_syllabus_knowledge_point_id: 41, to_syllabus_knowledge_point_id: 52,
      relation_type: "split", note: " reason ",
    }];
    SyllabusPage();
  }

  it("keeps six version/read scopes independent and disabled without IDs", () => {
    SyllabusPage();
    expect(h.queries.map((q) => q.enabled)).toEqual([undefined, false, false, false, false, false]);
    expect(h.queries.map((q) => q.queryKey[1])).toEqual([
      "versions", "detail", "catalog", "coverage", "mappings", "mapping-source",
    ]);
  });

  it("prefers a draft for editing even if an active version is listed first", () => {
    h.data['["syllabus","versions"]'] = [{ id: 5, status: "active" }, { id: 12, status: "draft" }];
    SyllabusPage();
    h.effects[0]();
    expect(h.setters[0]).toHaveBeenCalledWith(12);
  });

  it("reads the selected version and a separate mapping source version", async () => {
    setup();
    await Promise.all(h.queries.map((q) => q.queryFn()));
    expect(h.request.mock.calls.map(([path]) => path)).toEqual([
      "/knowledge/syllabus/versions", "/knowledge/syllabus/versions/12",
      "/knowledge/syllabus/versions/12/catalog", "/knowledge/syllabus/versions/12/coverage",
      "/knowledge/syllabus/versions/12/mappings", "/knowledge/syllabus/versions/5",
    ]);
  });

  it("trims create/mapping inputs and sorts membership IDs without changing endpoint ownership", async () => {
    setup();
    for (const mutation of h.mutations.slice(0, 5)) await mutation.mutationFn();
    await h.mutations[5].mutationFn(63);
    expect(h.request.mock.calls).toEqual([
      ["/knowledge/syllabus/versions", { method: "POST", body: JSON.stringify({
        code: "next", name: "next syllabus", effective_year: 2027, description: null,
      }) }],
      ["/knowledge/syllabus/versions/12/knowledge-points", {
        method: "PUT", body: JSON.stringify({ knowledge_point_ids: [2, 9] }),
      }],
      ["/knowledge/syllabus/versions/12/activate", { method: "POST" }],
      ["/knowledge/syllabus/versions/12/archive", { method: "POST" }],
      ["/knowledge/syllabus/mappings", { method: "POST", body: JSON.stringify({
        from_syllabus_knowledge_point_id: 41, to_syllabus_knowledge_point_id: 52,
        relation_type: "split", note: "reason",
      }) }],
      ["/knowledge/syllabus/mappings/63", { method: "DELETE" }],
    ]);
  });

  it("selects a created version and invalidates every dependent read scope", async () => {
    setup();
    await h.mutations[0].onSuccess({ id: 13 });
    expect(h.setters[0]).toHaveBeenCalledWith(13);
    expect(h.invalidate.mock.calls.map(([q]) => q.queryKey)).toEqual([
      ["syllabus", "versions"], ["syllabus", "detail"], ["syllabus", "catalog"],
      ["syllabus", "coverage"], ["syllabus", "mappings"], ["syllabus", "mapping-source"],
    ]);
  });

  it("propagates rejected writes without running success invalidation", async () => {
    setup();
    const error = new Error("write rejected");
    h.request.mockRejectedValue(error);
    await expect(h.mutations[1].mutationFn()).rejects.toBe(error);
    expect(h.invalidate).not.toHaveBeenCalled();
  });
});

describe("subject page optimistic mutation contracts", () => {
  const child: AdminSubjectNode = {
    id: 2, code: "data_structure", name: "Data", level: 2, path: "/exam408/data_structure",
    parent_id: 1, sort_order: 1, is_active: false, created_at: "", updated_at: "", children: [],
  };
  const root: AdminSubjectNode = {
    ...child, id: 1, code: "exam408", name: "408", level: 1, path: "/exam408",
    parent_id: null, is_product_root: true, children: [child],
  };

  it("requires explicit confirmation only when disabling the product root", async () => {
    SubjectsPage();
    await h.queries[0].queryFn();
    await h.mutations[0].mutationFn({ subject: root, nextActive: false });
    await h.mutations[0].mutationFn({ subject: child, nextActive: true });
    expect(h.request.mock.calls).toEqual([
      ["/subjects?include_inactive=true"],
      ["/subjects/1", { method: "PATCH", body: JSON.stringify({ is_active: false, confirm_core_disable: true }) }],
      ["/subjects/2", { method: "PATCH", body: JSON.stringify({ is_active: true }) }],
    ]);
  });

  it("cancels reads before optimistic ancestor activation and restores the exact snapshot on error", async () => {
    const previous = { items: [root] };
    h.getData.mockReturnValue(previous);
    SubjectsPage();
    const input = { subject: child, nextActive: true };
    const mutation = h.mutations[0];
    let release!: () => void;
    h.cancel.mockReturnValueOnce(new Promise<void>((resolve) => { release = resolve; }));
    const pending = mutation.onMutate!(input);
    expect(h.getData).not.toHaveBeenCalled();
    expect(h.setData).not.toHaveBeenCalled();
    release();
    const context = await pending;
    expect(h.cancel).toHaveBeenCalledWith({ queryKey: ["subjects", "include-inactive"] });
    expect(h.cancel.mock.invocationCallOrder[0]).toBeLessThan(h.getData.mock.invocationCallOrder[0]);
    expect(context.inactiveAncestors).toEqual([root]);
    const optimistic = h.setData.mock.calls[0][1];
    expect(optimistic.items[0].is_active).toBe(true);
    expect(optimistic.items[0].children[0].is_active).toBe(true);
    expect(previous.items[0].is_active).toBe(false);
    mutation.onError!(new Error("rejected"), input, context);
    expect(h.setData.mock.lastCall?.[1]).toBe(previous);
    await mutation.onSettled!();
    expect(h.invalidate).toHaveBeenCalledWith({ queryKey: ["subjects"] });
  });
});

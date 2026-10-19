import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider, QueryObserver } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchQuestionDetail, fetchQuestions, fetchQuestionVersionDetail, fetchQuestionVersions,
} from "./question-api";
import {
  questionDetailOptions, questionKeys, questionListOptions,
  questionVersionOptions, questionVersionsOptions,
} from "./question-queries";
import {
  useQuestionDetail, useQuestionList, useQuestionVersion, useQuestionVersions,
} from "./hooks/use-question-queries";
import type { AdminQuestionDetail, QuestionVersionDetail } from "@/lib/api/types";

vi.mock("./question-api", () => ({
  fetchQuestionDetail: vi.fn(), fetchQuestions: vi.fn(),
  fetchQuestionVersionDetail: vi.fn(), fetchQuestionVersions: vi.fn(),
}));

const params = {
  page: 1, page_size: 20, is_active: "", question_type: "", keyword: "", year: "",
};
const clients: QueryClient[] = [];
const subscriptions: Array<() => void> = [];
function client() {
  const value = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } });
  clients.push(value);
  return value;
}
function version(questionId: number, revision: number) {
  return { question_id: questionId, version: revision } as QuestionVersionDetail;
}

afterEach(() => {
  subscriptions.splice(0).forEach((unsubscribe) => unsubscribe());
  clients.splice(0).forEach((value) => value.clear());
  vi.resetAllMocks();
});

describe("question query cache ownership", () => {
  it("keeps the deployed list/detail/version keys and invalidation prefixes", () => {
    expect(questionKeys.all).toEqual(["questions"]);
    expect(questionKeys.scope(7)).toEqual(["questions", 7]);
    expect(questionListOptions(params).queryKey).toEqual(["questions", params]);
    expect(questionDetailOptions(7).queryKey).toEqual(["questions", 7, "detail"]);
    expect(questionVersionsOptions(7).queryKey).toEqual(["questions", 7, "versions"]);
    expect(questionVersionOptions(7, 2).queryKey).toEqual(["questions", 7, "versions", 2]);
    expect(questionVersionOptions(null, "current").queryKey)
      .toEqual(["questions", null, "versions", "current"]);
  });

  it("shares prefetched detail while the observer revalidates under its own policy", async () => {
    const cache = client();
    const data = { id: 7 } as AdminQuestionDetail;
    vi.mocked(fetchQuestionDetail).mockResolvedValueOnce(data)
      .mockImplementation(() => new Promise(() => {}));
    await cache.prefetchQuery({ ...questionDetailOptions(7), staleTime: 30_000 });
    const observer = new QueryObserver(cache, {
      ...questionDetailOptions(7), enabled: true, retry: false,
    });
    subscriptions.push(observer.subscribe(() => {}));
    expect(observer.getCurrentResult().data).toBe(data);
    expect(observer.getCurrentResult().isFetching).toBe(true);
    expect(fetchQuestionDetail).toHaveBeenCalledTimes(2);
    expect(vi.mocked(fetchQuestionDetail).mock.calls).toEqual([[7], [7]]);
  });

  it("invalidates only the selected question scope before the whole list prefix", async () => {
    const cache = client();
    const keys = [
      questionKeys.list(params), questionKeys.detail(7), questionKeys.versions(7),
      questionKeys.version(7, 2), questionKeys.detail(8), ["subjects"],
    ];
    keys.forEach((key) => cache.setQueryData(key, {}));
    await cache.invalidateQueries({ queryKey: questionKeys.scope(7) });
    expect(keys.map((key) => cache.getQueryState(key)?.isInvalidated))
      .toEqual([false, true, true, true, false, false]);
    await cache.invalidateQueries({ queryKey: questionKeys.all });
    expect(keys.map((key) => cache.getQueryState(key)?.isInvalidated))
      .toEqual([true, true, true, true, true, false]);
  });

  it("keeps the previous list during a filter/page change", async () => {
    const cache = client();
    const data = { items: [{ id: 7 }] };
    cache.setQueryData(questionKeys.list(params), data);
    vi.mocked(fetchQuestions).mockImplementation(() => new Promise(() => {}));
    const observer = new QueryObserver(cache, questionListOptions(params));
    subscriptions.push(observer.subscribe(() => {}));
    observer.setOptions(questionListOptions({ ...params, page: 2, keyword: "new" }));
    expect(observer.getCurrentResult().data).toBe(data);
    expect(observer.getCurrentResult().isPlaceholderData).toBe(true);
  });

  it("keeps historical placeholder data for the same question only", () => {
    const cache = client();
    const previous = version(7, 1);
    cache.setQueryData(questionKeys.version(7, 1), previous);
    vi.mocked(fetchQuestionVersionDetail).mockImplementation(() => new Promise(() => {}));
    const observer = new QueryObserver(cache, questionVersionOptions(7, 1));
    subscriptions.push(observer.subscribe(() => {}));
    observer.setOptions(questionVersionOptions(7, 2));
    expect(observer.getCurrentResult().data).toBe(previous);
    expect(observer.getCurrentResult().isPlaceholderData).toBe(true);
    observer.setOptions(questionVersionOptions(8, 2));
    expect(observer.getCurrentResult().data).toBeUndefined();
    expect(observer.getCurrentResult().isPlaceholderData).toBe(false);
  });

  it.each([[null, 2], [7, "current"], [7, null]] as const)(
    "disables historical fetch for question %s version %s", (id, revision) => {
      const observer = new QueryObserver(client(), questionVersionOptions(id, revision));
      subscriptions.push(observer.subscribe(() => {}));
      expect(observer.getCurrentResult().fetchStatus).toBe("idle");
      expect(fetchQuestionVersionDetail).not.toHaveBeenCalled();
    },
  );

  it("disables the version history until a question is selected", () => {
    const observer = new QueryObserver(client(), questionVersionsOptions(null));
    subscriptions.push(observer.subscribe(() => {}));
    expect(fetchQuestionVersions).not.toHaveBeenCalled();
    expect(observer.getCurrentResult().fetchStatus).toBe("idle");
  });

  it("calls the history and historical version providers with unchanged arguments", async () => {
    const cache = client();
    const history = { items: [], total: 0 } as unknown as Awaited<ReturnType<typeof fetchQuestionVersions>>;
    const historical = version(7, 2);
    vi.mocked(fetchQuestionVersions).mockResolvedValue(history);
    vi.mocked(fetchQuestionVersionDetail).mockResolvedValue(historical);
    expect(await cache.fetchQuery(questionVersionsOptions(7))).toBe(history);
    expect(await cache.fetchQuery(questionVersionOptions(7, 2))).toBe(historical);
    expect(fetchQuestionVersions).toHaveBeenCalledExactlyOnceWith(7);
    expect(fetchQuestionVersionDetail).toHaveBeenCalledExactlyOnceWith(7, 2);
  });

  it("propagates list errors with no automatic retry", async () => {
    const error = new Error("forbidden");
    vi.mocked(fetchQuestions).mockRejectedValue(error);
    await expect(client().fetchQuery(questionListOptions(params))).rejects.toBe(error);
    expect(fetchQuestions).toHaveBeenCalledExactlyOnceWith(params);
  });
});

describe("question hooks use the feature queries", () => {
  it("reads all five cached query results through the real hooks", () => {
    const cache = client();
    cache.setQueryData(questionKeys.list(params), { items: [], total: 12 });
    cache.setQueryData(questionKeys.detail(7), { id: 7 });
    cache.setQueryData(questionKeys.versions(7), { items: [{ version: 2 }] });
    cache.setQueryData(questionKeys.version(7, 1), version(7, 1));
    cache.setQueryData(questionKeys.version(7, 2), version(7, 2));
    function Probe() {
      const list = useQuestionList(params);
      const detail = useQuestionDetail(7);
      const history = useQuestionVersions(7);
      const base = useQuestionVersion(7, 1);
      const compare = useQuestionVersion(7, 2);
      return createElement("span", null, [
        list.data?.total, detail.data?.id, history.data?.items[0].version,
        base.data?.version, compare.data?.version,
      ].join(","));
    }
    expect(renderToStaticMarkup(createElement(QueryClientProvider, { client: cache },
      createElement(Probe)))).toBe("<span>12,7,2,1,2</span>");
  });

  it("keeps an unselected detail idle without fetching", () => {
    function Probe() {
      return createElement("span", null, useQuestionDetail(null).fetchStatus);
    }
    expect(renderToStaticMarkup(createElement(QueryClientProvider, { client: client() },
      createElement(Probe)))).toBe("<span>idle</span>");
    expect(fetchQuestionDetail).not.toHaveBeenCalled();
  });
});

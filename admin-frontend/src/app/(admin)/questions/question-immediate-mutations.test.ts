import { createElement, type SetStateAction } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AdminQuestion, AdminQuestionDetail, QuestionEditRequest } from "@/lib/api/types";
import { updateQuestion } from "./question-api";
import { useQuestionImmediateMutations } from "./hooks/use-question-immediate-mutations";
import { questionKeys } from "./question-queries";

vi.mock("./question-api", () => ({ updateQuestion: vi.fn() }));
const question: AdminQuestion = {
  id: 7, question_type: "judge", answer: "A", difficulty: 2,
  content: { stem: "stem" }, review_status: "approved", is_active: true,
};
const input = {
  questionId: 7, question, dirty: true, stemText: "stem",
  form: { question_type: "judge", answer: "B", difficulty: 2, content: question.content },
  unresolvedTableCount: 0, emptyCodeCount: 0,
};
const clients: QueryClient[] = [];
function setup(state: Parameters<typeof useQuestionImmediateMutations>[0] = input) {
  const cache = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } });
  clients.push(cache);
  const feedback = { setForm: vi.fn(), setStemText: vi.fn(), setMessage: vi.fn() };
  const selectedQuestionId = { current: state.questionId };
  let hook!: ReturnType<typeof useQuestionImmediateMutations>;
  function Probe() {
    hook = useQuestionImmediateMutations(state, feedback, selectedQuestionId);
    return null;
  }
  renderToStaticMarkup(createElement(QueryClientProvider, { client: cache }, createElement(Probe)));
  return { cache, feedback, hook, selectedQuestionId };
}
function deferred() {
  let resolve!: (value: AdminQuestion) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<AdminQuestion>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
afterEach(() => {
  clients.splice(0).forEach((cache) => cache.clear());
  vi.restoreAllMocks();
  vi.resetAllMocks();
});

describe("question immediate writes", () => {
  it("lets a clean draft proceed without validating or issuing a request", async () => {
    const { hook, feedback } = setup({
      ...input, dirty: false, questionId: null, question: null,
      unresolvedTableCount: 1, emptyCodeCount: 1,
    });
    expect(await hook.prepareImmediateQuestionMutation()).toBeNull();
    expect(updateQuestion).not.toHaveBeenCalled();
    expect(feedback.setMessage).not.toHaveBeenCalled();
  });

  it.each([
    [{ questionId: null, question: null, unresolvedTableCount: 1, emptyCodeCount: 1 },
      "未选中题目，无法保存当前修改。"],
    [{ question: null, unresolvedTableCount: 1, emptyCodeCount: 1 },
      "请先完成结构化表格核验，再继续图片或选项操作。"],
    [{ question: null, emptyCodeCount: 1 }, "请先填写或删除空代码块，再继续图片或选项操作。"],
    [{ question: null }, "题目详情尚未加载完成，无法保存当前修改。"],
  ])("keeps guard order and rejects before saving: %s", async (patch, message) => {
    const { hook, feedback, cache } = setup({ ...input, ...patch });
    const invalidate = vi.spyOn(cache, "invalidateQueries");
    expect(await hook.prepareImmediateQuestionMutation()).toBeNull();
    expect(feedback.setMessage).toHaveBeenCalledExactlyOnceWith(message);
    expect(updateQuestion).not.toHaveBeenCalled();
    expect(feedback.setForm).not.toHaveBeenCalled();
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("continues if a dirty flag resolves to an empty minimal PATCH", async () => {
    const { hook, feedback } = setup({ ...input, form: { ...input.form, answer: "A" } });
    expect(await hook.prepareImmediateQuestionMutation()).toEqual({ questionId: 7, generation: 1 });
    expect(updateQuestion).not.toHaveBeenCalled();
    expect(feedback.setMessage).not.toHaveBeenCalled();
  });

  it("saves once for concurrent operations and applies response/cache/feedback in order", async () => {
    const request = deferred();
    vi.mocked(updateQuestion).mockReturnValue(request.promise);
    const { hook, feedback, cache } = setup();
    const metadata = { id: 9, batch_id: "batch" };
    cache.setQueryData(questionKeys.detail(7), { ...question, import_record: metadata });
    const events: unknown[] = [];
    feedback.setForm.mockImplementation((form) => {
      expect(cache.getQueryData<AdminQuestionDetail>(questionKeys.detail(7))?.answer).toBe("B");
      events.push(form);
    });
    feedback.setStemText.mockImplementation((stem) => { events.push(stem); });
    feedback.setMessage.mockImplementation((message) => { events.push(message); });
    vi.spyOn(cache, "invalidateQueries").mockImplementation(async (filters) => {
      events.push(filters?.queryKey);
    });
    const first = hook.prepareImmediateQuestionMutation();
    const second = hook.prepareImmediateQuestionMutation();
    expect(updateQuestion).toHaveBeenCalledExactlyOnceWith(7, { answer: "B" });
    const saved = { ...question, answer: "B", content: { stem: "server stem" }, options: { A: "new" } };
    request.resolve(saved);
    const owner = { questionId: 7, generation: 1 };
    expect(await Promise.all([first, second])).toEqual([owner, owner]);
    expect(events).toEqual([
      { subject_id: null, question_type: "judge", difficulty: 2, answer: "B", analysis: "",
        options: { A: "new" }, content: { stem: "server stem" }, knowledge_points: undefined },
      "server stem", questionKeys.all, questionKeys.scope(7),
      "已先保存当前修改，将继续执行该操作。",
    ]);
    expect(cache.getQueryData(questionKeys.detail(7))).toEqual({ ...saved, import_record: metadata });
    expect(await hook.prepareImmediateQuestionMutation()).toEqual({
      questionId: 7, generation: 2,
    });
    expect(updateQuestion).toHaveBeenCalledTimes(2);
  });

  it.each([new Error("conflict"), "offline"])(
    "keeps the draft/cache after failure and permits retry: %s", async (error) => {
      const request = deferred();
      vi.mocked(updateQuestion).mockReturnValueOnce(request.promise).mockResolvedValue(question);
      const { hook, feedback, cache } = setup();
      cache.setQueryData(questionKeys.detail(7), question);
      const invalidate = vi.spyOn(cache, "invalidateQueries");
      const first = hook.prepareImmediateQuestionMutation();
      const second = hook.prepareImmediateQuestionMutation();
      request.reject(error);
      expect(await Promise.all([first, second])).toEqual([null, null]);
      expect(feedback.setMessage).toHaveBeenCalledExactlyOnceWith(error instanceof Error
        ? "当前修改保存失败：conflict" : "当前修改保存失败，请稍后重试。");
      expect(feedback.setForm).not.toHaveBeenCalled();
      expect(cache.getQueryData(questionKeys.detail(7))).toBe(question);
      expect(invalidate).not.toHaveBeenCalled();
    expect(await hook.prepareImmediateQuestionMutation()).toEqual({
      questionId: 7, generation: 2,
    });
      expect(updateQuestion).toHaveBeenCalledTimes(2);
    },
  );

  it("keeps single-flight ownership separate between page instances", async () => {
    const request = deferred();
    vi.mocked(updateQuestion).mockReturnValue(request.promise);
    const first = setup().hook;
    const second = setup().hook;
    const results = [first.prepareImmediateQuestionMutation(), second.prepareImmediateQuestionMutation()];
    expect(updateQuestion).toHaveBeenCalledTimes(2);
    request.resolve(question);
    expect(await Promise.all(results)).toEqual([
      { questionId: 7, generation: 1 },
      { questionId: 7, generation: 1 },
    ]);
  });

  it("adopts immediate writes without discarding other local edits or detail metadata", () => {
    const { hook, feedback, cache } = setup();
    const metadata = { id: 9 };
    cache.setQueryData(questionKeys.detail(7), { ...question, import_record: metadata });
    const events: unknown[] = [];
    vi.spyOn(cache, "invalidateQueries").mockImplementation(async (filters) => {
      events.push(filters?.queryKey);
    });
    const saved = { ...question, content: { stem: "new", image_url: "image" }, options: null };
    hook.handleQuestionMutated(saved);
    const updater = feedback.setForm.mock.calls[0][0] as SetStateAction<QuestionEditRequest>;
    expect(typeof updater).toBe("function");
    if (typeof updater !== "function") throw new Error("Expected functional form update");
    expect(updater({ ...input.form, analysis: "local", knowledge_points: ["local"] })).toEqual({
      ...input.form, content: saved.content, options: undefined,
      analysis: "local", knowledge_points: ["local"],
    });
    expect(cache.getQueryData(questionKeys.detail(7))).toEqual({ ...saved, import_record: metadata });
    expect(events).toEqual([questionKeys.scope(7), questionKeys.all]);
    expect(feedback.setStemText).not.toHaveBeenCalled();
    expect(feedback.setMessage).not.toHaveBeenCalled();
  });

  it("seeds an absent detail cache without assigning it to a null form", () => {
    const first = setup();
    first.hook.handleQuestionMutated(question);
    expect(first.cache.getQueryData(questionKeys.detail(7))).toEqual(question);
    const second = setup({ ...input, questionId: null });
    second.hook.handleQuestionMutated(question);
    expect(second.cache.getQueryData(questionKeys.detail(7))).toEqual(question);
    expect(second.feedback.setForm).not.toHaveBeenCalled();
  });

  it("retains the existing null import-record fallback when the detail cache exists", () => {
    const { hook, cache } = setup();
    cache.setQueryData(questionKeys.detail(7), question);
    hook.handleQuestionMutated(question);
    expect(cache.getQueryData(questionKeys.detail(7))).toEqual({ ...question, import_record: null });
  });

  it("does not apply an unowned mismatch to the current form", () => {
    const { hook, feedback, cache } = setup({
      ...input, questionId: 8, question: { ...question, id: 8 },
    });
    const staleQuestion = { ...question, content: { stem: "old image" } };
    const currentQuestion = { ...question, id: 8, content: { stem: "new question" } };
    cache.setQueryData(questionKeys.detail(8), currentQuestion);

    hook.handleQuestionMutated(staleQuestion);

    expect(cache.getQueryData(questionKeys.detail(7))).toEqual(staleQuestion);
    expect(cache.getQueryData(questionKeys.detail(8))).toEqual(currentQuestion);
    expect(feedback.setForm).not.toHaveBeenCalled();
    expect(feedback.setMessage).toHaveBeenCalledOnce();
  });

  it("invalidates an unselected response without applying it to the form", () => {
    const { hook, feedback, cache } = setup({
      ...input, questionId: null, question: null,
    });
    hook.handleQuestionMutated({ ...question, content: { stem: "server stem" } });
    expect(feedback.setForm).not.toHaveBeenCalled();
    expect(feedback.setMessage).not.toHaveBeenCalled();
    expect(cache.getQueryData(questionKeys.detail(7))).toEqual({
      ...question,
      content: { stem: "server stem" },
    });
  });
});

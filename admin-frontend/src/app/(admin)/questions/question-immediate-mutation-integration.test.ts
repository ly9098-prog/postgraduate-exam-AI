import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AdminQuestion, QuestionEditRequest } from "@/lib/api/types";
import { updateQuestion } from "./question-api";
import { useQuestionImmediateMutations } from "./hooks/use-question-immediate-mutations";
import { questionKeys } from "./question-queries";

vi.mock("./question-api", () => ({ updateQuestion: vi.fn() }));

const question7: AdminQuestion = {
  id: 7, question_type: "single_choice", answer: "A", difficulty: 2,
  content: { stem: "question seven" }, review_status: "approved", is_active: true,
};
const question8 = { ...question7, id: 8, content: { stem: "question eight" } };
const form7: QuestionEditRequest = {
  question_type: "single_choice", answer: "B", difficulty: 2, content: question7.content,
};
const clients: QueryClient[] = [];

function setup(initialId: number, question: AdminQuestion, form: QuestionEditRequest) {
  const cache = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } });
  clients.push(cache);
  const feedback = { setForm: vi.fn(), setStemText: vi.fn(), setMessage: vi.fn() };
  const selectedQuestionId = { current: initialId as number | null };
  let latest!: ReturnType<typeof useQuestionImmediateMutations>;
  let current = { id: initialId, question, form };
  function Probe() {
    latest = useQuestionImmediateMutations({
      questionId: current.id,
      question: current.question,
      dirty: true,
      form: current.form,
      stemText: String(current.question.content?.stem ?? ""),
      unresolvedTableCount: 0,
      emptyCodeCount: 0,
    }, feedback, selectedQuestionId);
    return null;
  }
  const render = () => renderToStaticMarkup(
    createElement(QueryClientProvider, { client: cache }, createElement(Probe)),
  );
  render();
  return {
    cache,
    feedback,
    get hook() { return latest; },
    switchTo(id: number, nextQuestion: AdminQuestion, form: QuestionEditRequest) {
      selectedQuestionId.current = id;
      current = { id, question: nextQuestion, form };
      render();
    },
    closeSelection() {
      selectedQuestionId.current = null;
    },
  };
}

afterEach(() => {
  clients.splice(0).forEach((cache) => cache.clear());
  vi.resetAllMocks();
});

describe("delayed question immediate writes", () => {
  it("rejects a draft save that finishes after switching questions", async () => {
    let resolveUpdate!: (value: AdminQuestion) => void;
    vi.mocked(updateQuestion).mockReturnValue(new Promise<AdminQuestion>((resolve) => {
      resolveUpdate = resolve;
    }));
    const ui = setup(7, question7, form7);
    const preparing = ui.hook.prepareImmediateQuestionMutation();
    ui.cache.setQueryData(questionKeys.detail(8), question8);
    ui.switchTo(8, question8, {
      ...form7, answer: "C", content: question8.content,
    });

    resolveUpdate({ ...question7, answer: "B", content: { stem: "old saved" } });

    expect(await preparing).toBeNull();
    expect(ui.feedback.setForm).not.toHaveBeenCalled();
    expect(ui.feedback.setMessage).toHaveBeenCalledWith(
      "题目已切换，已保存原题修改；请重新执行图片或选项操作。",
    );
    expect(ui.cache.getQueryData(questionKeys.detail(7))).toMatchObject({
      answer: "B",
      content: { stem: "old saved" },
    });
    expect(ui.cache.getQueryData(questionKeys.detail(8))).toEqual(question8);
  });

  it("updates the old detail without applying a stale response to the new form", async () => {
    const ui = setup(7, question7, form7);
    const owner = await ui.hook.prepareImmediateQuestionMutation();
    ui.cache.setQueryData(questionKeys.detail(8), question8);
    ui.switchTo(8, question8, {
      ...form7, answer: "C", content: question8.content,
    });

    ui.hook.handleQuestionMutated(
      { ...question7, content: { stem: "old image saved" } }, owner ?? undefined,
    );

    expect(ui.feedback.setForm).not.toHaveBeenCalled();
    expect(ui.feedback.setMessage).toHaveBeenCalledTimes(2);
    expect(ui.cache.getQueryData(questionKeys.detail(7))).toMatchObject({
      content: { stem: "old image saved" },
    });
    expect(ui.cache.getQueryData(questionKeys.detail(8))).toEqual(question8);
  });

  it("keeps late option responses out of the newly selected question", async () => {
    const ui = setup(7, question7, form7);
    const owner = await ui.hook.prepareImmediateQuestionMutation();
    ui.switchTo(8, question8, { ...form7, content: question8.content });
    ui.hook.handleQuestionMutated(
      { ...question7, options: { A: "late option" } }, owner ?? undefined,
    );

    expect(ui.feedback.setForm).not.toHaveBeenCalled();
    expect(ui.feedback.setMessage).toHaveBeenCalledTimes(2);
    expect(ui.cache.getQueryData(questionKeys.detail(8))).toBeUndefined();
  });

  it("invalidates the old detail when a response arrives after closing the drawer", async () => {
    vi.mocked(updateQuestion).mockResolvedValue({ ...question7, answer: "B" });
    const ui = setup(7, question7, form7);
    const owner = await ui.hook.prepareImmediateQuestionMutation();
    ui.feedback.setForm.mockClear();
    ui.feedback.setMessage.mockClear();
    ui.cache.setQueryData(questionKeys.detail(7), question7);
    ui.closeSelection();

    ui.hook.handleQuestionMutated(
      { ...question7, content: { stem: "saved after close" } },
      owner ?? undefined,
    );

    expect(ui.feedback.setForm).not.toHaveBeenCalled();
    expect(ui.feedback.setMessage).not.toHaveBeenCalled();
    expect(ui.cache.getQueryData(questionKeys.detail(7))).toMatchObject({
      content: { stem: "saved after close" },
    });
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest, apiRequestBlob } from "@/lib/api/client";
import {
  deleteQuestion, deleteQuestionBatch, exportQuestions, fetchQuestionDetail,
  fetchQuestions, fetchQuestionVersionDetail, fetchQuestionVersions, fetchSubjectOptions,
  updateQuestion, type QuestionQueryParams,
} from "./question-api";

vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/api/client")>(),
  apiRequest: vi.fn(),
  apiRequestBlob: vi.fn(),
}));

const request = vi.mocked(apiRequest);
const blobRequest = vi.mocked(apiRequestBlob);
const params: QuestionQueryParams = {
  page: 2, page_size: 50, subject_id: 3, is_active: "false", question_type: "choice",
  keyword: "C++ & 空格", year: "2025", difficulty: 2, import_batch_id: "batch/x",
  knowledge_point_id: 9,
};

beforeEach(() => vi.resetAllMocks());

describe("question read protocol", () => {
  it("preserves list parameter order, encoding and response identity", async () => {
    const response = { items: [{ id: 1 }] };
    request.mockResolvedValue(response);
    expect(await fetchQuestions(params)).toBe(response);
    expect(request).toHaveBeenCalledExactlyOnceWith(
      "/questions?page=2&page_size=50&subject_id=3&is_active=false&question_type=choice&keyword=C%2B%2B+%26+%E7%A9%BA%E6%A0%BC&year=2025&difficulty=2&import_batch_id=batch%2Fx&knowledge_point_id=9",
    );
  });

  it("omits empty/undefined filters without removing numeric zero", async () => {
    await fetchQuestions({
      page: 1, page_size: 20, is_active: "", question_type: "", keyword: "", year: "",
      difficulty: 0,
    });
    expect(request).toHaveBeenCalledWith("/questions?page=1&page_size=20&difficulty=0");
  });

  it.each(["true", "false", ""])("preserves active filter %j", async (is_active) => {
    await fetchQuestions({ ...params, is_active });
    const path = request.mock.calls[0][0];
    expect(new URL(path, "https://test.local").searchParams.get("is_active"))
      .toBe(is_active || null);
  });

  it("uses the same detail endpoint for fetching and prefetching", async () => {
    const response = { id: 7, import_record: { id: 8 } };
    request.mockResolvedValue(response);
    expect(await fetchQuestionDetail(7)).toBe(response);
    expect(request).toHaveBeenCalledExactlyOnceWith("/questions/7");
  });

  it("reads a specific historical version", async () => {
    const response = { question_id: 7, version: 2 };
    request.mockResolvedValue(response);
    expect(await fetchQuestionVersionDetail(7, 2)).toBe(response);
    expect(request).toHaveBeenCalledExactlyOnceWith("/questions/7/versions/2");
  });

  it.each([0, 1])("returns the first version page unchanged for %i pages", async (total_pages) => {
    const response = { items: [], total_pages, total: 0, page: 1, page_size: 100 };
    request.mockResolvedValue(response);
    expect(await fetchQuestionVersions(7)).toBe(response);
    expect(request).toHaveBeenCalledExactlyOnceWith("/questions/7/versions?page=1&page_size=100");
  });

  it("starts remaining version pages in parallel and merges in page order", async () => {
    let finishSecond!: (value: unknown) => void;
    const first = { items: [{ version: 5 }], total_pages: 3, total: 3, page: 1, page_size: 100 };
    request.mockResolvedValueOnce(first)
      .mockImplementationOnce(() => new Promise((resolve) => { finishSecond = resolve; }))
      .mockResolvedValueOnce({ items: [{ version: 1 }] });
    const pending = fetchQuestionVersions(7);
    await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(3));
    expect(request.mock.calls.map(([path]) => path)).toEqual([
      "/questions/7/versions?page=1&page_size=100",
      "/questions/7/versions?page=2&page_size=100",
      "/questions/7/versions?page=3&page_size=100",
    ]);
    finishSecond({ items: [{ version: 3 }] });
    expect(await pending).toEqual({ ...first, items: [{ version: 5 }, { version: 3 }, { version: 1 }] });
  });

  it.each([0, 1])("propagates version page failure at index %i", async (index) => {
    const error = new Error("version unavailable");
    if (index) request.mockResolvedValueOnce({ items: [], total_pages: 2 });
    request.mockRejectedValueOnce(error);
    await expect(fetchQuestionVersions(7)).rejects.toBe(error);
    expect(request).toHaveBeenCalledTimes(index + 1);
  });

  it("flattens subjects in depth-first order and keeps original fields", async () => {
    const leaf = { id: 3, code: "c", name: "C", level: 3, path: "a/b/c" };
    const child = { id: 2, code: "b", name: "B", level: 2, path: "a/b", children: [leaf] };
    request.mockResolvedValue({ items: [{ id: 1, level: 1, children: [child] }, { id: 4, level: 0 }] });
    expect(await fetchSubjectOptions()).toEqual([child, leaf]);
    expect(request).toHaveBeenCalledExactlyOnceWith("/subjects");
  });

  it("accepts an absent subject list", async () => {
    request.mockResolvedValue({});
    expect(await fetchSubjectOptions()).toEqual([]);
  });
});

describe("question write protocol", () => {
  it("serializes the patch without changing fields or returned metadata", async () => {
    const patch = { answer: "A", subject_id: null, content: { text: "new" }, analysis: undefined };
    const response = { id: 7, content: { text: "new" } };
    request.mockResolvedValue(response);
    expect(await updateQuestion(7, patch)).toBe(response);
    expect(request).toHaveBeenCalledExactlyOnceWith("/questions/7", {
      method: "PATCH", body: JSON.stringify(patch),
    });
  });

  it("uses the existing single delete protocol", async () => {
    const response = { status: "deleted" };
    request.mockResolvedValue(response);
    expect(await deleteQuestion(7)).toBe(response);
    expect(request).toHaveBeenCalledExactlyOnceWith("/questions/7", { method: "DELETE" });
  });

  it.each(["update", "delete", "detail", "subjects"])("propagates %s errors unchanged", async (kind) => {
    const error = new Error("no permission");
    request.mockRejectedValue(error);
    const task = kind === "update" ? updateQuestion(7, {}) : kind === "delete"
      ? deleteQuestion(7) : kind === "detail" ? fetchQuestionDetail(7) : fetchSubjectOptions();
    await expect(task).rejects.toBe(error);
  });

  it.each([0, 1, 49, 50, 51, 100, 101])("chunks %i selections at 50 without changing order", async (count) => {
    const ids = Array.from({ length: count }, (_, i) => count - i);
    const original = [...ids];
    const key = vi.fn((chunk: number[]) => chunk.join("-"));
    request.mockImplementation(async (_path, init) => ({ success_ids: JSON.parse(init!.body as string).ids }));
    expect(await deleteQuestionBatch(ids, key)).toEqual({ success_ids: ids, failed_items: [] });
    expect(request).toHaveBeenCalledTimes(Math.ceil(count / 50));
    request.mock.calls.forEach(([path, init], i) => {
      const chunk = ids.slice(i * 50, (i + 1) * 50);
      expect([path, init]).toEqual(["/questions/batch-delete", {
        method: "POST", headers: { "Idempotency-Key": chunk.join("-") }, body: JSON.stringify({ ids: chunk }),
      }]);
    });
    expect(key).toHaveBeenCalledTimes(Math.ceil(count / 50));
    expect(ids).toEqual(original);
  });

  it("keeps chunk requests sequential", async () => {
    let finish!: (value: unknown) => void;
    request.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValueOnce({ successIds: [51] });
    const pending = deleteQuestionBatch(Array.from({ length: 51 }, (_, i) => i + 1), () => "key");
    expect(request).toHaveBeenCalledTimes(1);
    finish({ success_ids: [1] });
    expect(await pending).toEqual({ success_ids: [1, 51], failed_items: [] });
    expect(request).toHaveBeenCalledTimes(2);
  });

  it("prefers snake_case even when empty and accepts camelCase fallback", async () => {
    request.mockResolvedValueOnce({ success_ids: [], successIds: [1], failed_items: [], failedItems: [{ id: 2 }] })
      .mockResolvedValueOnce({ successIds: [51], failedItems: [{ id: 52, error: "blocked" }] });
    const result = await deleteQuestionBatch(Array.from({ length: 51 }, (_, i) => i + 1), () => "key");
    expect(result).toEqual({ success_ids: [51], failed_items: [{ id: 52, error: "blocked" }] });
  });

  it.each([new Error("network"), "unknown"])("records chunk failure and continues: %j", async (error) => {
    request.mockRejectedValueOnce(error).mockResolvedValueOnce({ success_ids: [51] });
    const result = await deleteQuestionBatch(Array.from({ length: 51 }, (_, i) => i + 1), () => "same-key");
    expect(result.success_ids).toEqual([51]);
    expect(result.failed_items).toEqual(Array.from({ length: 50 }, (_, i) => ({
      id: i + 1, error: error instanceof Error ? error.message : "批量删除请求失败",
    })));
  });

  it("handles an empty result and a key factory failure like the original flow", async () => {
    request.mockResolvedValueOnce({});
    expect(await deleteQuestionBatch([1], () => "key")).toEqual({ success_ids: [], failed_items: [] });
    const key = () => { throw new Error("key unavailable"); };
    expect(await deleteQuestionBatch([2], key)).toEqual({
      success_ids: [], failed_items: [{ id: 2, error: "key unavailable" }],
    });
    expect(request).toHaveBeenCalledTimes(1);
  });

  it.each(["csv", "docx"] as const)("preserves %s export payload and long timeout", async (format) => {
    const payload = { format, ids: [3, 1], is_active: false, keyword: "x", subject_id: undefined };
    const response = { blob: new Blob(["data"]), filename: "x", mediaType: "test" };
    blobRequest.mockResolvedValue(response);
    expect(await exportQuestions(payload)).toBe(response);
    expect(blobRequest).toHaveBeenCalledExactlyOnceWith("/questions/export", {
      method: "POST", timeoutMs: 120_000, body: JSON.stringify(payload),
    });
  });

  it("propagates export errors unchanged", async () => {
    const error = new Error("export failed");
    blobRequest.mockRejectedValue(error);
    await expect(exportQuestions({ format: "csv" })).rejects.toBe(error);
  });
});

import { apiRequest, apiRequestBlob, toQuery } from "@/lib/api/client";
import type {
  AdminQuestion,
  AdminQuestionDetail,
  PaginatedResponse,
  QuestionEditRequest,
  QuestionVersion,
  QuestionVersionDetail,
} from "@/lib/api/types";

export const VERSION_HISTORY_PAGE_SIZE = 100;
export const BATCH_DELETE_CHUNK_SIZE = 50;

type SubjectNode = {
  id: number;
  code: string;
  name: string;
  path: string;
  level: number;
  children?: SubjectNode[];
};

export type QuestionQueryParams = {
  page: number;
  page_size: number;
  subject_id?: number;
  is_active: string;
  question_type: string;
  keyword: string;
  year: string;
  difficulty?: number;
  import_batch_id?: string;
  knowledge_point_id?: number;
};

export type BatchDeleteResult = {
  success_ids?: number[];
  successIds?: number[];
  failed_items?: Array<{ id: number; error: string }>;
  failedItems?: Array<{ id: number; error: string }>;
};

export type QuestionExportPayload = {
  format: "csv" | "docx";
  ids?: number[];
  subject_id?: number;
  is_active?: boolean;
  question_type?: string;
  keyword?: string;
  year?: number;
  difficulty?: number;
  import_batch_id?: string;
  knowledge_point_id?: number;
};

function flattenSubjects(items: SubjectNode[]): SubjectNode[] {
  return items.flatMap((item) => [item, ...flattenSubjects(item.children ?? [])]);
}

export async function fetchSubjectOptions(): Promise<Array<{ id: number; code: string; name: string }>> {
  const response = await apiRequest<{ items: SubjectNode[] }>("/subjects");
  return flattenSubjects(response.items ?? [])
    .filter((subject) => subject.level > 1);
}

export function fetchQuestions(queryParams: QuestionQueryParams) {
  return apiRequest<PaginatedResponse<AdminQuestion>>(`/questions${toQuery(queryParams)}`);
}

export function fetchQuestionDetail(id: number) {
  return apiRequest<AdminQuestionDetail>(`/questions/${id}`);
}

export async function fetchQuestionVersions(id: number) {
  const firstPage = await apiRequest<PaginatedResponse<QuestionVersion>>(
    `/questions/${id}/versions${toQuery({ page: 1, page_size: VERSION_HISTORY_PAGE_SIZE })}`,
  );
  if (firstPage.total_pages <= 1) return firstPage;

  const remainingPages = await Promise.all(
    Array.from({ length: firstPage.total_pages - 1 }, (_, index) =>
      apiRequest<PaginatedResponse<QuestionVersion>>(
        `/questions/${id}/versions${toQuery({ page: index + 2, page_size: VERSION_HISTORY_PAGE_SIZE })}`,
      ),
    ),
  );
  return {
    ...firstPage,
    items: [...firstPage.items, ...remainingPages.flatMap((response) => response.items)],
  };
}

export function fetchQuestionVersionDetail(id: number, version: number) {
  return apiRequest<QuestionVersionDetail>(`/questions/${id}/versions/${version}`);
}

export function updateQuestion(id: number, patch: QuestionEditRequest) {
  return apiRequest<AdminQuestion>(`/questions/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteQuestion(id: number) {
  return apiRequest<{ status: string }>(`/questions/${id}`, { method: "DELETE" });
}

export async function deleteQuestionBatch(
  ids: number[],
  keyForChunk: (chunk: number[]) => string,
): Promise<BatchDeleteResult> {
  const aggregate: BatchDeleteResult = { success_ids: [], failed_items: [] };
  for (let start = 0; start < ids.length; start += BATCH_DELETE_CHUNK_SIZE) {
    const chunk = ids.slice(start, start + BATCH_DELETE_CHUNK_SIZE);
    try {
      const result = await apiRequest<BatchDeleteResult>("/questions/batch-delete", {
        method: "POST",
        headers: { "Idempotency-Key": keyForChunk(chunk) },
        body: JSON.stringify({ ids: chunk }),
      });
      aggregate.success_ids?.push(...(result.success_ids ?? result.successIds ?? []));
      aggregate.failed_items?.push(...(result.failed_items ?? result.failedItems ?? []));
    } catch (error) {
      const errorText = error instanceof Error ? error.message : "批量删除请求失败";
      aggregate.failed_items?.push(...chunk.map((id) => ({ id, error: errorText })));
    }
  }
  return aggregate;
}

export function exportQuestions(payload: QuestionExportPayload) {
  return apiRequestBlob("/questions/export", {
    method: "POST",
    timeoutMs: 120_000,
    body: JSON.stringify(payload),
  });
}

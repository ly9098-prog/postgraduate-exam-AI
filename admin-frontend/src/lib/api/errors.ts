export class ApiError extends Error {
  status: number;
  payload: unknown;
  traceId?: string;
  requestId?: string;

  constructor(status: number, message: string, payload: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;

    if (payload && typeof payload === "object") {
      const meta = payload as Record<string, unknown>;
      this.traceId = typeof meta.traceId === "string" ? meta.traceId : undefined;
      this.requestId = typeof meta.requestId === "string" ? meta.requestId : undefined;
    }
  }
}

export function getErrorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message;
  // Unknown Error may contain fetch/runtime/backend-adapter internals; do not render it in UI.
  return "请求失败，请稍后重试";
}

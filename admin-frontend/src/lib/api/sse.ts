import { createApiRequestId, createApiTraceId, getApiAccessToken } from "./client";

export type TraceEvent = {
  seq: number;
  item_seq: number;
  step: string;
  status: string;
  message: string;
  duration_ms: number | null;
  created_at: string;
  [key: string]: unknown;
};

export type DoneEvent = {
  status: string;
  total_questions: number;
  error_message: string | null;
  succeeded: number;
  failed: number;
  [key: string]: unknown;
};

export type SSEMessage = {
  event: string;
  data: string;
};

export type SSEHandlers = {
  onOpen?: () => void;
  onTrace?: (event: TraceEvent) => void;
  onDone?: (summary: DoneEvent) => void;
  onError?: (error: SSEError) => void;
  onClose?: () => void;
};

export type SSEError = {
  type: "http" | "parse" | "heartbeat" | "eof" | "network" | "auth";
  status?: number;
  message: string;
  traceId?: string;
  requestId?: string;
};

export type SSEClient = {
  close: () => void;
};

export type SSEClientOptions = {
  /** Base URL override. Defaults to NEXT_PUBLIC_ADMIN_API_BASE_URL or /api/admin/v1 */
  baseUrl?: string;
  /** Heartbeat timeout in ms. Default 30_000 (30s). 0 disables. */
  heartbeatTimeoutMs?: number;
  /** Max reconnect attempts. Default 3. 0 disables reconnection. */
  maxRetries?: number;
  /** Initial retry delay in ms (doubles each attempt). Default 1000. */
  retryDelayMs?: number;
  /** Override token (if not using the shared provider). */
  token?: string | null;
  /** Optional trace ID shared with the action that opened this stream. */
  traceId?: string;
};

function getBaseUrl(override?: string) {
  return override ?? process.env.NEXT_PUBLIC_ADMIN_API_BASE_URL ?? "/api/admin/v1";
}

/**
 * Stateful SSE parser supporting cross-chunk lines and events.
 */
export class SSEParser {
  private buffer = "";
  private currentEvent = "";
  private currentData: string[] = [];

  /** Feed incoming chunk data, return complete messages. */
  feed(chunk: string): SSEMessage[] {
    this.buffer += chunk;
    const { messages, rest, event, data } = parseSSEBuffer(this.buffer, this.currentEvent, this.currentData);
    this.buffer = rest;
    this.currentEvent = event;
    this.currentData = data;
    return messages;
  }
}

/**
 * Parse SSE text lines from a buffer, handling \r\n, \n, and multi-line data.
 * Accepts optional pendingEvent and pendingData from a previous partial parse.
 * Returns complete messages, remaining buffer, pending event name, and pending data lines.
 */
export function parseSSEBuffer(
  buffer: string,
  pendingEvent = "",
  pendingData: string[] = [],
): { messages: SSEMessage[]; rest: string; event: string; data: string[] } {
  // Normalize \r\n to \n, then split on \n
  const lines = buffer.replace(/\r\n/g, "\n").split("\n");

  const messages: SSEMessage[] = [];
  let currentEvent = pendingEvent;
  let currentData = [...pendingData];
  const rest = lines.pop() ?? ""; // incomplete line stays in buffer

  for (const line of lines) {
    if (line.startsWith("event: ")) {
      currentEvent = line.slice(7).trim();
    } else if (line.startsWith("data: ")) {
      currentData.push(line.slice(6));
    } else if (line === "" && currentData.length > 0) {
      // Empty line = end of event
      messages.push({ event: currentEvent, data: currentData.join("\n") });
      currentEvent = "";
      currentData = [];
    }
    // Ignore comments (lines starting with :)
    // Ignore unknown fields
  }

  // If buffer ends with an empty line, the last event may have been complete
  // In that case, lines.pop() above removed the empty last line, so data is flushed.
  // We don't flush partial events here — they wait for the next chunk.

  return { messages, rest, event: currentEvent, data: currentData };
}

/**
 * Connect to an SSE endpoint with automatic reconnection, heartbeat monitoring,
 * structured error handling, and cross-chunk event parsing.
 */
export function connectSSE(
  path: string,
  token: string | null,
  handlers: SSEHandlers,
  options: SSEClientOptions = {},
): SSEClient {
  const {
    heartbeatTimeoutMs = 30_000,
    maxRetries = 3,
    retryDelayMs = 1_000,
    baseUrl: baseUrlOverride,
    token: tokenOverride,
    traceId: requestedTraceId,
  } = options;

  const baseUrl = getBaseUrl(baseUrlOverride);
  const url = `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
  const controller = new AbortController();
  let retryCount = 0;
  let heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
  let lastDataTime = Date.now();
  let disconnectedByUser = false;
  const traceId = requestedTraceId && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/.test(requestedTraceId)
    ? requestedTraceId
    : createApiTraceId();
  let currentTraceId = traceId;
  let currentRequestId = "";

  function emitError(error: SSEError) {
    handlers.onError?.({
      ...error,
      traceId: currentTraceId,
      requestId: currentRequestId || undefined,
    });
  }

  function cleanup() {
    if (heartbeatTimer) clearTimeout(heartbeatTimer);
    heartbeatTimer = null;
  }

  function resetHeartbeat() {
    if (heartbeatTimer) clearTimeout(heartbeatTimer);
    if (heartbeatTimeoutMs <= 0) return;
    lastDataTime = Date.now();
    heartbeatTimer = setTimeout(() => {
      // No data received within heartbeat window
      emitError({
        type: "heartbeat",
        message: "SSE 连接心跳超时",
      });
      controller.abort();
    }, heartbeatTimeoutMs);
  }

  async function connect() {
    const effectiveToken = tokenOverride !== undefined ? tokenOverride : getApiAccessToken() ?? token;
    currentTraceId = traceId;
    currentRequestId = createApiRequestId();
    const headers: Record<string, string> = {
      "X-Trace-ID": traceId,
      "X-Request-ID": currentRequestId,
    };
    if (effectiveToken) headers["Authorization"] = `Bearer ${effectiveToken}`;

    try {
      const response = await fetch(url, {
        headers,
        signal: controller.signal,
        credentials: "same-origin",
      });

      currentTraceId = response.headers.get("X-Trace-ID") || traceId;
      currentRequestId = response.headers.get("X-Request-ID") || currentRequestId;

      if (!response.ok) {
        const errorType = response.status === 401 ? "auth" : "http";
        emitError({
          type: errorType,
          status: response.status,
          message: response.status === 401
            ? "认证已过期，请重新登录"
            : `SSE 连接返回 HTTP ${response.status}`,
        });
        return;
      }

      if (!response.body) {
        emitError({
          type: "http",
          message: "SSE 响应体为空",
        });
        return;
      }

      // Connection established
      retryCount = 0;
      handlers.onOpen?.();
      resetHeartbeat();

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      const parser = new SSEParser();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        resetHeartbeat();

        const text = decoder.decode(value, { stream: true });
        const messages = parser.feed(text);

        for (const msg of messages) {
          if (msg.event === "trace") {
            try {
              const trace = JSON.parse(msg.data) as TraceEvent;
              handlers.onTrace?.(trace);
            } catch {
              emitError({
                type: "parse",
                message: `SSE trace 事件 JSON 解析失败: ${msg.data.slice(0, 100)}`,
              });
            }
          } else if (msg.event === "done") {
            try {
              const done = JSON.parse(msg.data) as DoneEvent;
              handlers.onDone?.(done);
            } catch {
              emitError({
                type: "parse",
                message: `SSE done 事件 JSON 解析失败: ${msg.data.slice(0, 100)}`,
              });
            }
          }
        }
      }

      // Stream ended without a done event
      if (!disconnectedByUser) {
        emitError({
          type: "eof",
          message: "SSE 流意外结束，任务可能未完成",
        });

        // Attempt reconnection
        if (maxRetries > 0 && retryCount < maxRetries) {
          retryCount++;
          const delay = Math.min(retryDelayMs * Math.pow(2, retryCount - 1), 30_000);
          emitError({
            type: "network",
            message: `SSE 将在 ${Math.round(delay / 1000)} 秒后重连 (第 ${retryCount}/${maxRetries} 次)`,
          });
          setTimeout(() => {
            if (!controller.signal.aborted) connect();
          }, delay);
          return;
        }
      }
    } catch (error) {
      if (disconnectedByUser) return; // user-initiated abort, no error

      // Network error or abort
      if (error instanceof DOMException && error.name === "AbortError") {
        if (!disconnectedByUser) {
          emitError({
            type: "network",
            message: "SSE 连接被中断",
          });
        }
        return;
      }

      emitError({
        type: "network",
        message: error instanceof Error ? error.message : "SSE 网络错误",
      });

      // Attempt reconnection for network errors
      if (maxRetries > 0 && retryCount < maxRetries) {
        retryCount++;
        const delay = Math.min(retryDelayMs * Math.pow(2, retryCount - 1), 30_000);
        setTimeout(() => {
          if (!controller.signal.aborted) connect();
        }, delay);
        return;
      }
    } finally {
      cleanup();
      handlers.onClose?.();
    }
  }

  connect();

  return {
    close: () => {
      disconnectedByUser = true;
      cleanup();
      controller.abort();
    },
  };
}

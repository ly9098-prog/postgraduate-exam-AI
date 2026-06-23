import type { TraceEvent } from "./types";

type SSEHandlers = {
  onTrace?: (event: TraceEvent) => void;
  onDone?: (summary: {
    status: string;
    total_questions: number;
    error_message: string | null;
    succeeded: number;
    failed: number;
  }) => void;
};

/**
 * Connect to an SSE endpoint via fetch (supports Bearer token natively).
 * Returns an abort function to close the connection.
 *
 * The endpoint should emit:
 *   event: trace   — incremental trace event (json TraceEvent)
 *   event: done    — job terminal summary (json { status, total_questions, ... })
 *   : heartbeat    — keepalive comment (ignored)
 */
export function connectSSE(
  path: string,
  token: string | null,
  handlers: SSEHandlers,
): () => void {
  const baseUrl =
    process.env.NEXT_PUBLIC_ADMIN_API_BASE_URL ??
    "http://localhost:8000/api/admin/v1";
  const url = `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
  const controller = new AbortController();
  const decoder = new TextDecoder();
  let buffer = "";

  (async () => {
    try {
      const response = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: controller.signal,
      });
      if (!response.ok || !response.body) return;

      const reader = response.body.getReader();
      let eventType = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n");
        buffer = parts.pop() || "";

        for (const line of parts) {
          if (line.startsWith("event: ")) {
            eventType = line.slice(7);
          } else if (line.startsWith("data: ")) {
            const data = JSON.parse(line.slice(6));
            if (eventType === "trace") handlers.onTrace?.(data as TraceEvent);
            else if (eventType === "done") handlers.onDone?.(data);
            eventType = "";
          }
        }
      }
    } catch {
      // abort is normal cleanup
    }
  })();

  return () => controller.abort();
}

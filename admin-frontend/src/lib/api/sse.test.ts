import { describe, it, expect } from "vitest";
import { parseSSEBuffer, SSEParser } from "./sse";

describe("parseSSEBuffer", () => {
  it("parses single trace event", () => {
    const input = "event: trace\ndata: {\"seq\":1,\"status\":\"processing\"}\n\n";
    const { messages, rest } = parseSSEBuffer(input);
    expect(messages).toHaveLength(1);
    expect(messages[0].event).toBe("trace");
    expect(messages[0].data).toBe('{"seq":1,"status":"processing"}');
    expect(rest).toBe("");
  });

  it("parses trace + done", () => {
    const input = "event: trace\ndata: {\"seq\":1}\n\nevent: done\ndata: {\"status\":\"completed\"}\n\n";
    const { messages } = parseSSEBuffer(input);
    expect(messages).toHaveLength(2);
    expect(messages[0].event).toBe("trace");
    expect(messages[1].event).toBe("done");
  });

  it("handles data across chunks", () => {
    const parser = new SSEParser();

    const r1 = parser.feed("event: trace\nda");
    expect(r1).toHaveLength(0);

    const messages = parser.feed("ta: {\"seq\":1}\n\n");
    expect(messages).toHaveLength(1);
    expect(messages[0].event).toBe("trace");
    expect(messages[0].data).toBe('{"seq":1}');
  });

  it("handles CRLF line endings", () => {
    const input = "event: trace\r\ndata: {\"seq\":1}\r\n\r\n";
    const { messages } = parseSSEBuffer(input);
    expect(messages).toHaveLength(1);
    expect(messages[0].event).toBe("trace");
  });

  it("handles corrupt JSON gracefully (still yields message)", () => {
    const input = "event: trace\ndata: {bad json}\n\n";
    const { messages } = parseSSEBuffer(input);
    expect(messages).toHaveLength(1);
    expect(messages[0].event).toBe("trace");
    expect(messages[0].data).toBe("{bad json}");
  });

  it("handles multi-line data:", () => {
    const input = "event: trace\ndata: line1\ndata: line2\n\n";
    const { messages } = parseSSEBuffer(input);
    expect(messages).toHaveLength(1);
    expect(messages[0].data).toBe("line1\nline2");
  });

  it("handles heartbeat comments (lines starting with :)", () => {
    const input = ": heartbeat\n\nevent: trace\ndata: {\"seq\":1}\n\n";
    const { messages } = parseSSEBuffer(input);
    expect(messages).toHaveLength(1);
    expect(messages[0].event).toBe("trace");
  });

  it("preserves incomplete last line as rest", () => {
    const input = "event: trace\ndata: {\"seq\":1}\n\nincomplete";
    const { messages, rest } = parseSSEBuffer(input);
    expect(messages).toHaveLength(1);
    expect(rest).toBe("incomplete");
  });

  it("handles events with no explicit event type (default to 'message')", () => {
    const input = "data: {\"msg\":\"hello\"}\n\n";
    const { messages } = parseSSEBuffer(input);
    expect(messages).toHaveLength(1);
    expect(messages[0].event).toBe("");
    expect(messages[0].data).toBe('{"msg":"hello"}');
  });

  it("ignores unknown fields", () => {
    const input = "event: trace\nid: 123\nretry: 5000\ndata: {\"seq\":1}\n\n";
    const { messages } = parseSSEBuffer(input);
    expect(messages).toHaveLength(1);
  });
});

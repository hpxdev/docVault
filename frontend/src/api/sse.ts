import { API_BASE, ApiError, parseError } from "./client";

export interface SSEEvent {
  event: string;
  data: unknown;
}

function parseBlock(block: string): SSEEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue; // comments are keepalive pings
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  if (!data.length) return null;
  const raw = data.join("\n");
  try {
    return { event, data: JSON.parse(raw) };
  } catch {
    return { event, data: raw };
  }
}

/** POST a JSON body and read an SSE response. The browser's EventSource only supports GET, so
 * the chat stream is read from the fetch body. Aborting the signal closes the connection, which
 * the server treats as "stop generating" (the partial answer is saved as interrupted). */
export async function postSSE(
  path: string,
  body: unknown,
  onEvent: (event: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(API_BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "NETWORK_ERROR", "Cannot reach the API. Is the backend running?");
  }
  if (!res.ok) throw await parseError(res);
  if (!res.body) throw new ApiError(0, "STREAM_ERROR", "The response has no body.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let end: number;
    while ((end = buffer.indexOf("\n\n")) !== -1) {
      const parsed = parseBlock(buffer.slice(0, end));
      buffer = buffer.slice(end + 2);
      if (parsed) onEvent(parsed);
    }
  }
  const tail = parseBlock(buffer.trim());
  if (tail) onEvent(tail);
}

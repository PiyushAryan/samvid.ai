import { getAccessToken } from "@/lib/auth-session";
import { ApiError, requestJson, responseApiError } from "@/lib/http-client";
import type { ChatMessage, ChatSession, ChatSessionSummary, ChatSource } from "./types";

function collectionItems<T>(response: T[] | { items: T[] }): T[] {
  return Array.isArray(response) ? response : response.items;
}

export async function listChatSessions(): Promise<ChatSessionSummary[]> {
  const response = await requestJson<ChatSessionSummary[] | { items: ChatSessionSummary[] }>("/api/chats");
  return collectionItems(response);
}

export function createChatSession(title?: string, contractId?: string | null) {
  return requestJson<ChatSession>("/api/chats", {
    method: "POST",
    body: JSON.stringify({ title: title?.trim() || null, contract_id: contractId || null })
  });
}

export function getChatSession(sessionId: string) {
  return requestJson<ChatSession>(`/api/chats/${encodeURIComponent(sessionId)}`);
}

export function updateChatContractScope(sessionId: string, contractId: string | null) {
  return requestJson<ChatSession>(`/api/chats/${encodeURIComponent(sessionId)}/contract-scope`, {
    method: "PATCH",
    body: JSON.stringify({ contract_id: contractId })
  });
}

export interface ChatStreamHandlers {
  onStatus?: (status: string) => void;
  onDelta?: (delta: string) => void;
  onSources?: (sources: ChatSource[]) => void;
  onMessage?: (message: ChatMessage) => void;
}

export async function streamChatMessage(
  sessionId: string,
  content: string,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const token = await getAccessToken();
  const response = await fetch(`/api/chats/${encodeURIComponent(sessionId)}/messages`, {
    method: "POST",
    headers: {
      Accept: "text/event-stream",
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ content }),
    signal
  });

  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event("samvid:auth-required"));
    if (response.status === 403) window.dispatchEvent(new Event("samvid:access-denied"));
    throw await responseApiError(response);
  }

  if (response.headers.get("content-type")?.includes("application/json")) {
    handlers.onMessage?.(await response.json() as ChatMessage);
    return;
  }
  if (!response.body) throw new ApiError(502, { message: "The chat stream did not return a response body." });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() || "";
    blocks.forEach((block) => dispatchChatStreamBlock(block, handlers));
    if (done) break;
  }
  if (buffer.trim()) dispatchChatStreamBlock(buffer, handlers);
}

function dispatchChatStreamBlock(block: string, handlers: ChatStreamHandlers) {
  let eventName = "message";
  const data: string[] = [];
  block.split(/\r?\n/).forEach((line) => {
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  });
  if (!data.length) return;

  const raw = data.join("\n");
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    payload = { delta: raw };
  }
  const type = String(payload.type || eventName).replace(/_/g, ".");
  if (["message.status", "status"].includes(type)) {
    if (typeof payload.status === "string") handlers.onStatus?.(payload.status);
    return;
  }
  if (["message.delta", "delta", "token"].includes(type)) {
    const delta = payload.delta ?? payload.token ?? payload.content;
    if (typeof delta === "string") handlers.onDelta?.(delta);
    return;
  }
  if (["message.sources", "sources"].includes(type) && Array.isArray(payload.sources)) {
    handlers.onSources?.(payload.sources as unknown as ChatSource[]);
    return;
  }
  if (["message.completed", "completed", "done"].includes(type) && payload.message) {
    handlers.onMessage?.(payload.message as unknown as ChatMessage);
    return;
  }
  if (type === "error") {
    throw new ApiError(502, {
      code: typeof payload.code === "string" ? payload.code : undefined,
      message: typeof payload.message === "string" ? payload.message : "The chat stream failed."
    });
  }
}

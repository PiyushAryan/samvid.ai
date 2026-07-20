import { beforeEach, expect, test, vi } from "vitest";

import { streamChatMessage } from "./api";

vi.mock("./auth", () => ({
  getAccessToken: vi.fn().mockResolvedValue("chat-access-token"),
  getCurrentAccount: vi.fn()
}));

beforeEach(() => {
  vi.restoreAllMocks();
});

test("chat stream consumes authenticated SSE deltas, sources, and completion", async () => {
  const completedMessage = {
    id: "message-2",
    role: "assistant" as const,
    content: "The notice period is 30 days.",
    sources: [],
    created_at: "2026-07-20T10:00:00Z"
  };
  const stream = [
    'event: message.delta\ndata: {"delta":"The notice "}\n\n',
    'event: message_delta\ndata: {"delta":"period is 30 days."}\n\n',
    'event: message.sources\ndata: {"sources":[{"contract_id":"contract-1","contract_title":"Services agreement","page_number":11,"excerpt":"Thirty days notice."}]}\n\n',
    `event: message.completed\ndata: ${JSON.stringify({ message: completedMessage })}\n\n`
  ].join("");
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" }
  }));
  const deltas: string[] = [];
  const sources: string[] = [];
  let finalContent = "";

  await streamChatMessage("chat/one", "What is the notice period?", {
    onDelta: (delta) => deltas.push(delta),
    onSources: (items) => sources.push(...items.map((item) => item.contract_title)),
    onMessage: (message) => { finalContent = message.content; }
  });

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/chats/chat%2Fone/messages",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ content: "What is the notice period?" }),
      headers: expect.objectContaining({ Authorization: "Bearer chat-access-token" })
    })
  );
  expect(deltas.join("")).toBe("The notice period is 30 days.");
  expect(sources).toEqual(["Services agreement"]);
  expect(finalContent).toBe("The notice period is 30 days.");
});

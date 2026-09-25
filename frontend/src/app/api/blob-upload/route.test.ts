import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { handleUpload } from "@vercel/blob/client";
import { maxDuration, POST } from "./route";

vi.mock("@vercel/blob/client", () => ({
  handleUpload: vi.fn()
}));

const pathname = "contracts/user-123/upload-123/agreement.pdf";

function uploadRequest() {
  return new Request("http://localhost/api/blob-upload", {
    method: "POST",
    headers: {
      Authorization: "Bearer test-token",
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      type: "blob.generate-client-token",
      payload: { pathname, clientPayload: null, multipart: false }
    })
  });
}

beforeEach(() => {
  process.env.API_ORIGIN = "https://api.example.com";
  vi.mocked(handleUpload).mockImplementation(async ({ body, onBeforeGenerateToken }) => {
    await onBeforeGenerateToken(body.payload.pathname, null, false);
    return { type: "blob.generate-client-token", clientToken: "client-token" };
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  delete process.env.API_ORIGIN;
});

test("authorizes a client upload with one backend request", async () => {
  const fetchMock = vi.fn().mockResolvedValue(Response.json({ status: "authorized" }));
  vi.stubGlobal("fetch", fetchMock);

  const response = await POST(uploadRequest());

  expect(response.status).toBe(200);
  expect(maxDuration).toBe(30);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock).toHaveBeenCalledWith(
    new URL("https://api.example.com/api/uploads/authorize"),
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ pathname })
    })
  );
});

test("reports an authorization timeout as a retryable gateway timeout", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new DOMException("Timed out", "TimeoutError")));

  const response = await POST(uploadRequest());

  expect(response.status).toBe(504);
  await expect(response.json()).resolves.toEqual({
    error: "Upload authorization timed out. Please try again."
  });
});

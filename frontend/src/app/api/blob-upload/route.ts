import { handleUpload, type HandleUploadBody } from "@vercel/blob/client";

const allowedContentTypes = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain"
];
const uploadAuthorizationTimeoutMs = 20_000;

class UploadAdmissionError extends Error {
  readonly status: number;
  readonly retryAfter: string | null;

  constructor(message: string, status: number, retryAfter: string | null = null) {
    super(message);
    this.name = "UploadAdmissionError";
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

async function authorizeContractUpload(request: Request, pathname: string): Promise<void> {
  const apiOrigin = process.env.API_ORIGIN;
  const authorization = request.headers.get("authorization");
  if (!apiOrigin || !authorization?.startsWith("Bearer ")) {
    throw new UploadAdmissionError("Authentication required", 401);
  }
  let response: Response;
  try {
    response = await fetch(new URL("/api/uploads/authorize", apiOrigin), {
      method: "POST",
      headers: { Authorization: authorization, "Content-Type": "application/json" },
      body: JSON.stringify({ pathname }),
      signal: AbortSignal.timeout(uploadAuthorizationTimeoutMs)
    });
  } catch (error) {
    const errorName = error && typeof error === "object" && "name" in error
      ? String(error.name)
      : "";
    if (errorName === "TimeoutError" || errorName === "AbortError") {
      throw new UploadAdmissionError("Upload authorization timed out. Please try again.", 504);
    }
    throw new UploadAdmissionError("Upload authorization service is unavailable. Please try again.", 502);
  }
  if (response.ok) return;
  if (response.status === 401) throw new UploadAdmissionError("Authentication required", 401);
  const payload = await response.json().catch(() => null) as {
    detail?: string | { message?: string };
    message?: string;
  } | null;
  const status = response.status === 429 || response.status === 503 ? response.status : 400;
  const detail = typeof payload?.detail === "string" ? payload.detail : payload?.detail?.message;
  throw new UploadAdmissionError(
    detail || payload?.message || "Upload is not available right now",
    status,
    response.headers.get("Retry-After")
  );
}

export const maxDuration = 30;
export const preferredRegion = "sin1";

export async function POST(request: Request): Promise<Response> {
  try {
    const body = (await request.json()) as HandleUploadBody;
    const response = await handleUpload({
      body,
      request,
      onBeforeGenerateToken: async (pathname) => {
        // The backend verifies both the account and the workspace prefix. Avoid a
        // separate /auth/me request here so a cold API only has to start once.
        await authorizeContractUpload(request, pathname);

        return {
          allowedContentTypes,
          maximumSizeInBytes: Number(process.env.MAX_FILE_SIZE_MB || "20") * 1024 * 1024,
          addRandomSuffix: false
        };
      }
    });
    return Response.json(response);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Upload authorization failed";
    const status = error instanceof UploadAdmissionError
      ? error.status
      : message === "Authentication required"
        ? 401
        : 400;
    const headers = new Headers();
    if (status === 401) headers.set("WWW-Authenticate", "Bearer");
    if (error instanceof UploadAdmissionError && error.retryAfter) {
      headers.set("Retry-After", error.retryAfter);
    }
    return Response.json({ error: message }, { status, headers });
  }
}

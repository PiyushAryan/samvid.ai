import { handleUpload, type HandleUploadBody } from "@vercel/blob/client";

const allowedContentTypes = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain"
];

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

async function personalWorkspaceForRequest(request: Request): Promise<string | null> {
  const apiOrigin = process.env.API_ORIGIN;
  const authorization = request.headers.get("authorization");
  if (!apiOrigin || !authorization?.startsWith("Bearer ")) return null;
  const response = await fetch(new URL("/api/auth/me", apiOrigin), {
    headers: { Authorization: authorization },
    signal: AbortSignal.timeout(5000)
  });
  if (!response.ok) return null;
  const payload = await response.json() as {
    account?: { role?: string; state?: string; workspace_id?: string | null };
  };
  const workspaceId = payload.account?.workspace_id;
  if (payload.account?.role !== "user" || payload.account?.state !== "active" || !workspaceId) return null;
  return workspaceId;
}

async function authorizeContractUpload(request: Request, pathname: string): Promise<void> {
  const apiOrigin = process.env.API_ORIGIN;
  const authorization = request.headers.get("authorization");
  if (!apiOrigin || !authorization?.startsWith("Bearer ")) {
    throw new UploadAdmissionError("Authentication required", 401);
  }
  const response = await fetch(new URL("/api/uploads/authorize", apiOrigin), {
    method: "POST",
    headers: { Authorization: authorization, "Content-Type": "application/json" },
    body: JSON.stringify({ pathname }),
    signal: AbortSignal.timeout(5000)
  });
  if (response.ok) return;
  if (response.status === 401) throw new UploadAdmissionError("Authentication required", 401);
  const payload = await response.json().catch(() => null) as { detail?: { message?: string } } | null;
  const status = response.status === 429 || response.status === 503 ? response.status : 400;
  throw new UploadAdmissionError(
    payload?.detail?.message || "Upload is not available right now",
    status,
    response.headers.get("Retry-After")
  );
}

export async function POST(request: Request): Promise<Response> {
  try {
    const body = (await request.json()) as HandleUploadBody;
    const response = await handleUpload({
      body,
      request,
      onBeforeGenerateToken: async (pathname) => {
        const workspaceId = await personalWorkspaceForRequest(request);
        if (!workspaceId) throw new Error("Authentication required");
        if (!pathname.startsWith(`contracts/${workspaceId}/`)) throw new Error("Invalid upload path");
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
    return Response.json(
      { error: message },
      {
        status,
        headers
      }
    );
  }
}

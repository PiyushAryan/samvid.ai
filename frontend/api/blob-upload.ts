import { handleUpload, type HandleUploadBody } from "@vercel/blob/client";

const allowedContentTypes = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain"
];

function hasValidBasicAuth(request: Request): boolean {
  const username = process.env.APP_ACCESS_USERNAME || "samvid";
  const password = process.env.APP_ACCESS_PASSWORD;
  const authorization = request.headers.get("authorization");
  if (!password || !authorization?.startsWith("Basic ")) return false;

  try {
    return atob(authorization.slice(6)) === `${username}:${password}`;
  } catch {
    return false;
  }
}

export default async function handler(request: Request): Promise<Response> {
  if (request.method !== "POST") {
    return Response.json({ error: "Method not allowed" }, { status: 405, headers: { Allow: "POST" } });
  }

  try {
    const body = (await request.json()) as HandleUploadBody;
    const response = await handleUpload({
      body,
      request,
      onBeforeGenerateToken: async (pathname) => {
        if (!hasValidBasicAuth(request)) throw new Error("Authentication required");
        if (!pathname.startsWith("contracts/")) throw new Error("Invalid upload path");

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
    const status = message === "Authentication required" ? 401 : 400;
    return Response.json(
      { error: message },
      {
        status,
        headers: status === 401 ? { "WWW-Authenticate": 'Basic realm="Samvid", charset="UTF-8"' } : undefined
      }
    );
  }
}

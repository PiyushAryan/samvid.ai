import { next, rewrite } from "@vercel/functions";

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

export default function middleware(request: Request): Response {
  const url = new URL(request.url);

  // The Blob completion callback is authenticated by the Blob SDK itself.
  if (url.pathname === "/api/blob-upload") return next();

  if (!hasValidBasicAuth(request)) {
    return Response.json(
      { detail: "Authentication required" },
      {
        status: 401,
        headers: { "WWW-Authenticate": 'Basic realm="Samvid", charset="UTF-8"' }
      }
    );
  }

  if (url.pathname.startsWith("/api/")) {
    const apiOrigin = process.env.API_ORIGIN;
    if (!apiOrigin) return Response.json({ detail: "API origin is not configured" }, { status: 503 });
    return rewrite(new URL(`${url.pathname}${url.search}`, apiOrigin));
  }

  return next();
}

export const config = {
  matcher: ["/contracts/:path*", "/api/:path*"]
};

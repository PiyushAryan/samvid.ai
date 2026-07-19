import { next, rewrite } from "@vercel/functions";

export default function middleware(request: Request): Response {
  const url = new URL(request.url);

  // The Blob completion callback is authenticated by the Blob SDK itself.
  if (url.pathname === "/api/blob-upload") return next();

  if (url.pathname.startsWith("/api/")) {
    const apiOrigin = process.env.API_ORIGIN;
    if (!apiOrigin) return Response.json({ detail: "API origin is not configured" }, { status: 503 });
    return rewrite(new URL(`${url.pathname}${url.search}`, apiOrigin));
  }

  return next();
}

export const config = {
  matcher: ["/api/:path*"]
};

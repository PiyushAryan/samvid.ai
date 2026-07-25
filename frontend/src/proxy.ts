import { NextResponse, type NextRequest } from "next/server";

export function proxy(request: NextRequest) {
  const host = request.headers.get("host")?.split(":")[0]?.toLowerCase();
  if (host === "samvid.ai" || host === "www.samvid.ai" || host === "www.samvid.online") {
    const destination = request.nextUrl.clone();
    destination.protocol = "https:";
    destination.hostname = "samvid.online";
    destination.port = "";
    return NextResponse.redirect(destination, 308);
  }

  if (!request.nextUrl.pathname.startsWith("/api/") || request.nextUrl.pathname === "/api/blob-upload") {
    return NextResponse.next();
  }

  const apiOrigin = process.env.API_ORIGIN;
  if (!apiOrigin) {
    return NextResponse.json({ detail: "API origin is not configured" }, { status: 503 });
  }

  const destination = new URL(`${request.nextUrl.pathname}${request.nextUrl.search}`, apiOrigin);
  return NextResponse.rewrite(destination);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image).*)"]
};

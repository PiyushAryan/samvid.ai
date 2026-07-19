import { createAuthClient } from "@neondatabase/neon-js/auth";

const neonAuthUrl = import.meta.env.VITE_NEON_AUTH_URL?.trim();

export const PENDING_AUTH_EMAIL_KEY = "samvid-pending-auth-email";

export const isNeonAuthConfigured = Boolean(neonAuthUrl);

export const authClient = neonAuthUrl ? createAuthClient(neonAuthUrl) : null;

export type SamvidAuthUser = {
  id: string;
  email: string;
  emailVerified: boolean;
  name: string;
  image?: string | null;
};

export type WorkspaceAccessResult =
  | { status: "allowed" }
  | { status: "unauthenticated"; message: string }
  | { status: "denied"; message: string }
  | { status: "error"; message: string };

export function safeInternalPath(value: string | null | undefined, fallback = "/contracts") {
  if (!value) return fallback;

  try {
    const origin = window.location.origin;
    const resolved = new URL(value, origin);
    if (resolved.origin !== origin || !resolved.pathname.startsWith("/")) return fallback;
    return `${resolved.pathname}${resolved.search}${resolved.hash}`;
  } catch {
    return fallback;
  }
}

export function getAuthClient() {
  if (!authClient) {
    throw new Error("Neon Auth is not configured. Add VITE_NEON_AUTH_URL to the frontend environment.");
  }

  return authClient;
}

export async function getAuthSession() {
  const result = await getAuthClient().getSession();
  if (result.error) throw result.error;
  return result.data;
}

export async function getAccessToken(): Promise<string> {
  const session = await getAuthSession();
  const token = session?.session?.token;
  if (!token) throw new Error("Authentication required");
  return token;
}

export async function checkWorkspaceAccess(token: string): Promise<WorkspaceAccessResult> {
  try {
    const response = await fetch("/api/auth/me", {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (response.ok) return { status: "allowed" };

    let message = response.statusText || "Workspace access could not be verified.";
    try {
      const payload = await response.json() as { detail?: unknown; message?: unknown };
      if (typeof payload.detail === "string" && payload.detail.trim()) message = payload.detail;
      else if (typeof payload.message === "string" && payload.message.trim()) message = payload.message;
    } catch {
      // Keep the status text when the API does not return JSON.
    }

    if (response.status === 401) return { status: "unauthenticated", message };
    if (response.status === 403) return { status: "denied", message };
    return { status: "error", message };
  } catch {
    return { status: "error", message: "Samvid could not verify workspace access. Try again." };
  }
}

export function getAuthErrorMessage(error: unknown, fallback: string) {
  if (typeof error === "string" && error.trim()) return error;

  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }

  return fallback;
}

import {
  setCurrentAccount,
  type SamvidAccount
} from "@/lib/auth-session";

export {
  authClient,
  getAccessToken,
  getAuthClient,
  getAuthSession,
  getCurrentAccount,
  isNeonAuthConfigured,
  PENDING_AUTH_EMAIL_KEY,
  setCurrentAccount
} from "@/lib/auth-session";
export type { SamvidAccount, SamvidAccountRole, SamvidAccountState, SamvidAuthUser } from "@/lib/auth-session";

export type AuthMeResponse = {
  user: {
    subject: string;
    email: string;
    name: string;
    email_verified: boolean;
  };
  account: SamvidAccount;
};

export function defaultRouteForAccount(account: SamvidAccount | null | undefined) {
  return account?.role === "super_admin" ? "/admin" : "/contracts";
}

export function canAccountAccessPath(account: SamvidAccount, path: string) {
  return account.role === "super_admin" ? path.startsWith("/admin") : !path.startsWith("/admin");
}

export type WorkspaceAccessResult =
  | { status: "allowed"; profile: AuthMeResponse }
  | { status: "unauthenticated"; message: string }
  | { status: "denied"; message: string }
  | { status: "error"; message: string };

export function safeInternalPath(value: string | null | undefined, fallback = "/contracts") {
  if (!value) return fallback;

  try {
    if (typeof window === "undefined") return value.startsWith("/") ? value : fallback;
    const origin = window.location.origin;
    const resolved = new URL(value, origin);
    if (resolved.origin !== origin || !resolved.pathname.startsWith("/")) return fallback;
    return `${resolved.pathname}${resolved.search}${resolved.hash}`;
  } catch {
    return fallback;
  }
}

export async function checkWorkspaceAccess(token: string): Promise<WorkspaceAccessResult> {
  try {
    const response = await fetch("/api/auth/me", {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (response.ok) {
      const profile = await response.json() as AuthMeResponse;
      setCurrentAccount(profile.account);
      return { status: "allowed", profile };
    }

    let message = response.statusText || "Workspace access could not be verified.";
    try {
      const payload = await response.json() as { detail?: unknown; message?: unknown };
      if (typeof payload.detail === "string" && payload.detail.trim()) message = payload.detail;
      else if (typeof payload.message === "string" && payload.message.trim()) message = payload.message;
    } catch {
      // Keep the status text when the API does not return JSON.
    }

    if (response.status === 401) {
      setCurrentAccount(null);
      return { status: "unauthenticated", message };
    }
    if (response.status === 403) {
      setCurrentAccount(null);
      return { status: "denied", message };
    }
    return { status: "error", message };
  } catch {
    setCurrentAccount(null);
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

import { createAuthClient } from "@neondatabase/neon-js/auth";

const neonAuthUrl = import.meta.env.VITE_NEON_AUTH_URL?.trim();

export const isNeonAuthConfigured = Boolean(neonAuthUrl);

export const authClient = neonAuthUrl ? createAuthClient(neonAuthUrl) : null;

export type SamvidAuthUser = {
  id: string;
  email: string;
  emailVerified: boolean;
  name: string;
  image?: string | null;
};

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

export function getAuthErrorMessage(error: unknown, fallback: string) {
  if (typeof error === "string" && error.trim()) return error;

  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }

  return fallback;
}

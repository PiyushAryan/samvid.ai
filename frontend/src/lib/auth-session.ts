import { createAuthClient } from "@neondatabase/neon-js/auth";

const neonAuthUrl = process.env.NEXT_PUBLIC_NEON_AUTH_URL?.trim();

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

export type SamvidAccountRole = "user" | "super_admin";
export type SamvidAccountState = "active" | "unclaimed";

export type SamvidAccount = {
  id: string;
  role: SamvidAccountRole;
  state: SamvidAccountState;
  workspace_id: string | null;
};

let currentAccount: SamvidAccount | null = null;

export function setCurrentAccount(account: SamvidAccount | null) {
  currentAccount = account;
}

export function getCurrentAccount() {
  return currentAccount;
}

export function getAuthClient() {
  if (!authClient) {
    throw new Error("Neon Auth is not configured. Add NEXT_PUBLIC_NEON_AUTH_URL to the frontend environment.");
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

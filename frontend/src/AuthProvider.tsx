import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";

import {
  checkWorkspaceAccess,
  getAuthClient,
  getAuthSession,
  isNeonAuthConfigured,
  setCurrentAccount,
  type SamvidAccount,
  type SamvidAccountRole,
  type SamvidAuthUser
} from "./auth";

type WorkspaceAccessStatus = "idle" | "checking" | "allowed" | "unverified" | "denied" | "error";

type AuthContextValue = {
  user: SamvidAuthUser | null;
  account: SamvidAccount | null;
  isLoading: boolean;
  accessStatus: WorkspaceAccessStatus;
  accessMessage: string;
  refreshSession: () => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function getLoadingTheme(): "light" | "dark" {
  const savedTheme = window.localStorage.getItem("samvid-theme");
  if (savedTheme === "light" || savedTheme === "dark") return savedTheme;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function AuthRouteLoading({ label }: { label: string }) {
  const theme = getLoadingTheme();

  return (
    <main className="auth-route-loading" data-theme={theme} aria-label={label} aria-busy="true">
      <img
        className="auth-route-loading-logo"
        src={theme === "dark" ? "/favicon-dark.svg" : "/favicon-light.svg"}
        alt=""
        aria-hidden="true"
      />
    </main>
  );
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SamvidAuthUser | null>(null);
  const [account, setAccount] = useState<SamvidAccount | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [accessStatus, setAccessStatus] = useState<WorkspaceAccessStatus>("idle");
  const [accessMessage, setAccessMessage] = useState("");
  const accessReadyRef = useRef(false);
  const accessUserIdRef = useRef<string | null>(null);

  const refreshSession = useCallback(async () => {
    if (!isNeonAuthConfigured) {
      setUser(null);
      setAccount(null);
      setCurrentAccount(null);
      setAccessStatus("idle");
      accessReadyRef.current = false;
      accessUserIdRef.current = null;
      setIsLoading(false);
      return;
    }

    try {
      const session = await getAuthSession();
      const sessionUser = (session?.user as SamvidAuthUser | undefined) ?? null;
      const canRefreshInBackground = Boolean(
        sessionUser &&
        accessReadyRef.current &&
        accessUserIdRef.current === sessionUser.id
      );
      setUser(sessionUser);
      setAccessMessage("");

      if (!sessionUser) {
        setAccount(null);
        setCurrentAccount(null);
        setAccessStatus("idle");
        accessReadyRef.current = false;
        accessUserIdRef.current = null;
        return;
      }
      if (!sessionUser.emailVerified) {
        setAccount(null);
        setCurrentAccount(null);
        setAccessStatus("unverified");
        accessReadyRef.current = false;
        accessUserIdRef.current = null;
        return;
      }

      const token = session?.session?.token;
      if (!token) {
        setUser(null);
        setAccount(null);
        setCurrentAccount(null);
        setAccessStatus("idle");
        accessReadyRef.current = false;
        accessUserIdRef.current = null;
        return;
      }

      if (!canRefreshInBackground) {
        setAccount(null);
        setCurrentAccount(null);
        setAccessStatus("checking");
      }
      const access = await checkWorkspaceAccess(token);
      setAccessMessage("message" in access ? access.message : "");
      if (access.status === "unauthenticated") {
        setUser(null);
        setAccount(null);
        setCurrentAccount(null);
        setAccessStatus("idle");
        accessReadyRef.current = false;
        accessUserIdRef.current = null;
      } else if (access.status === "allowed") {
        setAccount(access.profile.account);
        setAccessStatus("allowed");
        accessReadyRef.current = true;
        accessUserIdRef.current = sessionUser.id;
      } else {
        setAccessStatus(access.status);
        if (access.status === "denied" || access.status === "error") {
          accessReadyRef.current = false;
        }
      }
    } catch {
      setUser(null);
      setAccount(null);
      setCurrentAccount(null);
      setAccessStatus("idle");
      accessReadyRef.current = false;
      accessUserIdRef.current = null;
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshSession();
    const handleAuthRequired = () => void refreshSession();
    const handleAccessDenied = () => void refreshSession();
    const handleVisibility = () => {
      if (document.visibilityState === "visible") void refreshSession();
    };
    window.addEventListener("samvid:auth-required", handleAuthRequired);
    window.addEventListener("samvid:access-denied", handleAccessDenied);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      window.removeEventListener("samvid:auth-required", handleAuthRequired);
      window.removeEventListener("samvid:access-denied", handleAccessDenied);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [refreshSession]);

  const signOut = useCallback(async () => {
    try {
      if (isNeonAuthConfigured) await getAuthClient().signOut();
    } finally {
      setUser(null);
      setAccount(null);
      setCurrentAccount(null);
      setAccessStatus("idle");
      setAccessMessage("");
    }
  }, []);

  const value = useMemo(
    () => ({ user, account, isLoading, accessStatus, accessMessage, refreshSession, signOut }),
    [user, account, isLoading, accessStatus, accessMessage, refreshSession, signOut]
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  return <RequireAccount>{children}</RequireAccount>;
}

function RequireAccount({ children, role }: { children: ReactNode; role?: SamvidAccountRole }) {
  const { user, account, isLoading, accessStatus, accessMessage, refreshSession, signOut } = useAuth();
  const location = useLocation();

  if (isLoading || accessStatus === "checking") {
    return <AuthRouteLoading label="Loading your workspace" />;
  }
  if (!user) {
    const returnTo = `${location.pathname}${location.search}`;
    return <Navigate to={`/auth?returnTo=${encodeURIComponent(returnTo)}`} replace />;
  }
  if (!user.emailVerified || accessStatus === "unverified") {
    const returnTo = `${location.pathname}${location.search}`;
    return <Navigate to={`/auth?view=verify-email&returnTo=${encodeURIComponent(returnTo)}`} replace />;
  }
  if (accessStatus === "denied") {
    return (
      <main className="auth-route-state">
        <section className="auth-route-state-panel" aria-labelledby="access-denied-title">
          <span>Account access</span>
          <h1 id="access-denied-title">This account is not available.</h1>
          <p>{accessMessage || "Samvid could not provision access for this account."}</p>
          <button type="button" onClick={() => void signOut()}>Sign out</button>
        </section>
      </main>
    );
  }
  if (accessStatus === "error") {
    return (
      <main className="auth-route-state">
        <section className="auth-route-state-panel" aria-labelledby="access-error-title">
          <span>Account access</span>
          <h1 id="access-error-title">Access could not be verified.</h1>
          <p>{accessMessage || "Samvid could not reach the authorization service."}</p>
          <button type="button" onClick={() => void refreshSession()}>Try again</button>
        </section>
      </main>
    );
  }
  if (accessStatus !== "allowed") {
    return <AuthRouteLoading label="Verifying account access" />;
  }
  if (!account) return <AuthRouteLoading label="Loading your account" />;
  if (account.state === "unclaimed") {
    return (
      <main className="auth-route-state">
        <section className="auth-route-state-panel" aria-labelledby="claim-account-title">
          <span>Account claim required</span>
          <h1 id="claim-account-title">Verify the email that received this contract.</h1>
          <p>Sign in with the exact verified address used to send the contract to Samvid.</p>
          <button type="button" onClick={() => void signOut()}>Use another account</button>
        </section>
      </main>
    );
  }
  if (role && account.role !== role) {
    return <Navigate to={account.role === "super_admin" ? "/admin" : "/contracts"} replace />;
  }
  return children;
}

export function RequireUser({ children }: { children: ReactNode }) {
  return <RequireAccount role="user">{children}</RequireAccount>;
}

export function RequireSuperAdmin({ children }: { children: ReactNode }) {
  return <RequireAccount role="super_admin">{children}</RequireAccount>;
}

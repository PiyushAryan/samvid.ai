import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";

import {
  checkWorkspaceAccess,
  getAuthClient,
  getAuthSession,
  isNeonAuthConfigured,
  type SamvidAuthUser
} from "./auth";
import { Skeleton } from "./components/ui/skeleton";

type WorkspaceAccessStatus = "idle" | "checking" | "allowed" | "unverified" | "denied" | "error";

type AuthContextValue = {
  user: SamvidAuthUser | null;
  isLoading: boolean;
  accessStatus: WorkspaceAccessStatus;
  accessMessage: string;
  refreshSession: () => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SamvidAuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [accessStatus, setAccessStatus] = useState<WorkspaceAccessStatus>("idle");
  const [accessMessage, setAccessMessage] = useState("");

  const refreshSession = useCallback(async () => {
    if (!isNeonAuthConfigured) {
      setUser(null);
      setAccessStatus("idle");
      setIsLoading(false);
      return;
    }

    try {
      const session = await getAuthSession();
      const sessionUser = (session?.user as SamvidAuthUser | undefined) ?? null;
      setUser(sessionUser);
      setAccessMessage("");

      if (!sessionUser) {
        setAccessStatus("idle");
        return;
      }
      if (!sessionUser.emailVerified) {
        setAccessStatus("unverified");
        return;
      }

      const token = session?.session?.token;
      if (!token) {
        setUser(null);
        setAccessStatus("idle");
        return;
      }

      setAccessStatus("checking");
      const access = await checkWorkspaceAccess(token);
      setAccessMessage("message" in access ? access.message : "");
      if (access.status === "unauthenticated") {
        setUser(null);
        setAccessStatus("idle");
      } else {
        setAccessStatus(access.status);
      }
    } catch {
      setUser(null);
      setAccessStatus("idle");
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
      setAccessStatus("idle");
      setAccessMessage("");
    }
  }, []);

  const value = useMemo(
    () => ({ user, isLoading, accessStatus, accessMessage, refreshSession, signOut }),
    [user, isLoading, accessStatus, accessMessage, refreshSession, signOut]
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, isLoading, accessStatus, accessMessage, refreshSession, signOut } = useAuth();
  const location = useLocation();

  if (isLoading || accessStatus === "checking") {
    return (
      <main className="auth-route-loading" aria-label="Loading your workspace" aria-busy="true">
        <Skeleton className="auth-route-loading-mark" />
        <Skeleton className="auth-route-loading-line" />
      </main>
    );
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
          <span>Workspace access</span>
          <h1 id="access-denied-title">This account is not authorized.</h1>
          <p>{accessMessage || "Ask the Samvid workspace owner to add your email address."}</p>
          <button type="button" onClick={() => void signOut()}>Sign out</button>
        </section>
      </main>
    );
  }
  if (accessStatus === "error") {
    return (
      <main className="auth-route-state">
        <section className="auth-route-state-panel" aria-labelledby="access-error-title">
          <span>Workspace access</span>
          <h1 id="access-error-title">Access could not be verified.</h1>
          <p>{accessMessage || "Samvid could not reach the authorization service."}</p>
          <button type="button" onClick={() => void refreshSession()}>Try again</button>
        </section>
      </main>
    );
  }
  if (accessStatus !== "allowed") {
    return (
      <main className="auth-route-loading" aria-label="Verifying workspace access" aria-busy="true">
        <Skeleton className="auth-route-loading-mark" />
        <Skeleton className="auth-route-loading-line" />
      </main>
    );
  }
  return children;
}

import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { getAuthClient, getAuthSession, isNeonAuthConfigured, type SamvidAuthUser } from "./auth";
import { Skeleton } from "./components/ui/skeleton";

type AuthContextValue = {
  user: SamvidAuthUser | null;
  isLoading: boolean;
  refreshSession: () => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SamvidAuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refreshSession = useCallback(async () => {
    if (!isNeonAuthConfigured) {
      setUser(null);
      setIsLoading(false);
      return;
    }

    try {
      const session = await getAuthSession();
      setUser((session?.user as SamvidAuthUser | undefined) ?? null);
    } catch {
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshSession();
    const handleAuthRequired = () => void refreshSession();
    const handleVisibility = () => {
      if (document.visibilityState === "visible") void refreshSession();
    };
    window.addEventListener("samvid:auth-required", handleAuthRequired);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      window.removeEventListener("samvid:auth-required", handleAuthRequired);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [refreshSession]);

  const signOut = useCallback(async () => {
    if (isNeonAuthConfigured) await getAuthClient().signOut();
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, isLoading, refreshSession, signOut }), [user, isLoading, refreshSession, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
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
  return children;
}

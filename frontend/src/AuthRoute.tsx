"use client";

import { AuthPage } from "./AuthPage";
import { AuthRouteLoading, useAuth } from "./AuthProvider";
import { defaultRouteForAccount, safeInternalPath } from "./auth";
import { Navigate, useSearchParams } from "./next-router-compat";

export function AuthRoute() {
  const { user, account, isLoading } = useAuth();
  const [searchParams] = useSearchParams();
  const requestedReturnTo = searchParams.get("returnTo") || "/contracts";
  const returnTo = safeInternalPath(requestedReturnTo);
  const view = searchParams.get("view");
  const resetToken = searchParams.get("token");
  const allowAuthScreen = searchParams.get("signedOut") === "1" || searchParams.get("reset") === "complete";
  const initialView = view === "sign-up" || view === "forgot-password" || view === "verify-email"
    ? view
    : view === "reset-password" || resetToken
      ? "reset-password"
      : "sign-in";

  if (isLoading) return <AuthRouteLoading label="Checking your session" />;
  if (user && initialView !== "reset-password" && !allowAuthScreen) {
    if (!user.emailVerified) return <AuthPage initialView="verify-email" initialEmail={user.email} redirectTo={returnTo} />;
    return <Navigate to={account?.role === "super_admin" ? "/admin" : returnTo || defaultRouteForAccount(account)} replace />;
  }
  return <AuthPage initialView={initialView} initialEmail={user?.email} redirectTo={returnTo} />;
}

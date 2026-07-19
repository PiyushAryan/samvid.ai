import "./styles.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import { Navigate, NavLink, Route, BrowserRouter as Router, Routes, useSearchParams } from "react-router-dom";
import { TooltipProvider } from "./components/ui/tooltip";
import { Skeleton } from "./components/ui/skeleton";
import { AuthProvider, RequireAuth, useAuth } from "./AuthProvider";
import { safeInternalPath } from "./auth";

const LandingPage = lazy(() => import("./Home").then((module) => ({ default: module.LandingPage })));
const ChangelogPage = lazy(() => import("./Changelog").then((module) => ({ default: module.ChangelogPage })));
const AppShell = lazy(() => import("./App").then((module) => ({ default: module.AppShell })));
const ContractsPage = lazy(() => import("./App").then((module) => ({ default: module.ContractsPage })));
const ChatsPage = lazy(() => import("./App").then((module) => ({ default: module.ChatsPage })));
const ContractDetailPage = lazy(() => import("./App").then((module) => ({ default: module.ContractDetailPage })));
const SigningPage = lazy(() => import("./App").then((module) => ({ default: module.SigningPage })));
const AuthPage = lazy(() => import("./AuthPage"));

function AuthRoute() {
  const { user, isLoading } = useAuth();
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

  if (isLoading) {
    return (
      <main className="auth-route-loading" aria-label="Checking your session" aria-busy="true">
        <Skeleton className="auth-route-loading-mark" />
        <Skeleton className="auth-route-loading-line" />
      </main>
    );
  }
  if (user && initialView !== "reset-password" && !allowAuthScreen) {
    if (!user.emailVerified) {
      return <AuthPage initialView="verify-email" initialEmail={user.email} redirectTo={returnTo} />;
    }
    return <Navigate to={returnTo} replace />;
  }
  return <AuthPage initialView={initialView} initialEmail={user?.email} redirectTo={returnTo} />;
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false
    },
    mutations: {
      retry: 0
    }
  }
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={350} skipDelayDuration={100}>
        <Router>
          <AuthProvider>
            <Suspense fallback={null}>
              <Routes>
                <Route path="/" element={<LandingPage />} />
                <Route path="/changelog" element={<ChangelogPage />} />
                <Route path="/auth" element={<AuthRoute />} />
                <Route element={<RequireAuth><AppShell /></RequireAuth>}>
                  <Route path="/contracts" element={<ContractsPage />} />
                  <Route path="/chats" element={<ChatsPage />} />
                  <Route path="/contracts/:contractId" element={<ContractDetailPage />} />
                  <Route path="/signing" element={<SigningPage />} />
                </Route>
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Suspense>
          </AuthProvider>
        </Router>
      </TooltipProvider>
    </QueryClientProvider>
  </React.StrictMode>
);

export { NavLink };

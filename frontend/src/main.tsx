import "./styles.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import { Navigate, NavLink, Route, BrowserRouter as Router, Routes } from "react-router-dom";

const LandingPage = lazy(() => import("./Home").then((module) => ({ default: module.LandingPage })));
const ChangelogPage = lazy(() => import("./Changelog").then((module) => ({ default: module.ChangelogPage })));
const AppShell = lazy(() => import("./App").then((module) => ({ default: module.AppShell })));
const ContractsPage = lazy(() => import("./App").then((module) => ({ default: module.ContractsPage })));
const ContractDetailPage = lazy(() => import("./App").then((module) => ({ default: module.ContractDetailPage })));
const SigningPage = lazy(() => import("./App").then((module) => ({ default: module.SigningPage })));

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
      <Router>
        <Suspense fallback={null}>
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/changelog" element={<ChangelogPage />} />
            <Route element={<AppShell />}>
              <Route path="/contracts" element={<ContractsPage />} />
              <Route path="/contracts/:contractId" element={<ContractDetailPage />} />
              <Route path="/signing" element={<SigningPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </Router>
    </QueryClientProvider>
  </React.StrictMode>
);

export { NavLink };

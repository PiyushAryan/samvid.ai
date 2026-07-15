import "./styles.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { Navigate, NavLink, Route, BrowserRouter as Router, Routes } from "react-router-dom";
import { AppShell, ContractDetailPage, ContractsPage, SigningPage } from "./App";
import { ChangelogPage } from "./ChangelogPage";
import { LandingPage } from "./Home";

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
      </Router>
    </QueryClientProvider>
  </React.StrictMode>
);

export { NavLink };

"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { AuthProvider } from "../AuthProvider";
import { TooltipProvider } from "../components/ui/tooltip";

export function AppProviders({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: { retry: 1, refetchOnWindowFocus: false },
      mutations: { retry: 0 }
    }
  }));

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={350} skipDelayDuration={100}>
        <AuthProvider>{children}</AuthProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}

import type { Metadata } from "next";
import { Suspense, type ReactNode } from "react";

import "@/components/ai-elements/styles.css";

import { AppShell } from "@/features/workspace/app-shell";
import { RequireUser } from "@/features/auth/auth-provider";
import { AppProviders } from "../providers";

export const metadata: Metadata = {
  robots: { index: false, follow: false, nocache: true }
};

export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  return (
    <AppProviders>
      <Suspense fallback={null}>
        <RequireUser><AppShell>{children}</AppShell></RequireUser>
      </Suspense>
    </AppProviders>
  );
}

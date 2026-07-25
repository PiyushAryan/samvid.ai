import type { Metadata } from "next";
import { Suspense, type ReactNode } from "react";

import { AdminShell } from "../../../Admin";
import { RequireSuperAdmin } from "../../../AuthProvider";
import { AppProviders } from "../../providers";

export const metadata: Metadata = {
  robots: { index: false, follow: false, nocache: true }
};

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <AppProviders>
      <Suspense fallback={null}>
        <RequireSuperAdmin><AdminShell>{children}</AdminShell></RequireSuperAdmin>
      </Suspense>
    </AppProviders>
  );
}

import type { Metadata } from "next";
import { Suspense, type ReactNode } from "react";
import workspaceStyles from "@/features/workspace/workspace-shell.module.css";
import contractStyles from "@/features/contracts/contracts.module.css";
import signingStyles from "@/features/signing/signing.module.css";
import adminStyles from "@/features/admin/admin.module.css";

import { AdminShell } from "@/features/admin/admin-shell";
import { RequireSuperAdmin } from "@/features/auth/auth-provider";
import { AppProviders } from "../../providers";

export const metadata: Metadata = {
  robots: { index: false, follow: false, nocache: true }
};

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <div className={`${workspaceStyles.scope} ${contractStyles.scope} ${signingStyles.scope} ${adminStyles.scope}`}>
      <AppProviders>
        <Suspense fallback={null}>
          <RequireSuperAdmin><AdminShell>{children}</AdminShell></RequireSuperAdmin>
        </Suspense>
      </AppProviders>
    </div>
  );
}

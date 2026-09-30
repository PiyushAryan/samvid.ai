import type { Metadata } from "next";
import { Suspense, type ReactNode } from "react";

import "@/components/ai-elements/styles.css";
import workspaceStyles from "@/features/workspace/workspace-shell.module.css";
import chatStyles from "@/features/chat/chat.module.css";
import contractStyles from "@/features/contracts/contracts.module.css";
import signingStyles from "@/features/signing/signing.module.css";
import settingsStyles from "@/features/settings/settings.module.css";

import { AppShell } from "@/features/workspace/app-shell";
import { RequireUser } from "@/features/auth/auth-provider";
import { AppProviders } from "../providers";

export const metadata: Metadata = {
  robots: { index: false, follow: false, nocache: true }
};

export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  return (
    <div className={`${workspaceStyles.scope} ${chatStyles.scope} ${contractStyles.scope} ${signingStyles.scope} ${settingsStyles.scope}`}>
      <AppProviders>
        <Suspense fallback={null}>
          <RequireUser><AppShell>{children}</AppShell></RequireUser>
        </Suspense>
      </AppProviders>
    </div>
  );
}

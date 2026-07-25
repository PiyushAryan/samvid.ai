import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthRoute } from "../../../AuthRoute";
import { AppProviders } from "../../providers";

export const metadata: Metadata = {
  title: "Account access",
  robots: { index: false, follow: false, nocache: true }
};

export default function AuthPageRoute() {
  return <AppProviders><Suspense fallback={null}><AuthRoute /></Suspense></AppProviders>;
}

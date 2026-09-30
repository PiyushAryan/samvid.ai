import type { ReactNode } from "react";

import "@/features/marketing/home.css";
import "@/features/marketing/changelog.css";
import "@/features/marketing/book-demo.css";

export default function MarketingLayout({ children }: { children: ReactNode }) {
  return children;
}

import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import "../styles.css";
import "../auth.css";
import "../home.css";
import "../changelog.css";
import "../book-demo.css";

const siteUrl = new URL(process.env.NEXT_PUBLIC_SITE_URL || "https://samvid.online");

export const metadata: Metadata = {
  metadataBase: siteUrl,
  title: {
    default: "Samvid | Contract intelligence from inbox to signature",
    template: "%s | Samvid"
  },
  description: "Samvid helps teams review contracts, explain material risks, preserve evidence, and keep signing workflows moving.",
  openGraph: {
    type: "website",
    locale: "en_US",
    url: "/",
    siteName: "Samvid",
    title: "Samvid | Contract intelligence from inbox to signature",
    description: "Review contracts, explain risk, and keep every handoff moving.",
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: "Samvid contract intelligence" }]
  },
  twitter: {
    card: "summary_large_image",
    title: "Samvid | Contract intelligence from inbox to signature",
    description: "Review contracts, explain risk, and keep every handoff moving.",
    images: ["/opengraph-image"]
  },
  icons: {
    icon: [
      { url: "/favicon-light.svg", type: "image/svg+xml", media: "(prefers-color-scheme: light)" },
      { url: "/favicon-dark.svg", type: "image/svg+xml", media: "(prefers-color-scheme: dark)" }
    ]
  }
};

export const viewport: Viewport = {
  colorScheme: "light dark",
  themeColor: "#fbfcf9"
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

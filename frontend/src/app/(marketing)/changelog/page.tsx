import type { Metadata } from "next";

import { ChangelogPage } from "../../../Changelog";

export const metadata: Metadata = {
  title: "Changelog",
  description: "Product updates, new contract intelligence capabilities, and workflow improvements from Samvid.",
  alternates: { canonical: "/changelog" },
  openGraph: {
    title: "Changelog | Samvid",
    description: "Product updates, new contract intelligence capabilities, and workflow improvements from Samvid.",
    url: "/changelog",
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: "Samvid product updates" }]
  },
  twitter: {
    title: "Changelog | Samvid",
    description: "Product updates, new contract intelligence capabilities, and workflow improvements from Samvid.",
    images: ["/opengraph-image"]
  }
};

export default function ChangelogRoute() {
  return <ChangelogPage />;
}

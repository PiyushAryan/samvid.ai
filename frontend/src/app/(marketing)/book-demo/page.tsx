import type { Metadata } from "next";

import { BookDemoClient } from "./BookDemoClient";

export const metadata: Metadata = {
  title: "Book a contract workflow demo",
  description: "Book a focused Samvid walkthrough for your contract review, approval, and signing workflow.",
  alternates: { canonical: "/book-demo" },
  openGraph: {
    title: "Book a contract workflow demo | Samvid",
    description: "Book a focused Samvid walkthrough for your contract review, approval, and signing workflow.",
    url: "/book-demo",
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: "Book a Samvid contract workflow demo" }]
  },
  twitter: {
    title: "Book a contract workflow demo | Samvid",
    description: "Book a focused Samvid walkthrough for your contract review, approval, and signing workflow.",
    images: ["/opengraph-image"]
  }
};

export default function BookDemoRoute() {
  return <BookDemoClient />;
}

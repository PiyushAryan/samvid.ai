"use client";

import dynamic from "next/dynamic";

const BookDemoPage = dynamic(
  () => import("@/features/marketing/book-demo-page").then((module) => module.BookDemoPage),
  {
    ssr: false,
    loading: () => null
  }
);

export function BookDemoClient() {
  return <BookDemoPage />;
}

"use client";

import dynamic from "next/dynamic";

const BookDemoPage = dynamic(
  () => import("../../../BookDemo").then((module) => module.BookDemoPage),
  {
    ssr: false,
    loading: () => null
  }
);

export function BookDemoClient() {
  return <BookDemoPage />;
}

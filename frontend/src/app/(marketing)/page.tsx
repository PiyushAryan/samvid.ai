import type { Metadata } from "next";

import { LandingPage } from "../../Home";

export const metadata: Metadata = {
  title: "Contract intelligence from inbox to signature",
  description: "Forward or upload a contract, get evidence-grounded review and risk guidance, then keep every signing handoff moving in Samvid.",
  alternates: { canonical: "/" }
};

const structuredData = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      name: "Samvid",
      url: "https://samvid.online",
      logo: "https://samvid.online/favicon-light.svg"
    },
    {
      "@type": "WebSite",
      name: "Samvid",
      url: "https://samvid.online"
    }
  ]
};

export default function HomePage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData).replace(/</g, "\\u003c") }}
      />
      <LandingPage />
    </>
  );
}

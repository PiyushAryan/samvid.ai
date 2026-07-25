import type { MetadataRoute } from "next";

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://samvid.online";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: `${siteUrl}/`, lastModified: new Date("2026-07-25"), changeFrequency: "weekly", priority: 1 },
    { url: `${siteUrl}/changelog`, lastModified: new Date("2026-07-16"), changeFrequency: "weekly", priority: 0.8 },
    { url: `${siteUrl}/book-demo`, changeFrequency: "monthly", priority: 0.7 }
  ];
}

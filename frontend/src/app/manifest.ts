import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Samvid",
    short_name: "Samvid",
    description: "Contract intelligence from inbox to signature.",
    start_url: "/",
    display: "standalone",
    background_color: "#fbfcf9",
    theme_color: "#0c9488",
    icons: [
      { src: "/favicon-light.svg", type: "image/svg+xml", sizes: "any" },
      { src: "/favicon-dark.svg", type: "image/svg+xml", sizes: "any" }
    ]
  };
}

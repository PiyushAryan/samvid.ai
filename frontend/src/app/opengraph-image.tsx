import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { ImageResponse } from "next/og";

export const alt = "Samvid — One teammate to review, track, and remember every contract";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

function imageSource(data: Buffer): ArrayBuffer {
  return Uint8Array.from(data).buffer;
}

export default async function OpenGraphImage() {
  const [blrHero, roadScene, geistRegular, geistBold, geistPixel] = await Promise.all([
    readFile(join(process.cwd(), "public/og-blr-hero.jpg")),
    readFile(join(process.cwd(), "public/og-road-tuktuk-bike.png")),
    readFile(join(process.cwd(), "node_modules/geist/dist/fonts/geist-sans/Geist-Regular.ttf")),
    readFile(join(process.cwd(), "node_modules/geist/dist/fonts/geist-sans/Geist-Bold.ttf")),
    readFile(join(process.cwd(), "node_modules/geist/dist/fonts/geist-mono/GeistMono-Regular.ttf"))
  ]);

  return new ImageResponse(
    (
      <div
        style={{
          alignItems: "center",
          background: "#f6f7f4",
          color: "#0f172a",
          display: "flex",
          fontFamily: "Geist",
          height: "100%",
          justifyContent: "center",
          overflow: "hidden",
          position: "relative",
          width: "100%"
        }}
      >
        <img
          alt=""
          src={imageSource(blrHero) as unknown as string}
          style={{
            height: "100%",
            inset: 0,
            objectFit: "cover",
            objectPosition: "center center",
            position: "absolute",
            width: "100%"
          }}
        />
        <div
          style={{
            background: "linear-gradient(180deg, rgba(248, 250, 250, 0.12) 0%, rgba(248, 250, 250, 0.2) 60%, rgba(246, 247, 244, 0.62) 100%)",
            display: "flex",
            inset: 0,
            position: "absolute"
          }}
        />
        <img
          alt=""
          src={imageSource(roadScene) as unknown as string}
          style={{
            height: "100%",
            inset: 0,
            objectFit: "cover",
            objectPosition: "center bottom",
            position: "absolute",
            transform: "translateY(8px)",
            width: "100%"
          }}
        />

        <div
          style={{
            alignItems: "center",
            display: "flex",
            flexDirection: "column",
            height: "100%",
            padding: "54px 44px 0",
            position: "relative",
            textAlign: "center",
            width: "100%"
          }}
        >
          <div
            style={{
              color: "#285a55",
              display: "flex",
              fontFamily: "Geist Pixel",
              fontSize: 12,
              letterSpacing: "0.08em"
            }}
          >
            BUILT FOR LEGAL &amp; PROCUREMENT TEAMS
          </div>
          <div
            style={{
              color: "#285a55",
              display: "flex",
              fontFamily: "Geist Pixel",
              fontSize: 28,
              lineHeight: 1.2,
              marginTop: 42
            }}
          >
            One teammate to keep every contract
          </div>
          <div
            style={{
              alignItems: "baseline",
              display: "flex",
              fontSize: 66,
              fontWeight: 700,
              letterSpacing: "-0.045em",
              lineHeight: 1,
              marginTop: 8
            }}
          >
            <span>review. track.&nbsp;</span>
            <span style={{ color: "#0d9488" }}>remember.</span>
          </div>
          <div
            style={{
              color: "#334155",
              display: "flex",
              fontFamily: "Geist Pixel",
              fontSize: 20,
              justifyContent: "center",
              lineHeight: 1.5,
              marginTop: 30,
              maxWidth: 820
            }}
          >
            Forward a contract or upload it. Samvid reads every page, explains the risk, keeps every version organized, and records each signing handoff.
          </div>
          <div style={{ display: "flex", gap: 12, marginTop: 32 }}>
            <div
              style={{
                alignItems: "center",
                background: "rgba(251, 252, 249, 0.94)",
                border: "1px solid rgba(15, 23, 42, 0.1)",
                borderRadius: 8,
                display: "flex",
                fontSize: 18,
                fontWeight: 600,
                height: 52,
                justifyContent: "center",
                padding: "0 24px"
              }}
            >
              Mail it. Chill.
            </div>
            <div
              style={{
                alignItems: "center",
                background: "#0d9488",
                borderRadius: 8,
                color: "#fff",
                display: "flex",
                fontSize: 18,
                fontWeight: 600,
                gap: 10,
                height: 52,
                justifyContent: "center",
                padding: "0 24px"
              }}
            >
              Open Workspace <span style={{ fontSize: 25 }}>→</span>
            </div>
          </div>
        </div>
      </div>
    ),
    {
      ...size,
      fonts: [
        { data: imageSource(geistRegular), name: "Geist", weight: 400 },
        { data: imageSource(geistBold), name: "Geist", weight: 700 },
        { data: imageSource(geistPixel), name: "Geist Pixel", weight: 400 }
      ]
    }
  );
}

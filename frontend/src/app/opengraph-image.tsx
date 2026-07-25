import { ImageResponse } from "next/og";

export const alt = "Samvid contract intelligence";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div style={{
        alignItems: "flex-start",
        background: "linear-gradient(135deg, #f7fbf8 0%, #d9f5ef 100%)",
        color: "#12201e",
        display: "flex",
        flexDirection: "column",
        height: "100%",
        justifyContent: "center",
        padding: "72px",
        width: "100%"
      }}>
        <div style={{ color: "#0c9488", display: "flex", fontSize: 34, fontWeight: 700, letterSpacing: "-1px" }}>samvid</div>
        <div style={{ display: "flex", fontSize: 72, fontWeight: 700, letterSpacing: "-3px", lineHeight: 1.06, marginTop: 28, maxWidth: 900 }}>
          Contract intelligence from inbox to signature.
        </div>
        <div style={{ color: "#48615c", display: "flex", fontSize: 30, marginTop: 34 }}>
          Review contracts, explain risk, and keep every handoff moving.
        </div>
      </div>
    ),
    size
  );
}

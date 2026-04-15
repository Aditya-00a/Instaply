import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "Instaply — $1 per confirmed job application";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/**
 * Dynamically generated OpenGraph image served at /opengraph-image.
 * Rendered by Next.js at the edge so no static asset file is needed.
 * Keeps the Coinbase-clean look: big wordmark, headline, blue accent.
 */
export default async function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          background:
            "linear-gradient(135deg, #f7f9fc 0%, #e7eefb 50%, #d8e4fd 100%)",
          padding: "80px 96px",
          position: "relative",
          fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif",
        }}
      >
        {/* Accent orb */}
        <div
          style={{
            position: "absolute",
            top: -180,
            right: -180,
            width: 540,
            height: 540,
            borderRadius: 9999,
            background:
              "radial-gradient(circle, rgba(0, 82, 255, 0.22), transparent 70%)",
          }}
        />

        {/* Brand row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            fontSize: 28,
            fontWeight: 700,
            color: "#0a0b0d",
            letterSpacing: "-0.02em",
          }}
        >
          <div
            style={{
              width: 16,
              height: 16,
              borderRadius: 9999,
              background: "#0052ff",
              boxShadow: "0 0 0 6px rgba(0, 82, 255, 0.2)",
            }}
          />
          Instaply
        </div>

        {/* Headline */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 20,
            marginTop: "auto",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              fontSize: 20,
              fontWeight: 600,
              color: "#0052ff",
              background: "rgba(0, 82, 255, 0.12)",
              padding: "8px 18px",
              borderRadius: 999,
              alignSelf: "flex-start",
            }}
          >
            Agentic job applications
          </div>
          <div
            style={{
              fontSize: 84,
              fontWeight: 700,
              color: "#0a0b0d",
              letterSpacing: "-0.035em",
              lineHeight: 1.02,
              maxWidth: 960,
            }}
          >
            $1 per confirmed job application.
          </div>
          <div
            style={{
              fontSize: 28,
              color: "#5b616e",
              lineHeight: 1.4,
              maxWidth: 860,
            }}
          >
            We submit applications to Greenhouse, Lever, SmartRecruiters,
            and Workday on your behalf.
          </div>
        </div>

        {/* Footer band */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: 40,
            paddingTop: 24,
            borderTop: "1px solid rgba(10, 11, 13, 0.08)",
            fontSize: 20,
            color: "#5b616e",
          }}
        >
          <div style={{ display: "flex", gap: 24 }}>
            <span>instaply.asion.ai</span>
          </div>
          <div style={{ display: "flex", gap: 18, color: "#0a0b0d" }}>
            <span>No subscriptions</span>
            <span>·</span>
            <span>3 free on signup</span>
          </div>
        </div>
      </div>
    ),
    { ...size }
  );
}

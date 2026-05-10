"use client";

import type { Platform } from "@/types/api";

interface Props {
  platform: Platform;
}

const PLATFORM_LABEL: Record<Platform, string> = {
  vinted: "Vinted",
  kleinanzeigen: "Kleinanzeigen",
};

const ACCENT = "oklch(0.62 0.15 145)";

export default function PublishingScreen({ platform }: Props) {
  return (
    <div
      style={{
        height: "100dvh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "#fafaf8",
        color: "#0e0f0e",
        fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
        padding: "0 24px",
        gap: 24,
      }}
    >
      {/* Logo */}
      <div
        style={{
          width: 22,
          height: 22,
          borderRadius: 6,
          backgroundColor: ACCENT,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div style={{ width: 8, height: 8, borderRadius: 2, backgroundColor: "#fff" }} />
      </div>

      {/* Spinner */}
      <div
        style={{
          width: 36,
          height: 36,
          border: "3px solid #e7e5e0",
          borderTopColor: ACCENT,
          borderRadius: "50%",
          animation: "rcSpin 0.8s linear infinite",
        }}
      />

      <div style={{ textAlign: "center" }}>
        <p
          style={{
            fontSize: 17,
            fontWeight: 600,
            letterSpacing: "-0.3px",
            margin: "0 0 8px",
          }}
        >
          Publishing on {PLATFORM_LABEL[platform]}…
        </p>
        <p
          style={{
            fontSize: 13,
            color: "#6b6c6a",
            margin: 0,
            textAlign: "center",
            lineHeight: 1.5,
            maxWidth: 280,
          }}
        >
          Uploading your photo and posting the listing. Usually 5–10 seconds; cold starts can be longer.
        </p>
      </div>

      <style>{`@keyframes rcSpin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

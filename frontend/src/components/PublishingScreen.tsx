"use client";

import type { Platform } from "@/types/api";

interface Props {
  platform: Platform;
}

const PLATFORM_LABEL: Record<Platform, string> = {
  vinted: "Vinted",
  kleinanzeigen: "Kleinanzeigen",
};

export default function PublishingScreen({ platform }: Props) {
  return (
    <div
      style={{
        minHeight: "100dvh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "var(--color-bg)",
        color: "var(--color-ink)",
        fontFamily: "var(--font-sans)",
        padding: "0 24px",
        gap: 16,
      }}
    >
      <div
        style={{
          width: 36,
          height: 36,
          border: "3px solid var(--color-border)",
          borderTopColor: "var(--color-ink)",
          borderRadius: "50%",
          animation: "spin 0.8s linear infinite",
        }}
      />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <p style={{ fontSize: 17, fontWeight: 600, letterSpacing: "-0.3px", margin: 0 }}>
        Preparing draft on {PLATFORM_LABEL[platform]}…
      </p>
      <p style={{ fontSize: 13, color: "var(--color-ink-secondary)", margin: 0, textAlign: "center", lineHeight: 1.5 }}>
        Uploading your photo and filling in all fields.
        You&apos;ll review and publish on {PLATFORM_LABEL[platform]} yourself.
      </p>
    </div>
  );
}

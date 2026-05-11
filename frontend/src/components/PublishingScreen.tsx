"use client";

import type { Platform } from "@/types/api";

type ProgressState = "pending" | "posted" | "failed";

interface Props {
  platforms: Platform[];
  progress: Record<Platform, ProgressState>;
}

const PLATFORM_LABEL: Record<Platform, string> = {
  vinted: "Vinted",
  kleinanzeigen: "Kleinanzeigen",
};

const PLATFORM_ACCENT: Record<Platform, string> = {
  vinted: "oklch(0.55 0.08 195)",
  kleinanzeigen: "oklch(0.62 0.13 55)",
};

const SUCCESS = "oklch(0.62 0.15 145)";
const ERROR_RED = "#c0392b";

export default function PublishingScreen({ platforms, progress }: Props) {
  const allDone = platforms.every((p) => progress[p] !== "pending");
  const subtitle = allDone
    ? "Wrapping up…"
    : platforms.length > 1
      ? "Posting both listings in parallel. Usually 5–15 seconds."
      : "Posting the listing. Usually 5–10 seconds.";

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
        gap: 28,
      }}
    >
      {/* Logo */}
      <div
        style={{
          width: 22,
          height: 22,
          borderRadius: 6,
          backgroundColor: SUCCESS,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div style={{ width: 8, height: 8, borderRadius: 2, backgroundColor: "#fff" }} />
      </div>

      {/* Per-platform rows */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 12,
          width: "100%",
          maxWidth: 340,
        }}
      >
        {platforms.map((p) => (
          <PlatformRow key={p} platform={p} state={progress[p] ?? "pending"} />
        ))}
      </div>

      <p
        style={{
          fontSize: 12,
          color: "#9b9c99",
          textAlign: "center",
          maxWidth: 320,
          margin: 0,
          lineHeight: 1.5,
        }}
      >
        {subtitle}
      </p>

      <style>{`@keyframes rcSpin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

function PlatformRow({ platform, state }: { platform: Platform; state: ProgressState }) {
  const accent = PLATFORM_ACCENT[platform];
  const label = PLATFORM_LABEL[platform];
  const status =
    state === "pending" ? "Posting…" : state === "posted" ? "Posted" : "Failed";
  const statusColor = state === "failed" ? ERROR_RED : "#6b6c6a";
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 14,
        padding: "14px 16px",
        borderRadius: 14,
        background: "#fff",
        border: `1px solid ${state === "failed" ? "#f5c6c0" : "#e7e5e0"}`,
      }}
    >
      <StatusIcon state={state} accent={accent} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <p
          style={{
            margin: 0,
            fontSize: 14,
            fontWeight: 600,
            color: "#0e0f0e",
            letterSpacing: "-0.1px",
          }}
        >
          {label}
        </p>
        <p style={{ margin: "2px 0 0", fontSize: 12, color: statusColor }}>{status}</p>
      </div>
    </div>
  );
}

function StatusIcon({ state, accent }: { state: ProgressState; accent: string }) {
  if (state === "pending") {
    return (
      <div
        style={{
          width: 24,
          height: 24,
          border: "2.5px solid #e7e5e0",
          borderTopColor: accent,
          borderRadius: "50%",
          animation: "rcSpin 0.8s linear infinite",
          flexShrink: 0,
        }}
      />
    );
  }
  if (state === "posted") {
    return (
      <div
        style={{
          width: 24,
          height: 24,
          borderRadius: "50%",
          background: SUCCESS,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
          <path
            d="M3 7l2.5 2.5L10 4"
            stroke="#fff"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
    );
  }
  return (
    <div
      style={{
        width: 24,
        height: 24,
        borderRadius: "50%",
        background: ERROR_RED,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}
    >
      <svg width="11" height="11" viewBox="0 0 11 11" fill="none">
        <path
          d="M2 2l7 7M9 2l-7 7"
          stroke="#fff"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
    </div>
  );
}

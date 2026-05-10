"use client";

import type { OnboardingStatus, Platform } from "@/types/api";

interface Props {
  status: OnboardingStatus | null;
  onConnect: (platform: Platform) => void;
}

const LABEL: Record<Platform, string> = {
  vinted: "Vinted",
  kleinanzeigen: "Kleinanzeigen",
};

function isDisconnected(state: string): boolean {
  return state === "needs_login" || state === "expired" || state === "not_configured";
}

export default function PlatformConnectionBanner({ status, onConnect }: Props) {
  if (status === null) return null;

  const disconnected: Platform[] = (["vinted", "kleinanzeigen"] as Platform[]).filter(
    (p) => isDisconnected(status[p].state),
  );
  if (disconnected.length === 0) return null;

  return (
    <div
      style={{
        backgroundColor: "oklch(0.96 0.04 80)",
        borderBottom: "1px solid oklch(0.86 0.10 80)",
        padding: "10px 24px",
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: 12,
        fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
        fontSize: 13,
        color: "#3d3a2a",
      }}
    >
      <span
        style={{
          fontFamily: '"JetBrains Mono", ui-monospace, monospace',
          fontSize: 10.5,
          letterSpacing: "1.2px",
          textTransform: "uppercase",
          color: "oklch(0.45 0.08 75)",
        }}
      >
        Reconnect
      </span>
      {disconnected.map((p) => (
        <button
          key={p}
          type="button"
          onClick={() => onConnect(p)}
          style={{
            padding: "6px 12px",
            borderRadius: 999,
            border: "1px solid oklch(0.62 0.15 145)",
            backgroundColor: "#fff",
            color: "oklch(0.45 0.12 145)",
            fontSize: 12,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          Connect {LABEL[p]}
        </button>
      ))}
      <span style={{ marginLeft: "auto", fontSize: 12, color: "#6b6c69" }}>
        Identification still works while disconnected — only publishing is blocked.
      </span>
    </div>
  );
}

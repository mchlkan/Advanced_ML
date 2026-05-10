"use client";

import type { OnboardingStatus, Platform } from "@/types/api";
import SmallCaps from "./ui/SmallCaps";

interface Props {
  status: OnboardingStatus | null;
  onConnect: (platform: Platform) => void;
}

const LABEL: Record<Platform, string> = {
  vinted: "Vinted",
  kleinanzeigen: "Kleinanzeigen",
};

const PLATFORM_DOT: Record<Platform, string> = {
  vinted: "oklch(0.55 0.08 195)",
  kleinanzeigen: "oklch(0.62 0.13 55)",
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
        backgroundColor: "#fff",
        borderBottom: "1px solid #e7e5e0",
        padding: "10px 24px",
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: 12,
        fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
        fontSize: 13,
        color: "#3a3b3a",
      }}
    >
      <SmallCaps size={10.5}>Reconnect</SmallCaps>
      {disconnected.map((p) => (
        <button
          key={p}
          type="button"
          onClick={() => onConnect(p)}
          title="Identification still works while disconnected — only publishing is blocked."
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "5px 11px",
            borderRadius: 999,
            border: "1px solid #e7e5e0",
            backgroundColor: "#fff",
            color: "#0e0f0e",
            fontSize: 12,
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: 6,
              background: PLATFORM_DOT[p],
            }}
          />
          {LABEL[p]}
        </button>
      ))}
    </div>
  );
}

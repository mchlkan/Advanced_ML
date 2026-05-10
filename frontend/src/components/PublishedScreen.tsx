"use client";

import { useRef } from "react";
import type { Platform, UploadResponse } from "@/types/api";
import SmallCaps from "./ui/SmallCaps";

interface Props {
  platform: Platform;
  listingUrl: string;
  results: UploadResponse;
  onReset: () => void;
}

const PLATFORM_LABEL: Record<Platform, string> = {
  vinted: "Vinted",
  kleinanzeigen: "Kleinanzeigen",
};

function fmt(n: number) {
  return `€${Math.round(n)}`;
}

function shortId(id: string) {
  return id.slice(0, 8);
}

const ACCENT = "oklch(0.62 0.15 145)";

export default function PublishedScreen({ platform, listingUrl, results, onReset }: Props) {
  const tabRef = useRef<Window | null>(null);

  const otherPlatform: Platform = platform === "vinted" ? "kleinanzeigen" : "vinted";
  const activeBlock = platform === "vinted" ? results.vinted : results.kleinanzeigen;
  const otherBlock = platform === "vinted" ? results.kleinanzeigen : results.vinted;

  function reopenTab() {
    if (tabRef.current && !tabRef.current.closed) {
      tabRef.current.focus();
    } else {
      tabRef.current = window.open(listingUrl, "_blank") ?? null;
    }
  }

  return (
    <div
      style={{
        height: "100dvh",
        display: "flex",
        flexDirection: "column",
        backgroundColor: "#fafaf8",
        color: "#0e0f0e",
        fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
        boxSizing: "border-box",
      }}
    >
      {/* Header */}
      <header style={{ padding: "20px 24px 16px", display: "flex", alignItems: "center", gap: 8 }}>
        <div
          style={{
            width: 22,
            height: 22,
            borderRadius: 6,
            backgroundColor: ACCENT,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <div style={{ width: 8, height: 8, borderRadius: 2, backgroundColor: "#fff" }} />
        </div>
        <span style={{ fontSize: 15, fontWeight: 600, letterSpacing: "-0.2px" }}>
          Resell Copilot
        </span>
      </header>

      <div
        style={{
          flex: 1,
          overflowY: "auto",
          WebkitOverflowScrolling: "touch",
          padding: "8px 20px 0",
        } as React.CSSProperties}
      >
        {/* Receipt card */}
        <div
          style={{
            background: "#fff",
            borderRadius: 18,
            border: "1px solid #e7e5e0",
            padding: "22px 22px 20px",
          }}
        >
          {/* Status badge */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginBottom: 18,
            }}
          >
            <div
              style={{
                width: 6,
                height: 6,
                borderRadius: 6,
                background: ACCENT,
                boxShadow: "0 0 0 4px oklch(0.62 0.15 145 / 0.15)",
              }}
            />
            <SmallCaps size={10.5}>Live on {PLATFORM_LABEL[platform]}</SmallCaps>
          </div>

          <h2
            style={{
              margin: 0,
              fontSize: 24,
              fontWeight: 600,
              letterSpacing: "-0.7px",
              lineHeight: 1.15,
              textWrap: "balance",
            } as React.CSSProperties}
          >
            Your listing is live on {PLATFORM_LABEL[platform]}.
          </h2>
          <p
            style={{
              margin: "10px 0 0",
              fontSize: 14,
              color: "#6b6c6a",
              lineHeight: 1.5,
            }}
          >
            We opened it in a new tab so you can give it a final check or share
            the link.
          </p>

          {/* Summary */}
          <div
            style={{
              marginTop: 22,
              paddingTop: 18,
              borderTop: "1px solid #efece6",
              fontSize: 14,
              color: "#3a3b3a",
              lineHeight: 1.5,
            }}
          >
            <div style={{ color: "#0e0f0e", fontWeight: 500 }}>
              {PLATFORM_LABEL[platform]} · {fmt(activeBlock.price.q50)}
            </div>
            <div
              style={{
                marginTop: 4,
                fontFamily: '"JetBrains Mono", ui-monospace, monospace',
                fontSize: 11,
                color: "#9b9c99",
                letterSpacing: "0.06em",
              }}
            >
              #{shortId(results.listing_id)}
            </div>
          </div>

          {/* Reopen button */}
          <button
            onClick={reopenTab}
            style={{
              marginTop: 20,
              width: "100%",
              padding: "12px 14px",
              borderRadius: 12,
              border: "1px solid #e7e5e0",
              background: "#fff",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
              fontSize: 14,
              fontWeight: 500,
              color: "#0e0f0e",
            }}
          >
            <span>Reopen {PLATFORM_LABEL[platform]} tab</span>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path
                d="M5 2h7v7M12 2L5 9M2 6v6h6"
                stroke="#0e0f0e"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>

        {/* Cross-post tip */}
        <div
          style={{
            marginTop: 16,
            padding: "12px 14px",
            borderRadius: 12,
            background: "#fff",
            border: "1px solid #efece6",
            display: "flex",
            alignItems: "flex-start",
            gap: 10,
            fontSize: 13,
            color: "#3a3b3a",
            lineHeight: 1.45,
          }}
        >
          <div
            style={{
              width: 18,
              height: 18,
              borderRadius: 9,
              flexShrink: 0,
              background: "oklch(0.62 0.13 55 / 0.1)",
              color: "oklch(0.62 0.13 55)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 12,
              fontWeight: 700,
            }}
          >
            i
          </div>
          <div>
            Want to cross-post? You can also publish to{" "}
            <span style={{ color: "#0e0f0e", fontWeight: 600 }}>
              {PLATFORM_LABEL[otherPlatform]}
            </span>{" "}
            at {fmt(otherBlock.price.q50)} —{" "}
            {otherPlatform === "kleinanzeigen" ? "faster local sale." : "larger fashion audience."}
          </div>
        </div>

        <div style={{ height: 24 }} />
      </div>

      {/* Bottom actions */}
      <div
        style={{
          flexShrink: 0,
          padding: "0 20px calc(20px + env(safe-area-inset-bottom))",
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        <button
          onClick={onReset}
          style={{
            width: "100%",
            height: 54,
            borderRadius: 14,
            border: "1.5px solid #0e0f0e",
            cursor: "pointer",
            background: "#0e0f0e",
            color: "#fff",
            fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
            fontSize: 16,
            fontWeight: 600,
            letterSpacing: "-0.1px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 10,
          }}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M8 3v10M3 8h10" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          Sell another piece
        </button>
        <div
          style={{
            textAlign: "center",
            fontSize: 12,
            color: "#9b9c99",
            paddingBottom: 4,
          }}
        >
          No history kept · No account · Privacy by default
        </div>
      </div>
    </div>
  );
}

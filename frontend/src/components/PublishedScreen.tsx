"use client";

import type { Platform, UploadResponse } from "@/types/api";
import SmallCaps from "./ui/SmallCaps";

export interface PublishOutcome {
  platform: Platform;
  listingUrl: string | null;
  error: string | null;
}

interface Props {
  outcomes: PublishOutcome[];
  results: UploadResponse;
  onReset: () => void;
}

const PLATFORM_LABEL: Record<Platform, string> = {
  vinted: "Vinted",
  kleinanzeigen: "Kleinanzeigen",
};

const PLATFORM_ACCENT: Record<Platform, string> = {
  vinted: "oklch(0.55 0.08 195)",
  kleinanzeigen: "oklch(0.62 0.13 55)",
};

const ACCENT = "oklch(0.62 0.15 145)";

function fmt(n: number) {
  return `€${Math.round(n)}`;
}

function shortId(id: string) {
  return id.slice(0, 8);
}

function priceFor(platform: Platform, results: UploadResponse): number {
  const block = platform === "vinted" ? results.vinted : results.kleinanzeigen;
  return Math.round((block.identification.price_eur as number | null) ?? block.price.q50);
}

function ExternalArrow({ color = "#0e0f0e" }: { color?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path
        d="M5 2h7v7M12 2L5 9M2 6v6h6"
        stroke={color}
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function PublishedScreen({ outcomes, results, onReset }: Props) {
  const successes = outcomes.filter((o) => o.listingUrl);
  const failures = outcomes.filter((o) => !o.listingUrl);
  const successLabels = successes.map((o) => PLATFORM_LABEL[o.platform]);
  const headline =
    successes.length === 0
      ? "Couldn't post the listing."
      : successes.length === 1
        ? `Your listing is live on ${successLabels[0]}.`
        : `Your listings are live on ${successLabels.join(" & ")}.`;
  const subhead =
    successes.length === 0
      ? "Both platforms returned an error — see below."
      : "Tap to open and check or share.";

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
                background: successes.length > 0 ? ACCENT : "#c0392b",
                boxShadow:
                  successes.length > 0
                    ? "0 0 0 4px oklch(0.62 0.15 145 / 0.15)"
                    : "0 0 0 4px oklch(0.55 0.18 25 / 0.15)",
              }}
            />
            <SmallCaps size={10.5}>
              {successes.length === 0
                ? "Publishing failed"
                : successes.length === 1
                  ? `Live on ${successLabels[0]}`
                  : "Live on both"}
            </SmallCaps>
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
            {headline}
          </h2>
          <p
            style={{
              margin: "10px 0 0",
              fontSize: 14,
              color: "#6b6c6a",
              lineHeight: 1.5,
            }}
          >
            {subhead}
          </p>

          {/* Per-platform rows */}
          <div
            style={{
              marginTop: 22,
              paddingTop: 18,
              borderTop: "1px solid #efece6",
              display: "flex",
              flexDirection: "column",
              gap: 12,
            }}
          >
            {outcomes.map((o) => (
              <PlatformRow key={o.platform} outcome={o} priceEur={priceFor(o.platform, results)} />
            ))}
          </div>

          {/* Listing id */}
          <div
            style={{
              marginTop: 18,
              fontFamily: '"JetBrains Mono", ui-monospace, monospace',
              fontSize: 11,
              color: "#9b9c99",
              letterSpacing: "0.06em",
            }}
          >
            #{shortId(results.listing_id)}
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

function PlatformRow({
  outcome,
  priceEur,
}: {
  outcome: PublishOutcome;
  priceEur: number;
}) {
  const accent = PLATFORM_ACCENT[outcome.platform];
  const label = PLATFORM_LABEL[outcome.platform];
  const live = !!outcome.listingUrl;
  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 8,
        }}
      >
        <div style={{ width: 8, height: 8, borderRadius: 8, background: accent }} />
        <span style={{ fontSize: 14, fontWeight: 600, color: "#0e0f0e", letterSpacing: "-0.1px" }}>
          {label}
        </span>
        <span
          style={{
            marginLeft: "auto",
            fontSize: 13,
            color: "#3a3b3a",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {fmt(priceEur)}
        </span>
      </div>
      {live ? (
        <a
          href={outcome.listingUrl as string}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "11px 14px",
            borderRadius: 12,
            border: "1px solid #e7e5e0",
            background: "#fff",
            color: "#0e0f0e",
            textDecoration: "none",
            fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
            fontSize: 14,
            fontWeight: 500,
          }}
        >
          <span>Open {label} listing</span>
          <ExternalArrow />
        </a>
      ) : (
        <div
          style={{
            padding: "10px 12px",
            borderRadius: 12,
            background: "#fdf0ee",
            border: "1px solid #f5c6c0",
            color: "#c0392b",
            fontSize: 13,
            lineHeight: 1.45,
          }}
        >
          {outcome.error ?? "Publishing failed."}
        </div>
      )}
    </div>
  );
}

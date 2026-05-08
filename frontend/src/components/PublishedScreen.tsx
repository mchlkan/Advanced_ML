"use client";

import { useRef } from "react";
import type { Platform, PublishResponse, UploadResponse } from "@/types/api";

interface Props {
  platform: Platform;
  publishResponse: PublishResponse;
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

export default function PublishedScreen({
  platform,
  publishResponse,
  results,
  onReset,
}: Props) {
  const tabRef = useRef<Window | null>(null);

  const activePlatform = platform;
  const otherPlatform: Platform = platform === "vinted" ? "kleinanzeigen" : "vinted";

  const activeBlock = platform === "vinted" ? results.vinted : results.kleinanzeigen;
  const otherBlock = platform === "vinted" ? results.kleinanzeigen : results.vinted;

  function reopenTab() {
    if (tabRef.current && !tabRef.current.closed) {
      tabRef.current.focus();
    } else {
      tabRef.current = window.open(publishResponse.prefill_url, "_blank") ?? null;
    }
  }

  return (
    <div
      style={{
        minHeight: "100dvh",
        display: "flex",
        flexDirection: "column",
        backgroundColor: "var(--color-bg)",
        color: "var(--color-ink)",
        fontFamily: "var(--font-sans)",
      }}
    >
      {/* Header */}
      <header
        style={{
          padding: "20px 24px 16px",
          borderBottom: "1px solid var(--color-border)",
        }}
      >
        <button
          onClick={onReset}
          style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontSize: 15, fontWeight: 600, letterSpacing: "-0.3px", color: "var(--color-ink)", minHeight: 44 }}
        >
          Resell Copilot
        </button>
      </header>

      <main style={{ flex: 1, padding: "28px 24px 0" }}>
        {/* Success heading */}
        <h2
          style={{
            fontSize: 26,
            fontWeight: 590,
            letterSpacing: "-0.7px",
            margin: "0 0 8px",
          }}
        >
          Listing opened
        </h2>

        <p
          style={{
            fontSize: 15,
            color: "var(--color-ink-secondary)",
            margin: "0 0 6px",
            lineHeight: 1.45,
          }}
        >
          We pre-filled {PLATFORM_LABEL[activePlatform]} in a new tab.
        </p>

        <p
          style={{
            fontSize: 13,
            color: "var(--color-ink-tertiary)",
            margin: "0 0 32px",
            lineHeight: 1.5,
          }}
        >
          Switch over to review photos, confirm the price, and hit publish on{" "}
          {PLATFORM_LABEL[activePlatform]} itself. We don&apos;t post on your behalf.
        </p>

        {/* Summary table */}
        <div
          style={{
            backgroundColor: "var(--color-bg-card)",
            padding: "20px",
            marginBottom: 24,
          }}
        >
          {[
            ["Platform", PLATFORM_LABEL[activePlatform]],
            ["Suggested", fmt(activeBlock.price.q50)],
            [
              "Title",
              activeBlock.identification.title ?? "—",
            ],
            ["Listing ID", `#${shortId(results.listing_id)}`],
            ["Drafted in", `${(results.latency_ms / 1000).toFixed(1)}s`],
          ].map(([key, value]) => (
            <div
              key={key}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "flex-start",
                gap: 16,
                paddingBottom: 12,
                marginBottom: 12,
                borderBottom: "1px solid var(--color-border)",
              }}
            >
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  letterSpacing: "0.8px",
                  textTransform: "uppercase",
                  color: "var(--color-ink-tertiary)",
                  flexShrink: 0,
                  paddingTop: 1,
                }}
              >
                {key}
              </span>
              <span
                style={{
                  fontSize: 13,
                  color: "var(--color-ink)",
                  textAlign: "right",
                  lineHeight: 1.4,
                  wordBreak: "break-word",
                }}
              >
                {value}
              </span>
            </div>
          ))}
        </div>

        {/* Reopen button */}
        <button
          onClick={reopenTab}
          style={{
            display: "block",
            width: "100%",
            padding: "16px 0",
            backgroundColor: "var(--color-ink)",
            color: "var(--color-bg)",
            fontSize: 15,
            fontWeight: 600,
            letterSpacing: "-0.2px",
            border: "none",
            cursor: "pointer",
            minHeight: 52,
            marginBottom: 20,
          }}
        >
          Reopen {PLATFORM_LABEL[activePlatform]} tab
        </button>

        {/* Cross-post callout */}
        <div
          style={{
            padding: "16px",
            backgroundColor: "var(--color-bg-subtle)",
            borderLeft: "3px solid var(--color-border)",
            marginBottom: 32,
          }}
        >
          <p style={{ fontSize: 13, color: "var(--color-ink-secondary)", margin: 0, lineHeight: 1.5 }}>
            Want to cross-post? You can also publish to{" "}
            <strong style={{ color: "var(--color-ink)" }}>
              {PLATFORM_LABEL[otherPlatform]}
            </strong>{" "}
            at {fmt(otherBlock.price.q50)} —{" "}
            {otherPlatform === "kleinanzeigen" ? "faster local sale." : "better price."}
          </p>
        </div>
      </main>

      {/* Footer */}
      <footer
        style={{
          padding: "0 24px calc(24px + env(safe-area-inset-bottom))",
          textAlign: "center",
        }}
      >
        <button
          onClick={onReset}
          style={{
            background: "none",
            border: "none",
            fontSize: 14,
            color: "var(--color-ink-secondary)",
            cursor: "pointer",
            minHeight: 44,
          }}
        >
          Start a new listing →
        </button>
      </footer>
    </div>
  );
}

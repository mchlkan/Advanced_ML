"use client";

import { useState } from "react";
import type { Identification, Platform, UploadResponse } from "@/types/api";
import { verifyListing } from "@/api/verify";

interface Props {
  imageUrl: string;
  data: UploadResponse;
  onPublish: (platform: Platform, finalFields: Identification) => void;
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
  return id.slice(0, 6);
}

interface FieldChipProps {
  label: string;
  value: string | null;
  uncertain?: boolean;
}
function FieldChip({ label, value, uncertain }: FieldChipProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 52 }}>
      <span
        style={{
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: "1px",
          color: "var(--color-ink-tertiary)",
          textTransform: "uppercase",
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontSize: 13,
          fontWeight: 500,
          color: uncertain ? "var(--color-ink-tertiary)" : "var(--color-ink)",
          fontStyle: uncertain ? "italic" : "normal",
        }}
      >
        {value ?? "—"}{uncertain ? " ?" : ""}
      </span>
    </div>
  );
}

export default function ResultsScreen({ imageUrl, data: initialData, onPublish, onReset }: Props) {
  const [data, setData] = useState(initialData);
  const [editOpen, setEditOpen] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [selectedPlatform, setSelectedPlatform] = useState<Platform>("vinted");
  const [hints, setHints] = useState<Partial<Identification>>({});

  // Determine recommendation: Vinted has higher price, Kleinanzeigen has sell probability
  const vintedQ50 = data.vinted.price.q50;
  const kaQ50 = data.kleinanzeigen.price.q50;
  const priceDiff = Math.abs(vintedQ50 - kaQ50);
  const recommendationText =
    vintedQ50 >= kaQ50
      ? `Vinted gets ${fmt(priceDiff)} more; Kleinanzeigen may sell faster.`
      : `Kleinanzeigen sells faster; Vinted gets ${fmt(priceDiff)} more.`;

  const activeId =
    selectedPlatform === "vinted"
      ? data.vinted.identification
      : data.kleinanzeigen.identification;

  const [listingTitle, setListingTitle] = useState(activeId.title ?? "");
  const [listingDesc, setListingDesc] = useState(activeId.description ?? "");

  const wearDetected = data.visual_wear_probability > 0.4;

  async function handleVerify(e: React.FormEvent) {
    e.preventDefault();
    setVerifying(true);
    try {
      const updated = await verifyListing({
        listing_id: data.listing_id,
        hints,
      });
      setData(updated);
    } finally {
      setVerifying(false);
      setEditOpen(false);
    }
  }

  function handlePublish(platform: Platform) {
    const id = platform === "vinted" ? data.vinted.identification : data.kleinanzeigen.identification;
    onPublish(platform, {
      ...id,
      title: listingTitle || id.title,
      description: listingDesc || id.description,
    });
  }

  const otherPlatform: Platform = selectedPlatform === "vinted" ? "kleinanzeigen" : "vinted";

  return (
    <div
      style={{
        height: "100dvh",
        display: "flex",
        flexDirection: "column",
        backgroundColor: "var(--color-bg)",
        color: "var(--color-ink)",
        fontFamily: "var(--font-sans)",
        overflow: "hidden",
      }}
    >
      {/* Header — fixed at top, outside scroll area */}
      <header
        style={{
          padding: "20px 24px 16px",
          borderBottom: "1px solid var(--color-border)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexShrink: 0,
        }}
      >
        <button
          onClick={onReset}
          style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontSize: 15, fontWeight: 600, letterSpacing: "-0.3px", color: "var(--color-ink)", minHeight: 44 }}
        >
          Resell Copilot
        </button>
        <span
          style={{
            fontSize: 12,
            color: "var(--color-ink-tertiary)",
            fontFamily: "var(--font-mono)",
          }}
        >
          #{shortId(data.listing_id)} · {(data.latency_ms / 1000).toFixed(1)}s
        </span>
      </header>

      {/* Scrollable body — sits between header and publish bar */}
      <div style={{ flex: 1, overflowY: "auto", WebkitOverflowScrolling: "touch" } as React.CSSProperties}>

      {/* Photo preview */}
      <div
        style={{
          height: 220,
          overflow: "hidden",
          backgroundColor: "var(--color-bg-card)",
          flexShrink: 0,
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={imageUrl}
          alt="Your item"
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      </div>

      {/* Identification block */}
      <section style={{ padding: "24px 24px 0" }}>
        <p
          style={{
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: "1px",
            textTransform: "uppercase",
            color: "var(--color-ink-tertiary)",
            margin: "0 0 6px",
          }}
        >
          Identified
        </p>
        <p
          style={{
            fontSize: 11,
            color: "var(--color-ink-tertiary)",
            margin: "0 0 14px",
          }}
        >
          What we see
        </p>

        {/* Item headline */}
        <p
          style={{
            fontSize: 17,
            fontWeight: 590,
            letterSpacing: "-0.5px",
            margin: "0 0 16px",
            lineHeight: 1.3,
          }}
        >
          {data.vinted.identification.brand}{" "}
          {data.vinted.identification.color?.toLowerCase()}{" "}
          {data.vinted.identification.category?.toLowerCase()},{" "}
          {data.vinted.identification.condition?.toLowerCase()}
        </p>

        {/* Field chips */}
        <div
          style={{
            display: "flex",
            gap: 20,
            flexWrap: "wrap",
            marginBottom: wearDetected ? 14 : 20,
          }}
        >
          <FieldChip label="Brand" value={data.vinted.identification.brand} />
          <FieldChip label="Type" value={data.vinted.identification.category} />
          <FieldChip label="Cond" value={data.vinted.identification.condition} />
          <FieldChip label="Color" value={data.vinted.identification.color} />
          <FieldChip
            label="Size"
            value={data.vinted.identification.size}
            uncertain={!data.vinted.identification.size}
          />
        </div>

        {/* Wear warning */}
        {wearDetected && (
          <div
            style={{
              backgroundColor: "oklch(0.97 0.03 55)",
              borderLeft: "3px solid var(--color-accent-orange)",
              padding: "10px 14px",
              marginBottom: 20,
            }}
          >
            <p
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: "var(--color-accent-orange)",
                margin: "0 0 3px",
              }}
            >
              ! Visible wear detected.
            </p>
            <p style={{ fontSize: 12, color: "var(--color-ink-secondary)", margin: 0 }}>
              Light pilling detected. We adjusted condition accordingly.
            </p>
          </div>
        )}

        {/* Edit details toggle */}
        <button
          onClick={() => setEditOpen((o) => !o)}
          style={{
            background: "none",
            border: "none",
            padding: 0,
            fontSize: 13,
            color: "var(--color-accent)",
            cursor: "pointer",
            fontWeight: 500,
            minHeight: 44,
            display: "flex",
            alignItems: "center",
          }}
        >
          {editOpen ? "Hide details" : "Edit details"} ↓
        </button>

        {/* Edit form */}
        {editOpen && (
          <form onSubmit={handleVerify} style={{ marginTop: 12, marginBottom: 8 }}>
            {(
              [
                ["brand", "Brand"],
                ["category", "Type"],
                ["condition", "Condition"],
                ["color", "Color"],
                ["size", "Size"],
              ] as [keyof Identification, string][]
            ).map(([field, label]) => (
              <div key={field} style={{ marginBottom: 12 }}>
                <label
                  style={{
                    display: "block",
                    fontSize: 11,
                    fontWeight: 600,
                    letterSpacing: "0.8px",
                    textTransform: "uppercase",
                    color: "var(--color-ink-tertiary)",
                    marginBottom: 4,
                  }}
                >
                  {label}
                </label>
                <input
                  type="text"
                  defaultValue={(data.vinted.identification[field] as string) ?? ""}
                  onChange={(e) =>
                    setHints((h) => ({ ...h, [field]: e.target.value || null }))
                  }
                  style={{
                    display: "block",
                    width: "100%",
                    padding: "10px 12px",
                    fontSize: 14,
                    border: "1.5px solid var(--color-border)",
                    backgroundColor: "var(--color-bg)",
                    color: "var(--color-ink)",
                    outline: "none",
                    minHeight: 44,
                  }}
                />
              </div>
            ))}
            <button
              type="submit"
              disabled={verifying}
              style={{
                width: "100%",
                padding: "14px 0",
                backgroundColor: verifying ? "var(--color-ink-tertiary)" : "var(--color-ink)",
                color: "var(--color-bg)",
                fontSize: 14,
                fontWeight: 600,
                border: "none",
                cursor: verifying ? "not-allowed" : "pointer",
                minHeight: 48,
              }}
            >
              {verifying ? "Recalculating…" : "Update listing"}
            </button>
          </form>
        )}
      </section>

      {/* Divider */}
      <div style={{ height: 1, backgroundColor: "var(--color-border)", margin: "20px 0" }} />

      {/* Platform recommendation */}
      <section style={{ padding: "0 24px" }}>
        <p
          style={{
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: "1px",
            textTransform: "uppercase",
            color: "var(--color-ink-tertiary)",
            margin: "0 0 16px",
          }}
        >
          Where to list
        </p>

        {/* Vinted card */}
        <PlatformCard
          platform="vinted"
          selected={selectedPlatform === "vinted"}
          price={data.vinted.price}
          sellProbability={data.vinted.sell_probability}
          verifying={verifying}
          onClick={() => setSelectedPlatform("vinted")}
        />

        <div style={{ height: 10 }} />

        {/* Kleinanzeigen card */}
        <PlatformCard
          platform="kleinanzeigen"
          selected={selectedPlatform === "kleinanzeigen"}
          price={data.kleinanzeigen.price}
          qualitativeNote={data.kleinanzeigen.qualitative_note}
          verifying={verifying}
          onClick={() => setSelectedPlatform("kleinanzeigen")}
        />

        {/* Recommendation callout */}
        <p
          style={{
            fontSize: 13,
            color: "var(--color-ink-secondary)",
            margin: "14px 0 0",
            lineHeight: 1.45,
          }}
        >
          {recommendationText}
        </p>
      </section>

      {/* Divider */}
      <div style={{ height: 1, backgroundColor: "var(--color-border)", margin: "20px 0" }} />

      {/* Generated listing */}
      <section style={{ padding: "0 24px" }}>
        <p
          style={{
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: "1px",
            textTransform: "uppercase",
            color: "var(--color-ink-tertiary)",
            margin: "0 0 12px",
          }}
        >
          Generated listing · {PLATFORM_LABEL[selectedPlatform]}
        </p>

        <input
          type="text"
          value={listingTitle}
          onChange={(e) => setListingTitle(e.target.value)}
          placeholder="Title"
          style={{
            display: "block",
            width: "100%",
            padding: "10px 12px",
            fontSize: 14,
            fontWeight: 500,
            border: "1.5px solid var(--color-border)",
            backgroundColor: "var(--color-bg)",
            color: "var(--color-ink)",
            outline: "none",
            marginBottom: 10,
            minHeight: 44,
          }}
        />

        <textarea
          value={listingDesc}
          onChange={(e) => setListingDesc(e.target.value)}
          rows={6}
          style={{
            display: "block",
            width: "100%",
            padding: "10px 12px",
            fontSize: 13,
            lineHeight: 1.55,
            border: "1.5px solid var(--color-border)",
            backgroundColor: "var(--color-bg)",
            color: "var(--color-ink)",
            outline: "none",
          }}
        />
      </section>

      {/* Bottom padding so last content clears the safe area */}
      <div style={{ height: "env(safe-area-inset-bottom, 16px)" }} />

      </div>{/* end scrollable body */}

      {/* Publish bar — never overlaps content because it's outside the scroll container */}
      <div
        style={{
          flexShrink: 0,
          backgroundColor: "var(--color-bg)",
          borderTop: "1px solid var(--color-border)",
          padding: "14px 24px calc(14px + env(safe-area-inset-bottom))",
        }}
      >
        <button
          onClick={() => handlePublish(selectedPlatform)}
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
          }}
        >
          Publish on {PLATFORM_LABEL[selectedPlatform]}
        </button>
      </div>
    </div>
  );
}

// ---- PlatformCard sub-component ----

interface PlatformCardProps {
  platform: Platform;
  selected: boolean;
  price: { q10: number; q50: number; q90: number };
  sellProbability?: number;
  qualitativeNote?: string;
  verifying: boolean;
  onClick: () => void;
}

const PLATFORM_COLOR: Record<Platform, string> = {
  vinted: "oklch(0.55 0.1 165)",      // teal-green
  kleinanzeigen: "var(--color-accent-orange)",
};

function PlatformCard({
  platform,
  selected,
  price,
  sellProbability,
  qualitativeNote,
  verifying,
  onClick,
}: PlatformCardProps) {
  const accentColor = PLATFORM_COLOR[platform];

  return (
    <button
      onClick={onClick}
      style={{
        display: "block",
        width: "100%",
        textAlign: "left",
        padding: "16px",
        backgroundColor: selected ? "var(--color-bg-card)" : "var(--color-bg-subtle)",
        border: "none",
        borderLeft: `4px solid ${selected ? accentColor : "var(--color-border)"}`,
        cursor: "pointer",
      }}
    >
      {/* Platform name + price */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 8,
        }}
      >
        <span
          style={{
            fontSize: 14,
            fontWeight: 600,
            letterSpacing: "-0.2px",
            color: selected ? "var(--color-ink)" : "var(--color-ink-secondary)",
          }}
        >
          {platform === "vinted" ? "Vinted" : "Kleinanzeigen"}
        </span>

        {verifying ? (
          <span style={{ fontSize: 13, color: "var(--color-ink-tertiary)" }}>…</span>
        ) : (
          <div style={{ textAlign: "right" }}>
            <span
              style={{
                fontSize: 20,
                fontWeight: 590,
                letterSpacing: "-0.6px",
                color: "var(--color-ink)",
              }}
            >
              {fmt(price.q50)}
            </span>
            <span
              style={{
                display: "block",
                fontSize: 11,
                color: "var(--color-ink-tertiary)",
              }}
            >
              {fmt(price.q10)}–{fmt(price.q90)}
            </span>
          </div>
        )}
      </div>

      {/* Sell probability (Vinted only) */}
      {sellProbability !== undefined && !verifying && (
        <div>
          <div
            style={{
              height: 3,
              backgroundColor: "var(--color-border)",
              marginBottom: 5,
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${Math.round(sellProbability * 100)}%`,
                backgroundColor: accentColor,
                transition: "width 0.4s ease",
              }}
            />
          </div>
          <span style={{ fontSize: 11, color: "var(--color-ink-tertiary)" }}>
            ~{Math.round(sellProbability * 100)}% chance to sell within 30 days
          </span>
        </div>
      )}

      {/* Qualitative note (Kleinanzeigen) */}
      {qualitativeNote && (
        <p
          style={{
            fontSize: 11,
            color: "var(--color-ink-tertiary)",
            fontStyle: "italic",
            margin: 0,
          }}
        >
          {qualitativeNote}
        </p>
      )}
    </button>
  );
}

"use client";

import { useState } from "react";
import type {
  Identification,
  OnboardingStatus,
  Platform,
  UploadResponse,
} from "@/types/api";
import { verifyListing } from "@/api/verify";
import { patchListingFields } from "@/api/inventory";
import SmallCaps from "./ui/SmallCaps";

type DetailKey = "brand" | "category" | "condition" | "color" | "size";
const DETAIL_FIELDS: { key: DetailKey; label: string }[] = [
  { key: "brand", label: "Brand" },
  { key: "category", label: "Type" },
  { key: "condition", label: "Condition" },
  { key: "color", label: "Color" },
  { key: "size", label: "Size" },
];
const CONDITION_OPTIONS = ["New with tags", "New", "Very good", "Good"];

const SANS = '"Inter", -apple-system, system-ui, sans-serif';
const MONO = '"JetBrains Mono", ui-monospace, monospace';

interface Props {
  imageUrl: string;
  labelImageUrl?: string;
  data: UploadResponse;
  connectionStatus: OnboardingStatus | null;
  onPublish: (platform: Platform, finalFields: Identification) => void;
  onReset: () => void;
  onConnectPlatform: (platform: Platform) => void;
  error?: string | null;
}

function isPlatformReady(
  status: OnboardingStatus | null,
  platform: Platform,
): boolean {
  // Treat unknown status as ready so we don't block users when the status
  // endpoint is briefly unreachable. The publish backend will return its
  // own error if a session is genuinely missing.
  if (status === null) return true;
  return status[platform].state === "ready";
}

const PLATFORM_LABEL: Record<Platform, string> = {
  vinted: "Vinted",
  kleinanzeigen: "Kleinanzeigen",
};

const PLATFORM_ACCENT: Record<Platform, string> = {
  vinted: "oklch(0.55 0.08 195)",
  kleinanzeigen: "oklch(0.62 0.13 55)",
};

const PLATFORM_SOFT: Record<Platform, string> = {
  vinted: "oklch(0.97 0.02 195)",
  kleinanzeigen: "oklch(0.97 0.03 70)",
};

const PLATFORM_KICKER: Record<Platform, string> = {
  vinted: "EU · fashion",
  kleinanzeigen: "DE · local",
};

const OPTIMISTIC_CONDITIONS = new Set(["New with tags", "Like new"]);

function fmt(n: number) {
  return `€${Math.round(n)}`;
}

function shortId(id: string) {
  return id.slice(0, 6);
}

function SectionLabel({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        justifyContent: "space-between",
        padding: "0 20px",
        marginBottom: 10,
      }}
    >
      <SmallCaps>{children}</SmallCaps>
      {action && (
        <div style={{ fontSize: 13, color: "#3a3b3a", fontWeight: 500 }}>{action}</div>
      )}
    </div>
  );
}

function ProbBar({ value, color }: { value: number; color: string }) {
  return (
    <div
      style={{
        height: 5,
        background: "#efece6",
        borderRadius: 999,
        overflow: "hidden",
        width: "100%",
      }}
    >
      <div
        style={{
          width: `${Math.round(value * 100)}%`,
          height: "100%",
          background: color,
          borderRadius: 999,
          transition: "width 0.4s ease",
        }}
      />
    </div>
  );
}

interface PlatformCardProps {
  platform: Platform;
  recommended: boolean;
  selected: boolean;
  price: { q10: number; q50: number; q90: number };
  sellProbability?: number;
  qualitativeNote?: string;
  verifying: boolean;
  disconnected?: boolean;
  onClick: () => void;
}

function PlatformCard({
  platform,
  recommended,
  selected,
  price,
  sellProbability,
  qualitativeNote,
  verifying,
  disconnected,
  onClick,
}: PlatformCardProps) {
  const accent = PLATFORM_ACCENT[platform];
  const soft = PLATFORM_SOFT[platform];
  const kicker = PLATFORM_KICKER[platform];

  return (
    <button
      onClick={onClick}
      style={{
        display: "block",
        width: "100%",
        textAlign: "left",
        position: "relative",
        borderRadius: 16,
        background: selected ? soft : "#fff",
        border: `1px solid ${selected ? accent + "55" : "#e7e5e0"}`,
        padding: "16px 16px 18px",
        boxShadow: selected
          ? `0 1px 0 #fff inset, 0 6px 20px ${accent}1f`
          : "0 1px 0 #fff inset",
        cursor: "pointer",
        marginTop: recommended ? 12 : 0,
        opacity: disconnected ? 0.6 : 1,
      }}
    >
      {recommended && (
        <div
          style={{
            position: "absolute",
            top: -10,
            left: 16,
            background: "#0e0f0e",
            color: "#fff",
            fontSize: 10,
            fontWeight: 600,
            letterSpacing: "0.12em",
            textTransform: "uppercase" as const,
            padding: "4px 8px",
            borderRadius: 6,
          }}
        >
          Recommended
        </div>
      )}

      {/* Wordmark row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 14,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <div style={{ width: 8, height: 8, borderRadius: 8, background: accent }} />
          <span style={{ fontSize: 14, fontWeight: 600, color: "#0e0f0e", letterSpacing: "-0.1px" }}>
            {PLATFORM_LABEL[platform]}
          </span>
          {disconnected && (
            <span
              style={{
                fontSize: 9.5,
                fontWeight: 600,
                color: "oklch(0.45 0.08 75)",
                backgroundColor: "oklch(0.95 0.06 80)",
                padding: "2px 6px",
                borderRadius: 999,
                textTransform: "uppercase" as const,
                letterSpacing: "0.12em",
              }}
            >
              Disconnected
            </span>
          )}
        </div>
        <SmallCaps size={10}>{kicker}</SmallCaps>
      </div>

      {/* Price */}
      {verifying ? (
        <div style={{ fontSize: 13, color: "#9b9c99", height: 42 }}>…</div>
      ) : (
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <div
            style={{
              fontSize: 38,
              fontWeight: 600,
              letterSpacing: "-1.2px",
              color: "#0e0f0e",
              fontVariantNumeric: "tabular-nums",
              lineHeight: 1,
            }}
          >
            {fmt(price.q50)}
          </div>
          <div
            style={{
              fontSize: 12,
              color: "#6b6c6a",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {fmt(price.q10)}–{fmt(price.q90)}
          </div>
        </div>
      )}

      {/* Sell prob */}
      {sellProbability !== undefined && !verifying && (
        <div style={{ marginTop: 14 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: 12,
              color: "#3a3b3a",
              marginBottom: 6,
              fontWeight: 500,
            }}
          >
            <span>Chance to sell</span>
            <span
              style={{
                fontVariantNumeric: "tabular-nums",
                color: "#0e0f0e",
                fontWeight: 600,
              }}
            >
              {Math.round(sellProbability * 100)}% · 30 days
            </span>
          </div>
          <ProbBar value={sellProbability} color={accent} />
        </div>
      )}

      {/* Qualitative note */}
      {qualitativeNote && !verifying && (
        <div
          style={{
            marginTop: 14,
            fontSize: 13,
            color: "#3a3b3a",
            lineHeight: 1.4,
            padding: "10px 12px",
            borderRadius: 10,
            background: "#fff",
            border: "1px solid #efece6",
          }}
        >
          <SmallCaps size={10} style={{ marginRight: 6 }}>
            Note
          </SmallCaps>
          {qualitativeNote}
        </div>
      )}
    </button>
  );
}

export default function ResultsScreen({
  imageUrl,
  labelImageUrl,
  data: initialData,
  connectionStatus,
  onPublish,
  onReset,
  onConnectPlatform,
  error,
}: Props) {
  const vintedReady = isPlatformReady(connectionStatus, "vinted");
  const kaReady = isPlatformReady(connectionStatus, "kleinanzeigen");
  const isReady = (p: Platform) => (p === "vinted" ? vintedReady : kaReady);
  const [data, setData] = useState(initialData);
  const [verifying, setVerifying] = useState(false);
  const [selectedPlatform, setSelectedPlatform] = useState<Platform>("vinted");
  // Canonical "details" overrides (brand/category/condition/color/size).
  const [fieldEdits, setFieldEdits] = useState<Partial<Identification>>({});
  // Per-platform overrides for the listing copy + price.
  const [titleEdits, setTitleEdits] = useState<Partial<Record<Platform, string>>>({});
  const [descEdits, setDescEdits] = useState<Partial<Record<Platform, string>>>({});
  const [priceEdits, setPriceEdits] = useState<Partial<Record<Platform, string>>>({});

  const vintedQ50 = data.vinted.price.q50;
  const kaQ50 = data.kleinanzeigen.price.q50;
  const recommendedPlatform: Platform = vintedQ50 >= kaQ50 ? "vinted" : "kleinanzeigen";

  const activeId =
    selectedPlatform === "vinted" ? data.vinted.identification : data.kleinanzeigen.identification;
  const activeBand = selectedPlatform === "vinted" ? data.vinted.price : data.kleinanzeigen.price;

  const detailVal = (f: DetailKey): string =>
    (fieldEdits[f] as string | undefined) ?? (data.vinted.identification[f] as string | null) ?? "";

  const listingTitle = titleEdits[selectedPlatform] ?? activeId.title ?? "";
  const listingDesc = descEdits[selectedPlatform] ?? activeId.description ?? "";
  const defaultPrice = Math.round((activeId.price_eur as number | null) ?? activeBand.q50);
  const listingPrice = priceEdits[selectedPlatform] ?? String(defaultPrice);

  const wearDetected = data.visual_wear_probability > 0.4;
  const conditionVal = detailVal("condition");
  const wearConflict =
    data.visual_wear_probability > 0.5 && !!conditionVal && OPTIMISTIC_CONDITIONS.has(conditionVal);
  const reviewSet = new Set(data.vinted.field_review?.needs_review ?? []);
  const itemHeadline = [
    detailVal("brand"),
    detailVal("color").toLowerCase(),
    detailVal("category").toLowerCase(),
    conditionVal ? `— ${conditionVal.toLowerCase()}` : null,
  ]
    .filter(Boolean)
    .join(" ");

  // Persist a correction on the listing (new predictions row, source='edit';
  // also pushes to any posted platform — a fresh scan isn't posted, so no-op).
  function persistFields(patch: Partial<Identification>) {
    patchListingFields(data.listing_id, patch).catch(() => {});
  }

  function setDetail(f: DetailKey, value: string) {
    setFieldEdits((e) => ({ ...e, [f]: value || null }));
  }

  function priceFor(platform: Platform): number {
    const raw = priceEdits[platform];
    const p = raw ? parseInt(raw, 10) : NaN;
    if (Number.isFinite(p) && p > 0) return p;
    const id = platform === "vinted" ? data.vinted.identification : data.kleinanzeigen.identification;
    const band = platform === "vinted" ? data.vinted.price : data.kleinanzeigen.price;
    return Math.round((id.price_eur as number | null) ?? band.q50);
  }

  async function handleReanalyze() {
    setVerifying(true);
    try {
      const updated = await verifyListing({
        listing_id: data.listing_id,
        hints: {
          brand: detailVal("brand") || null,
          category: detailVal("category") || null,
          condition: detailVal("condition") || null,
          color: detailVal("color") || null,
          size: detailVal("size") || null,
        },
      });
      setData(updated);
      setFieldEdits({});
      setTitleEdits({});
      setDescEdits({});
      setPriceEdits({});
    } finally {
      setVerifying(false);
    }
  }

  function handlePublish(platform: Platform) {
    const id =
      platform === "vinted" ? data.vinted.identification : data.kleinanzeigen.identification;
    onPublish(platform, {
      ...id,
      ...fieldEdits,
      title: titleEdits[platform] ?? id.title,
      description: descEdits[platform] ?? id.description,
      price_eur: priceFor(platform),
    });
  }

  const otherPlatform: Platform =
    selectedPlatform === "vinted" ? "kleinanzeigen" : "vinted";

  const ACCENT = "oklch(0.62 0.15 145)";

  return (
    <div
      style={{
        height: "100dvh",
        display: "flex",
        flexDirection: "column",
        backgroundColor: "#fafaf8",
        color: "#0e0f0e",
        fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
        overflow: "hidden",
      }}
    >
      {/* Scrollable body */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          WebkitOverflowScrolling: "touch",
          paddingBottom: 120,
        } as React.CSSProperties}
      >
        {error && (
          <div style={{ padding: "12px 20px 0" }}>
            <p style={{
              fontSize: 13,
              color: "#c0392b",
              margin: 0,
              padding: "10px 12px",
              backgroundColor: "#fdf0ee",
              borderRadius: 10,
              border: "1px solid #f5c6c0",
            }}>
              {error}
            </p>
          </div>
        )}
        {/* Top bar */}
        <div
          style={{
            padding: "12px 20px 16px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <button
            onClick={onReset}
            style={{
              width: 36,
              height: 36,
              borderRadius: 18,
              border: "1px solid #e7e5e0",
              background: "#fff",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: 0,
              cursor: "pointer",
            }}
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path
                d="M9 2L4 7l5 5"
                stroke="#0e0f0e"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          <div
            style={{
              fontFamily: '"JetBrains Mono", ui-monospace, monospace',
              fontSize: 10.5,
              color: "#9b9c99",
              textTransform: "uppercase",
              letterSpacing: "1.2px",
            }}
          >
            #{shortId(data.listing_id)} · {(data.latency_ms / 1000).toFixed(1)}s
          </div>
          <div style={{ width: 36 }} />
        </div>

        {/* Photo */}
        <div style={{ padding: "0 20px" }}>
          <div
            style={{
              borderRadius: 18,
              overflow: "hidden",
              border: "1px solid #e7e5e0",
              position: "relative",
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={imageUrl}
              alt="Your item"
              style={{ width: "100%", height: 260, objectFit: "cover", display: "block" }}
            />
            <div
              style={{
                position: "absolute",
                top: 12,
                left: 12,
                padding: "5px 9px",
                borderRadius: 8,
                background: "rgba(14,15,14,0.78)",
                color: "#fff",
                fontSize: 10.5,
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.12em",
                display: "flex",
                alignItems: "center",
                gap: 6,
                backdropFilter: "blur(8px)",
              }}
            >
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                <path
                  d="M2 5l2 2 4-4"
                  stroke="#fff"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              Identified
            </div>
            {labelImageUrl && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={labelImageUrl}
                alt="Brand or size tag"
                onError={(e) => {
                  // Listing opened from inventory with no tag photo → /label 404s; drop the thumbnail.
                  e.currentTarget.style.display = "none";
                }}
                style={{
                  position: "absolute",
                  right: 12,
                  bottom: 12,
                  width: 64,
                  height: 64,
                  objectFit: "cover",
                  borderRadius: 10,
                  border: "2px solid #fff",
                  boxShadow: "0 2px 8px rgba(0,0,0,0.25)",
                }}
              />
            )}
          </div>
        </div>

        {/* Title block */}
        <div style={{ padding: "24px 20px 16px" }}>
          <SmallCaps size={10.5} style={{ display: "block", marginBottom: 8 }}>
            What we see
          </SmallCaps>
          <h2
            style={{
              margin: 0,
              fontSize: 22,
              fontWeight: 600,
              letterSpacing: "-0.6px",
              lineHeight: 1.2,
              textWrap: "balance",
            } as React.CSSProperties}
          >
            {itemHeadline || "Your item"}
          </h2>
        </div>

        {/* Wear badge */}
        {wearDetected && (
          <div style={{ padding: "12px 20px 0" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "10px 12px",
                borderRadius: 12,
                background: "oklch(0.96 0.04 80)",
                border: "1px solid oklch(0.72 0.12 75 / 0.2)",
                fontSize: 13,
                color: "#3a3b3a",
                lineHeight: 1.4,
              }}
            >
              <div
                style={{
                  width: 18,
                  height: 18,
                  borderRadius: 9,
                  flexShrink: 0,
                  background: "oklch(0.72 0.12 75)",
                  color: "#fff",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 11,
                  fontWeight: 700,
                }}
              >
                !
              </div>
              <div>
                {wearConflict ? (
                  <>
                    <span style={{ fontWeight: 600, color: "#0e0f0e" }}>Condition mismatch.</span>{" "}
                    Read as &ldquo;{conditionVal}&rdquo;, but our flaw detector sees possible
                    wear — re-check the condition below.
                  </>
                ) : (
                  <>
                    <span style={{ fontWeight: 600, color: "#0e0f0e" }}>Visible wear detected.</span>{" "}
                    Light wear detected — condition set accordingly. Adjust below if needed.
                  </>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Editable details */}
        <div style={{ padding: "16px 20px 0" }}>
          <SmallCaps size={10.5} style={{ display: "block", marginBottom: 8 }}>
            Details
          </SmallCaps>
          <div style={{ background: "#fff", borderRadius: 14, border: "1px solid #e7e5e0", overflow: "hidden" }}>
            {DETAIL_FIELDS.map(({ key, label }, i) => {
              const needsReview = reviewSet.has(key);
              const value = detailVal(key);
              return (
                <div key={key}>
                  {i > 0 && <div style={{ height: 1, background: "#efece6" }} />}
                  <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 14px" }}>
                    <span style={{
                      width: 76, flexShrink: 0,
                      fontSize: 10.5, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase",
                      color: needsReview ? "oklch(0.5 0.1 75)" : "#9b9c99",
                    }}>
                      {label}{needsReview ? " · ?" : ""}
                    </span>
                    {key === "condition" ? (
                      <select
                        value={value}
                        onChange={(e) => {
                          setDetail("condition", e.target.value);
                          persistFields({ condition: e.target.value || null });
                        }}
                        style={{
                          flex: 1, minWidth: 0, border: "none", outline: "none", background: "transparent",
                          fontSize: 14, fontWeight: 500, color: value ? "#0e0f0e" : "#9b9c99",
                          fontFamily: SANS, cursor: "pointer",
                        }}
                      >
                        {!value && <option value="">—</option>}
                        {value && !CONDITION_OPTIONS.includes(value) && (
                          <option value={value}>{value}</option>
                        )}
                        {CONDITION_OPTIONS.map((c) => (
                          <option key={c} value={c}>{c}</option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type="text"
                        value={value}
                        placeholder="—"
                        onChange={(e) => setDetail(key, e.target.value)}
                        onBlur={(e) =>
                          persistFields({ [key]: e.target.value.trim() || null } as Partial<Identification>)
                        }
                        style={{
                          flex: 1, minWidth: 0, border: "none", outline: "none", background: "transparent",
                          fontSize: 14, fontWeight: 500, color: "#0e0f0e", fontFamily: SANS,
                        }}
                      />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Platform section */}
        <div style={{ padding: "28px 0 0" }}>
          <SectionLabel>Where to sell it</SectionLabel>
          <div style={{ padding: "0 20px", display: "flex", flexDirection: "column", gap: 16 }}>
            <PlatformCard
              platform="vinted"
              recommended={recommendedPlatform === "vinted"}
              selected={selectedPlatform === "vinted"}
              price={data.vinted.price}
              sellProbability={data.vinted.sell_probability}
              verifying={verifying}
              disconnected={!vintedReady}
              onClick={() => setSelectedPlatform("vinted")}
            />
            <PlatformCard
              platform="kleinanzeigen"
              recommended={recommendedPlatform === "kleinanzeigen"}
              selected={selectedPlatform === "kleinanzeigen"}
              price={data.kleinanzeigen.price}
              qualitativeNote={data.kleinanzeigen.qualitative_note}
              verifying={verifying}
              disconnected={!kaReady}
              onClick={() => setSelectedPlatform("kleinanzeigen")}
            />
          </div>
        </div>

        {/* Listing copy */}
        <div style={{ padding: "28px 0 0" }}>
          <SectionLabel
            action={
              <span
                onClick={verifying ? undefined : handleReanalyze}
                style={{ color: ACCENT, cursor: verifying ? "default" : "pointer", opacity: verifying ? 0.5 : 1 }}
              >
                {verifying ? "Re-analyzing…" : "Re-analyze"}
              </span>
            }
          >
            Your draft listing
          </SectionLabel>
          <div style={{ padding: "0 20px" }}>
            <div
              style={{
                borderRadius: 14,
                border: "1px solid #e7e5e0",
                background: "#fff",
                overflow: "hidden",
              }}
            >
              {/* Title */}
              <div style={{ padding: "14px 14px 8px" }}>
                <SmallCaps size={10} style={{ display: "block", marginBottom: 6 }}>
                  Title
                </SmallCaps>
                <input
                  type="text"
                  value={listingTitle}
                  onChange={(e) =>
                    setTitleEdits((t) => ({ ...t, [selectedPlatform]: e.target.value }))
                  }
                  onBlur={(e) => persistFields({ title: e.target.value.trim() || null })}
                  placeholder="Title"
                  style={{
                    display: "block",
                    width: "100%",
                    fontSize: 15,
                    fontWeight: 600,
                    color: "#0e0f0e",
                    lineHeight: 1.3,
                    border: "none",
                    outline: "none",
                    background: "transparent",
                    padding: 0,
                    fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
                  }}
                />
              </div>
              <div style={{ height: 1, background: "#efece6" }} />
              {/* Price */}
              <div style={{
                padding: "12px 14px", display: "flex", alignItems: "flex-end",
                justifyContent: "space-between", gap: 12,
              }}>
                <div>
                  <SmallCaps size={10} style={{ display: "block", marginBottom: 6 }}>
                    Price
                  </SmallCaps>
                  <span style={{
                    display: "inline-flex", alignItems: "baseline", gap: 1,
                    fontSize: 16, fontWeight: 600, color: "#0e0f0e", fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
                  }}>
                    <span>€</span>
                    <input
                      type="text"
                      inputMode="decimal"
                      value={listingPrice}
                      onChange={(e) =>
                        setPriceEdits((p) => ({ ...p, [selectedPlatform]: e.target.value.replace(/[^\d]/g, "") }))
                      }
                      onBlur={(e) => {
                        const n = parseInt(e.target.value, 10);
                        if (Number.isFinite(n) && n > 0) persistFields({ price_eur: n });
                      }}
                      style={{
                        width: "4.5ch", border: "none", outline: "none", background: "transparent",
                        fontSize: 16, fontWeight: 600, color: "#0e0f0e",
                        fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
                      }}
                    />
                  </span>
                </div>
                <span style={{ fontSize: 11.5, color: "#9b9c99", fontFamily: MONO, paddingBottom: 2 }}>
                  rec. {fmt(activeBand.q50)}
                </span>
              </div>
              <div style={{ height: 1, background: "#efece6" }} />
              {/* Description */}
              <div style={{ padding: "12px 14px 14px" }}>
                <SmallCaps size={10} style={{ display: "block", marginBottom: 6 }}>
                  Description
                </SmallCaps>
                <textarea
                  value={listingDesc}
                  onChange={(e) =>
                    setDescEdits((d) => ({ ...d, [selectedPlatform]: e.target.value }))
                  }
                  onBlur={(e) => persistFields({ description: e.target.value.trim() || null })}
                  rows={5}
                  style={{
                    display: "block",
                    width: "100%",
                    fontSize: 13.5,
                    lineHeight: 1.5,
                    color: "#3a3b3a",
                    border: "none",
                    outline: "none",
                    background: "transparent",
                    padding: 0,
                    resize: "none",
                    fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
                  }}
                />
              </div>
            </div>
          </div>
        </div>

        <div style={{ height: 32 }} />
      </div>

      {/* Sticky bottom CTA */}
      <div
        style={{
          position: "relative",
          flexShrink: 0,
          padding: "14px 20px calc(20px + env(safe-area-inset-bottom))",
          background:
            "linear-gradient(180deg, rgba(250,250,248,0) 0%, rgba(250,250,248,1) 25%)",
          marginTop: -20,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        <button
          onClick={() =>
            isReady(selectedPlatform)
              ? handlePublish(selectedPlatform)
              : onConnectPlatform(selectedPlatform)
          }
          style={{
            width: "100%",
            height: 54,
            borderRadius: 14,
            border: "none",
            cursor: "pointer",
            backgroundColor: ACCENT,
            color: "#fff",
            fontSize: 16,
            fontWeight: 600,
            letterSpacing: "-0.1px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0 20px",
            boxShadow:
              "0 1px 0 rgba(255,255,255,0.4) inset, 0 4px 12px oklch(0.62 0.15 145 / 0.3)",
            fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
          }}
        >
          <span>
            {isReady(selectedPlatform)
              ? `Publish on ${PLATFORM_LABEL[selectedPlatform]}`
              : `Reconnect ${PLATFORM_LABEL[selectedPlatform]} to publish`}
          </span>
          {isReady(selectedPlatform) && (
            <span
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                fontVariantNumeric: "tabular-nums",
                fontWeight: 500,
                opacity: 0.92,
              }}
            >
              {fmt(priceFor(selectedPlatform))}
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path
                  d="M3 7h8m0 0L7 3m4 4l-4 4"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
          )}
        </button>
        <button
          onClick={() =>
            isReady(otherPlatform)
              ? handlePublish(otherPlatform)
              : onConnectPlatform(otherPlatform)
          }
          style={{
            width: "100%",
            height: 38,
            borderRadius: 10,
            border: "none",
            background: "transparent",
            cursor: "pointer",
            fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
            fontSize: 13.5,
            fontWeight: 500,
            color: "#6b6c6a",
          }}
        >
          {isReady(otherPlatform)
            ? `Or publish on ${PLATFORM_LABEL[otherPlatform]} · ${fmt(priceFor(otherPlatform))}`
            : `Or reconnect ${PLATFORM_LABEL[otherPlatform]}`}
        </button>
      </div>
    </div>
  );
}

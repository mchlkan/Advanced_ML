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
import { PLATFORM_ACCENT, PLATFORM_KICKER, PLATFORM_LABEL, PLATFORM_SOFT } from "@/lib/platforms";
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
// Canonical garment vocab the publish mapper understands (= VINTED_CATEGORY_TO_CATALOG_ID keys).
const CATEGORY_OPTIONS = ["tshirts", "jackets", "jeans", "sneakers"];
const CLOTHING_SIZES = ["XS", "S", "M", "L", "XL", "XXL"];
const SHOE_SIZES = ["36", "37", "38", "39", "40", "41", "42", "43", "44", "45", "46"];
const ONE_SIZE = ["One size"];

function sizeOptionsFor(category: string): string[] {
  if (/shoe|schuh|sneaker/i.test(category)) return [...SHOE_SIZES, ...ONE_SIZE];
  if (category) return [...CLOTHING_SIZES, ...ONE_SIZE];
  return [...CLOTHING_SIZES, ...SHOE_SIZES, ...ONE_SIZE];
}

function ordinal(n: number): string {
  const v = n % 100;
  if (v >= 11 && v <= 13) return `${n}th`;
  return `${n}${["th", "st", "nd", "rd"][n % 10] ?? "th"}`;
}

// Rough percentile of price `p` within the q10/q50/q90 band, by piecewise-linear
// interpolation (the "~" signals it's an estimate off three quantiles).
function percentLabel(p: number, b: { q10: number; q50: number; q90: number }): string {
  if (p < b.q10) return "below the recommended range";
  if (p > b.q90) return "above the recommended range";
  let pct: number;
  if (p < b.q50) pct = b.q50 > b.q10 ? 10 + (40 * (p - b.q10)) / (b.q50 - b.q10) : 50;
  else pct = b.q90 > b.q50 ? 50 + (40 * (p - b.q50)) / (b.q90 - b.q50) : 50;
  const n = Math.round(pct);
  const tone = n < 30 ? "below market" : n > 75 ? "premium" : "fair";
  return `~${ordinal(n)} pct · ${tone}`;
}

const SANS = '"Inter", -apple-system, system-ui, sans-serif';
const MONO = '"JetBrains Mono", ui-monospace, monospace';

function DetailSelect({
  value,
  options,
  onPick,
}: {
  value: string;
  options: string[];
  onPick: (v: string) => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onPick(e.target.value)}
      style={{
        flex: 1,
        minWidth: 0,
        border: "none",
        outline: "none",
        background: "transparent",
        fontSize: 14,
        fontWeight: 500,
        color: value ? "#0e0f0e" : "#9b9c99",
        fontFamily: SANS,
        cursor: "pointer",
      }}
    >
      {!value && <option value="">—</option>}
      {value && !options.includes(value) && <option value={value}>{value}</option>}
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}

interface Props {
  imageUrl: string;
  labelImageUrl?: string;
  data: UploadResponse;
  connectionStatus: OnboardingStatus | null;
  onPublishMany: (items: Array<{ platform: Platform; finalFields: Identification }>) => void;
  onReset: () => void;
  onConnectPlatform: (platform: Platform) => void;
  error?: string | null;
  /** True for fresh VLM scans (upload, verify/re-analyze). False when re-opened
   *  from inventory, where `identification.price_eur` may be a persisted user
   *  edit that must be respected — see `modelPrice()` for how this is used. */
  isFreshUpload: boolean;
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

const OPTIMISTIC_CONDITIONS = new Set(["New with tags", "New"]);

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
  currentPrice: number;
  /** The model's own price for this platform — used to fix the slider bounds.
   *  Stable for the session; must NOT depend on the live `currentPrice`. */
  originalPrice: number;
  onPrice: (n: number) => void;
  onPriceCommit: (n: number) => void;
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
  currentPrice,
  originalPrice,
  onPrice,
  onPriceCommit,
  onClick,
}: PlatformCardProps) {
  const accent = PLATFORM_ACCENT[platform];
  const soft = PLATFORM_SOFT[platform];
  const kicker = PLATFORM_KICKER[platform];

  // Price slider on a piecewise scale: q10 → 10 %, q50 (the recommendation) →
  // 50 %, q90 → 90 % of the track, regardless of how right-skewed the band is,
  // with small tail zones below q10 / above q90 to undercut or go premium. Nice
  // side effect: the thumb position-% ≈ the percentile, so the slider *is* a
  // percentile picker. (A plain linear €-scale buried q50 on the far left.)
  const q10 = Math.round(price.q10);
  const q50 = Math.round(price.q50);
  const q90 = Math.round(price.q90);
  // Bounds are fixed (band + the model's price) — NOT derived from
  // `currentPrice`, or the endpoints would recede as you drag toward them.
  const sliderLo = Math.max(1, Math.min(Math.round(q10 * 0.6), originalPrice));
  const sliderHi = Math.max(Math.round(q90 * 1.5), originalPrice);
  const STEPS = 1000;
  const lerp = (x: number, a: number, b: number) =>
    b > a ? Math.min(1, Math.max(0, (x - a) / (b - a))) : 0;
  const priceToPos = (eur: number): number => {
    const e = Math.max(sliderLo, Math.min(sliderHi, eur));
    let f: number;
    if (e <= q10) f = 0.1 * lerp(e, sliderLo, q10);
    else if (e <= q50) f = 0.1 + 0.4 * lerp(e, q10, q50);
    else if (e <= q90) f = 0.5 + 0.4 * lerp(e, q50, q90);
    else f = 0.9 + 0.1 * lerp(e, q90, sliderHi);
    return Math.round(f * STEPS);
  };
  const posToPrice = (pos: number): number => {
    const f = Math.max(0, Math.min(1, pos / STEPS));
    let e: number;
    if (f <= 0.1) e = sliderLo + (f / 0.1) * (q10 - sliderLo);
    else if (f <= 0.5) e = q10 + ((f - 0.1) / 0.4) * (q50 - q10);
    else if (f <= 0.9) e = q50 + ((f - 0.5) / 0.4) * (q90 - q50);
    else e = q90 + ((f - 0.9) / 0.1) * (sliderHi - q90);
    return Math.max(1, Math.round(e));
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
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

      {/* Price + slider */}
      {verifying ? (
        <div style={{ fontSize: 13, color: "#9b9c99", height: 42 }}>…</div>
      ) : (
        <>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
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
              {fmt(currentPrice)}
            </div>
            <div style={{ fontSize: 12, color: "#6b6c6a" }}>
              rec. <span style={{ fontVariantNumeric: "tabular-nums" }}>{fmt(price.q50)}</span>
              {" · "}
              {percentLabel(currentPrice, price)}
            </div>
          </div>
          <div style={{ marginTop: 12 }}>
            <input
              type="range"
              min={0}
              max={STEPS}
              step={1}
              value={priceToPos(currentPrice)}
              onChange={(e) => onPrice(posToPrice(Number(e.target.value)))}
              onPointerUp={(e) => onPriceCommit(posToPrice(Number((e.target as HTMLInputElement).value)))}
              onBlur={(e) => onPriceCommit(posToPrice(Number(e.target.value)))}
              onClick={(e) => e.stopPropagation()}
              onPointerDown={(e) => e.stopPropagation()}
              style={{
                width: "100%",
                display: "block",
                accentColor: accent,
                cursor: "pointer",
              }}
            />
            <div style={{ position: "relative", height: 16, marginTop: 3 }}>
              {([
                [q10, "10%", false],
                [q50, "50%", true],
                [q90, "90%", false],
              ] as const).map(([v, left, emph]) => (
                <div
                  key={left}
                  style={{
                    position: "absolute",
                    left,
                    transform: "translateX(-50%)",
                    fontSize: 9.5,
                    fontFamily: MONO,
                    color: emph ? "#3a3b3a" : "#9b9c99",
                    fontWeight: emph ? 600 : 400,
                    whiteSpace: "nowrap",
                  }}
                >
                  {fmt(v)}
                </div>
              ))}
            </div>
          </div>
        </>
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
    </div>
  );
}

export default function ResultsScreen({
  imageUrl,
  labelImageUrl,
  data: initialData,
  connectionStatus,
  onPublishMany,
  onReset,
  onConnectPlatform,
  error,
  isFreshUpload,
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
  const [priceEdits, setPriceEdits] = useState<Partial<Record<Platform, number>>>({});

  const vintedQ50 = data.vinted.price.q50;
  const kaQ50 = data.kleinanzeigen.price.q50;
  const recommendedPlatform: Platform = vintedQ50 >= kaQ50 ? "vinted" : "kleinanzeigen";

  const activeId =
    selectedPlatform === "vinted" ? data.vinted.identification : data.kleinanzeigen.identification;

  const detailVal = (f: DetailKey): string =>
    (fieldEdits[f] as string | undefined) ?? (data.vinted.identification[f] as string | null) ?? "";

  const listingTitle = titleEdits[selectedPlatform] ?? activeId.title ?? "";
  const listingDesc = descEdits[selectedPlatform] ?? activeId.description ?? "";

  const wearDetected = data.visual_wear_probability > 0.4;
  const conditionVal = detailVal("condition");
  const wearConflict =
    data.visual_wear_probability > 0.5 && !!conditionVal && OPTIMISTIC_CONDITIONS.has(conditionVal);
  const reviewSet = new Set(data.vinted.field_review.needs_review);
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

  // Default ask price for a platform. Stable for the session.
  //
  // Re-opened from inventory (`!isFreshUpload`): respect any persisted edit on
  // `identification.price_eur` — the patch endpoint stamps source='edit' on
  // the predictions row, and overwriting it would silently lose the user's
  // saved price.
  //
  // Fresh scan / verify (`isFreshUpload`): the VLM's emitted `price_eur` is
  // a hint, not a recommendation — it tends to under-call against the
  // price-head's quantiles. Default to ~38th percentile of the band
  // (`0.7·q50 + 0.3·q10`) so the slider lands a bit under market without
  // dropping below q10.
  function modelPrice(platform: Platform): number {
    const id = platform === "vinted" ? data.vinted.identification : data.kleinanzeigen.identification;
    const band = platform === "vinted" ? data.vinted.price : data.kleinanzeigen.price;
    if (!isFreshUpload && id.price_eur != null) return Math.round(id.price_eur as number);
    return Math.round(0.7 * band.q50 + 0.3 * band.q10);
  }

  function priceFor(platform: Platform): number {
    const edited = priceEdits[platform];
    if (typeof edited === "number" && edited > 0) return edited;
    return modelPrice(platform);
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

  // KA's category encodes both gender and clothing-vs-shoes ("Men's clothing",
  // "Women's shoes", …); the "Type" picker is Vinted vocabulary (a garment
  // type, no gender). So for a KA publish: take gender from the KA block's own
  // label, take clothing-vs-shoes from the Type edit if the user touched it.
  // (Sending the Vinted leaf as KA's `category` is what made a recent KA
  // cross-post fail with "no Kleinanzeigen category mapping".)
  function kaCategory(): string {
    const kaLabel = ((data.kleinanzeigen.identification.category as string | null) ?? "").trim();
    const men = /^men/i.test(kaLabel);
    const leaf = fieldEdits.category as string | undefined;
    if (!leaf) return kaLabel || (men ? "Men's clothing" : "Women's clothing");
    const shoes =
      leaf === "sneakers" ? true
      : (["tshirts", "jackets", "jeans"] as string[]).includes(leaf) ? false
      : /shoe/i.test(kaLabel); // unknown leaf — keep whatever the KA block implied
    return `${men ? "Men's" : "Women's"} ${shoes ? "shoes" : "clothing"}`;
  }

  function buildFinalFields(platform: Platform): Identification {
    const id =
      platform === "vinted" ? data.vinted.identification : data.kleinanzeigen.identification;
    const merged: Identification = {
      ...id,
      ...fieldEdits,
      title: titleEdits[platform] ?? id.title,
      description: descEdits[platform] ?? id.description,
      price_eur: priceFor(platform),
    };
    if (platform === "kleinanzeigen") merged.category = kaCategory();
    return merged;
  }

  function handlePublish(platform: Platform) {
    onPublishMany([{ platform, finalFields: buildFinalFields(platform) }]);
  }

  function handlePublishBoth() {
    onPublishMany([
      { platform: "vinted", finalFields: buildFinalFields("vinted") },
      { platform: "kleinanzeigen", finalFields: buildFinalFields("kleinanzeigen") },
    ]);
  }

  const bothReady = vintedReady && kaReady;
  const missingPlatform: Platform = vintedReady ? "kleinanzeigen" : "vinted";

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
                    {key === "condition" || key === "category" || key === "size" ? (
                      <DetailSelect
                        value={value}
                        options={
                          key === "condition"
                            ? CONDITION_OPTIONS
                            : key === "category"
                              ? CATEGORY_OPTIONS
                              : sizeOptionsFor(detailVal("category"))
                        }
                        onPick={(v) => {
                          setDetail(key, v);
                          persistFields({ [key]: v || null } as Partial<Identification>);
                        }}
                      />
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
              currentPrice={priceFor("vinted")}
              originalPrice={modelPrice("vinted")}
              onPrice={(n) => setPriceEdits((e) => ({ ...e, vinted: n }))}
              onPriceCommit={(n) => persistFields({ price_eur: n })}
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
              currentPrice={priceFor("kleinanzeigen")}
              originalPrice={modelPrice("kleinanzeigen")}
              onPrice={(n) => setPriceEdits((e) => ({ ...e, kleinanzeigen: n }))}
              onPriceCommit={(n) => persistFields({ price_eur: n })}
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
        {/* Primary: publish on both. When one platform is disconnected, this
            button prompts to reconnect that platform; the per-platform secondary
            buttons below still let you publish on whatever IS connected. */}
        <button
          onClick={() =>
            bothReady ? handlePublishBoth() : onConnectPlatform(missingPlatform)
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
            {bothReady
              ? "Publish on Vinted & Kleinanzeigen"
              : `Reconnect ${PLATFORM_LABEL[missingPlatform]} to publish on both`}
          </span>
          {bothReady && (
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
              {fmt(priceFor("vinted"))} + {fmt(priceFor("kleinanzeigen"))}
            </span>
          )}
        </button>

        {/* Per-platform fallbacks — equal-weight, side-by-side. */}
        <div style={{ display: "flex", gap: 8 }}>
          {(["vinted", "kleinanzeigen"] as const).map((p) => {
            const ready = isReady(p);
            return (
              <button
                key={p}
                onClick={() => (ready ? handlePublish(p) : onConnectPlatform(p))}
                style={{
                  flex: 1,
                  height: 40,
                  borderRadius: 10,
                  border: "1px solid #e7e5e0",
                  background: "#fff",
                  cursor: "pointer",
                  fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
                  fontSize: 13,
                  fontWeight: 500,
                  color: ready ? "#0e0f0e" : "#6b6c6a",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 6,
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {ready
                  ? `Just ${PLATFORM_LABEL[p]} · ${fmt(priceFor(p))}`
                  : `Reconnect ${PLATFORM_LABEL[p]}`}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

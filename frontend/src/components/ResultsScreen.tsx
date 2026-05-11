"use client";

import { useState } from "react";
import type {
  Identification,
  OnboardingStatus,
  Platform,
  UploadResponse,
} from "@/types/api";
import { verifyListing } from "@/api/verify";
import SmallCaps from "./ui/SmallCaps";

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

// Pill chip for identification fields
function Chip({
  children,
  dim,
}: {
  children: React.ReactNode;
  dim?: boolean;
}) {
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "7px 12px",
        borderRadius: 999,
        background: "#fff",
        border: "1px solid #e7e5e0",
        fontSize: 13.5,
        fontWeight: 500,
        color: dim ? "#9b9c99" : "#0e0f0e",
        fontStyle: dim ? "italic" : "normal",
        lineHeight: 1,
        whiteSpace: "nowrap" as const,
      }}
    >
      {children}
    </div>
  );
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
  const [editOpen, setEditOpen] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [selectedPlatform, setSelectedPlatform] = useState<Platform>("vinted");
  const [hints, setHints] = useState<Partial<Identification>>({});

  const vintedQ50 = data.vinted.price.q50;
  const kaQ50 = data.kleinanzeigen.price.q50;
  const recommendedPlatform: Platform = vintedQ50 >= kaQ50 ? "vinted" : "kleinanzeigen";

  const activeId =
    selectedPlatform === "vinted"
      ? data.vinted.identification
      : data.kleinanzeigen.identification;

  const [titleEdits, setTitleEdits] = useState<Partial<Record<Platform, string>>>({});
  const [descEdits, setDescEdits] = useState<Partial<Record<Platform, string>>>({});

  const listingTitle = titleEdits[selectedPlatform] ?? activeId.title ?? "";
  const listingDesc = descEdits[selectedPlatform] ?? activeId.description ?? "";

  const wearDetected = data.visual_wear_probability > 0.4;
  const vintedReview = new Set(data.vinted.field_review?.needs_review ?? []);

  const idBlock = data.vinted.identification;
  const wearConflict =
    data.visual_wear_probability > 0.5 &&
    !!idBlock.condition &&
    OPTIMISTIC_CONDITIONS.has(idBlock.condition);
  const itemHeadline = [
    idBlock.brand,
    idBlock.color?.toLowerCase(),
    idBlock.category?.toLowerCase(),
    idBlock.condition ? `— ${idBlock.condition.toLowerCase()}` : null,
  ]
    .filter(Boolean)
    .join(" ");

  async function handleVerify(e: React.FormEvent) {
    e.preventDefault();
    setVerifying(true);
    try {
      const updated = await verifyListing({ listing_id: data.listing_id, hints });
      setData(updated);
    } finally {
      setVerifying(false);
      setEditOpen(false);
    }
  }

  function handlePublish(platform: Platform) {
    const id =
      platform === "vinted" ? data.vinted.identification : data.kleinanzeigen.identification;
    onPublish(platform, {
      ...id,
      title: listingTitle || id.title,
      description: listingDesc || id.description,
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

        {/* Identification chips */}
        <div
          style={{
            padding: "0 20px",
            display: "flex",
            flexWrap: "wrap",
            gap: 6,
          }}
        >
          {idBlock.brand && <Chip>{idBlock.brand}</Chip>}
          {idBlock.category && <Chip>{idBlock.category}</Chip>}
          {idBlock.condition && <Chip>{idBlock.condition}</Chip>}
          {idBlock.color && <Chip>{idBlock.color}</Chip>}
          <Chip dim={vintedReview.has("size") || !idBlock.size}>
            Size {idBlock.size ?? "—"}{(vintedReview.has("size") || !idBlock.size) ? " · Check" : ""}
          </Chip>
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
                    Model #1 read this as &ldquo;{idBlock.condition}&rdquo; but our flaw detector
                    sees possible wear — please re-check the condition.
                  </>
                ) : (
                  <>
                    <span style={{ fontWeight: 600, color: "#0e0f0e" }}>Visible wear detected.</span>{" "}
                    Light wear detected. We adjusted condition accordingly.
                  </>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Edit details button */}
        <div style={{ padding: "14px 20px 0" }}>
          <button
            onClick={() => setEditOpen((o) => !o)}
            style={{
              width: "100%",
              padding: "14px 16px",
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
            <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path
                  d="M2 10l1.2-3.2L9 1l3 3-5.8 5.8L3 11l-1-1z"
                  stroke="#3a3b3a"
                  strokeWidth="1.4"
                  strokeLinejoin="round"
                />
              </svg>
              {editOpen ? "Hide details" : "Edit details"}
            </span>
          </button>

          {/* Edit form */}
          {editOpen && (
            <form
              onSubmit={handleVerify}
              style={{
                marginTop: 12,
                background: "#fff",
                borderRadius: 12,
                border: "1px solid #e7e5e0",
                padding: "14px 16px",
              }}
            >
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
                  <SmallCaps style={{ display: "block", marginBottom: 4 }}>
                    {label}
                  </SmallCaps>
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
                      border: "1.5px solid #e7e5e0",
                      borderRadius: 8,
                      backgroundColor: "#fafaf8",
                      color: "#0e0f0e",
                      outline: "none",
                      minHeight: 44,
                      fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
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
                  backgroundColor: verifying ? "#9b9c99" : "#0e0f0e",
                  color: "#fff",
                  fontSize: 14,
                  fontWeight: 600,
                  border: "none",
                  borderRadius: 10,
                  cursor: verifying ? "not-allowed" : "pointer",
                  minHeight: 48,
                  fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
                }}
              >
                {verifying ? "Recalculating…" : "Update listing"}
              </button>
            </form>
          )}
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
              <span style={{ color: ACCENT, cursor: "pointer" }}>Regenerate</span>
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
              {fmt(
                selectedPlatform === "vinted" ? data.vinted.price.q50 : data.kleinanzeigen.price.q50
              )}
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
            ? `Or publish on ${PLATFORM_LABEL[otherPlatform]} · ${fmt(
                otherPlatform === "vinted"
                  ? data.vinted.price.q50
                  : data.kleinanzeigen.price.q50,
              )}`
            : `Or reconnect ${PLATFORM_LABEL[otherPlatform]}`}
        </button>
      </div>
    </div>
  );
}

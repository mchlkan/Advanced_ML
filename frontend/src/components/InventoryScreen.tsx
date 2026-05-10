"use client";

import { useEffect, useState } from "react";
import type { InventoryItem } from "@/types/api";
import { BASE, fetchInventory, markAsSold } from "@/api/inventory";
import SmallCaps from "./ui/SmallCaps";

interface Props {
  onBack: () => void;
}

const PLATFORM_ACCENT: Record<string, string> = {
  vinted: "oklch(0.55 0.08 195)",
  kleinanzeigen: "oklch(0.62 0.13 55)",
};

const PLATFORM_SOFT: Record<string, string> = {
  vinted: "oklch(0.97 0.02 195)",
  kleinanzeigen: "oklch(0.97 0.03 70)",
};

function PlatformBadge({ platform }: { platform: string }) {
  const accent = PLATFORM_ACCENT[platform] ?? "#9b9c99";
  const soft = PLATFORM_SOFT[platform] ?? "#f5f5f5";
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 600,
        letterSpacing: "0.12em",
        textTransform: "uppercase",
        color: accent,
        backgroundColor: soft,
        padding: "3px 7px",
        borderRadius: 999,
        border: `1px solid ${accent}33`,
      }}
    >
      {platform}
    </span>
  );
}

function SkeletonCard() {
  return (
    <div
      style={{
        display: "flex",
        gap: 14,
        padding: "16px 0",
        borderBottom: "1px solid #e7e5e0",
        alignItems: "center",
      }}
    >
      <div
        style={{
          width: 64,
          height: 64,
          backgroundColor: "#efece6",
          flexShrink: 0,
          borderRadius: 10,
        }}
      />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
        <div
          style={{ height: 14, width: "60%", backgroundColor: "#efece6", borderRadius: 6 }}
        />
        <div
          style={{ height: 11, width: "40%", backgroundColor: "#efece6", borderRadius: 6 }}
        />
      </div>
    </div>
  );
}

export default function InventoryScreen({ onBack }: Props) {
  const [listings, setListings] = useState<InventoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selling, setSelling] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetchInventory()
      .then((res) => setListings(res.items))
      .catch(() => setError("Could not load listings. Is the backend running?"))
      .finally(() => setLoading(false));
  }, []);

  async function handleMarkSold(id: string) {
    setSelling((s) => new Set(s).add(id));
    try {
      await markAsSold(id);
      setListings((prev) => prev.filter((item) => item.listing_id !== id));
    } catch {
      // keep button visible so user can retry
    } finally {
      setSelling((s) => {
        const next = new Set(s);
        next.delete(id);
        return next;
      });
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
      }}
    >
      {/* Header */}
      <header
        style={{
          position: "sticky",
          top: 0,
          backgroundColor: "#fafaf8",
          padding: "20px 24px 16px",
          display: "flex",
          alignItems: "center",
          gap: 12,
          borderBottom: "1px solid #e7e5e0",
          zIndex: 10,
        }}
      >
        <button
          onClick={onBack}
          style={{
            width: 36,
            height: 36,
            borderRadius: 18,
            border: "1px solid #e7e5e0",
            background: "#fff",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 0,
            flexShrink: 0,
          }}
          aria-label="Back"
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
        <span style={{ fontSize: 16, fontWeight: 600, letterSpacing: "-0.3px" }}>
          My Listings
        </span>
        {!loading && (
          <span
            style={{
              marginLeft: "auto",
              fontFamily: '"JetBrains Mono", ui-monospace, monospace',
              fontSize: 11,
              color: "#9b9c99",
              textTransform: "uppercase",
              letterSpacing: "1px",
            }}
          >
            {listings.length} item{listings.length !== 1 ? "s" : ""}
          </span>
        )}
      </header>

      {/* Body */}
      <main style={{ flex: 1, padding: "0 24px", overflowY: "auto" }}>
        {loading && (
          <>
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </>
        )}

        {error && (
          <p
            style={{
              marginTop: 40,
              textAlign: "center",
              color: "#6b6c6a",
              fontSize: 14,
            }}
          >
            {error}
          </p>
        )}

        {!loading && !error && listings.length === 0 && (
          <div
            style={{
              marginTop: 80,
              textAlign: "center",
              color: "#9b9c99",
            }}
          >
            <div
              style={{
                width: 48,
                height: 48,
                borderRadius: 12,
                border: "1.5px dashed #e7e5e0",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                margin: "0 auto 16px",
              }}
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path
                  d="M10 4v12M4 10h12"
                  stroke="#9b9c99"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                />
              </svg>
            </div>
            <p style={{ fontSize: 15, margin: 0, color: "#3a3b3a", fontWeight: 500 }}>
              No listings yet.
            </p>
            <p style={{ fontSize: 13, marginTop: 4, color: "#9b9c99" }}>
              Upload a photo to create your first one.
            </p>
          </div>
        )}

        {listings.map((item) => {
          const fields = item.prediction?.english_fields ?? {};
          const title = (fields.title as string) ?? null;
          const brand = (fields.brand as string) ?? null;
          const category = (fields.category as string) ?? null;
          const publishedPlatforms = [
            item.vinted && "vinted",
            item.kleinanzeigen && "kleinanzeigen",
          ].filter(Boolean) as string[];
          return (
            <div
              key={item.listing_id}
              style={{
                display: "flex",
                gap: 14,
                padding: "16px 0",
                borderBottom: "1px solid #e7e5e0",
                alignItems: "center",
              }}
            >
              {/* Thumbnail */}
              <img
                src={`${BASE}${item.thumbnail_url}`}
                alt={title ?? "listing"}
                style={{
                  width: 64,
                  height: 64,
                  objectFit: "cover",
                  flexShrink: 0,
                  backgroundColor: "#efece6",
                  imageOrientation: "from-image",
                  borderRadius: 10,
                  border: "1px solid #e7e5e0",
                }}
              />

              {/* Details */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <p
                  style={{
                    margin: "0 0 3px",
                    fontSize: 14,
                    fontWeight: 600,
                    letterSpacing: "-0.2px",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {title ?? "Untitled"}
                </p>
                <p
                  style={{
                    margin: "0 0 6px",
                    fontSize: 12,
                    color: "#6b6c6a",
                  }}
                >
                  {[brand, category].filter(Boolean).join(" · ") || "—"}
                </p>
                <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                  {publishedPlatforms.map((p) => (
                    <PlatformBadge key={p} platform={p} />
                  ))}
                  {publishedPlatforms.length === 0 && (
                    <SmallCaps size={10}>not published</SmallCaps>
                  )}
                </div>
              </div>

              {/* Sold action */}
              <div style={{ flexShrink: 0, marginLeft: 8 }}>
                <button
                  onClick={() => handleMarkSold(item.listing_id)}
                  disabled={selling.has(item.listing_id)}
                  style={{
                    fontSize: 12,
                    fontWeight: 600,
                    padding: "7px 12px",
                    border: "1px solid #e7e5e0",
                    borderRadius: 8,
                    backgroundColor: "#fff",
                    color: "#0e0f0e",
                    cursor: selling.has(item.listing_id) ? "default" : "pointer",
                    opacity: selling.has(item.listing_id) ? 0.5 : 1,
                    letterSpacing: "-0.1px",
                    fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
                  }}
                >
                  {selling.has(item.listing_id) ? "…" : "Mark sold"}
                </button>
              </div>
            </div>
          );
        })}
      </main>
    </div>
  );
}

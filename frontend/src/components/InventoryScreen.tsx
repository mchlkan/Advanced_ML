"use client";

import { useEffect, useState } from "react";
import type { ListingItem } from "@/types/api";
import { BASE, fetchInventory, markAsSold } from "@/api/inventory";

interface Props {
  onBack: () => void;
}

const PLATFORM_COLORS: Record<string, string> = {
  vinted: "#00a987",
  kleinanzeigen: "#d97706",
};

function PlatformBadge({ platform }: { platform: string }) {
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 600,
        letterSpacing: "0.4px",
        textTransform: "uppercase",
        color: "#fff",
        backgroundColor: PLATFORM_COLORS[platform] ?? "var(--color-ink-tertiary)",
        padding: "2px 6px",
        borderRadius: 3,
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
        borderBottom: "1px solid var(--color-border)",
        alignItems: "center",
      }}
    >
      <div
        style={{
          width: 64,
          height: 64,
          backgroundColor: "var(--color-bg-card)",
          flexShrink: 0,
        }}
      />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ height: 14, width: "60%", backgroundColor: "var(--color-bg-card)" }} />
        <div style={{ height: 11, width: "40%", backgroundColor: "var(--color-bg-card)" }} />
      </div>
    </div>
  );
}

export default function InventoryScreen({ onBack }: Props) {
  const [listings, setListings] = useState<ListingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selling, setSelling] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetchInventory()
      .then((res) => setListings(res.listings))
      .catch(() => setError("Could not load listings. Is the backend running?"))
      .finally(() => setLoading(false));
  }, []);

  async function handleMarkSold(id: string) {
    setSelling((s) => new Set(s).add(id));
    try {
      await markAsSold(id);
      setListings((prev) => prev.filter((item) => item.id !== id));
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
          position: "sticky",
          top: 0,
          backgroundColor: "var(--color-bg)",
          padding: "20px 24px 16px",
          display: "flex",
          alignItems: "center",
          gap: 12,
          borderBottom: "1px solid var(--color-border)",
          zIndex: 10,
        }}
      >
        <button
          onClick={onBack}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            padding: "4px 0",
            color: "var(--color-ink)",
            fontSize: 20,
            lineHeight: 1,
          }}
          aria-label="Back"
        >
          ←
        </button>
        <span style={{ fontSize: 16, fontWeight: 600, letterSpacing: "-0.3px" }}>
          My Listings
        </span>
        {!loading && (
          <span
            style={{
              marginLeft: "auto",
              fontSize: 12,
              color: "var(--color-ink-tertiary)",
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
              color: "var(--color-ink-secondary)",
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
              color: "var(--color-ink-tertiary)",
            }}
          >
            <p style={{ fontSize: 32, margin: "0 0 12px" }}>📭</p>
            <p style={{ fontSize: 15, margin: 0 }}>No listings yet.</p>
            <p style={{ fontSize: 13, marginTop: 4 }}>
              Upload a photo to create your first one.
            </p>
          </div>
        )}

        {listings.map((item) => (
          <div
            key={item.id}
            style={{
              display: "flex",
              gap: 14,
              padding: "16px 0",
              borderBottom: "1px solid var(--color-border)",
              alignItems: "center",
              opacity: 1,
            }}
          >
            {/* Thumbnail */}
            <img
              src={`${BASE}${item.image_url}`}
              alt={item.title ?? "listing"}
              style={{
                width: 64,
                height: 64,
                objectFit: "cover",
                flexShrink: 0,
                backgroundColor: "var(--color-bg-card)",
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
                {item.title ?? "Untitled"}
              </p>
              <p
                style={{
                  margin: "0 0 6px",
                  fontSize: 12,
                  color: "var(--color-ink-secondary)",
                }}
              >
                {[item.brand, item.category].filter(Boolean).join(" · ") || "—"}
              </p>
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                {item.published_platforms.map((p) => (
                  <PlatformBadge key={p} platform={p} />
                ))}
                {item.published_platforms.length === 0 && (
                  <span
                    style={{
                      fontSize: 10,
                      color: "var(--color-ink-tertiary)",
                      letterSpacing: "0.3px",
                    }}
                  >
                    not published
                  </span>
                )}
              </div>
            </div>

            {/* Sold action */}
            <div style={{ flexShrink: 0, marginLeft: 8 }}>
              <button
                onClick={() => handleMarkSold(item.id)}
                disabled={selling.has(item.id)}
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  padding: "6px 12px",
                  border: "1.5px solid var(--color-border)",
                  backgroundColor: "transparent",
                  color: "var(--color-ink)",
                  cursor: selling.has(item.id) ? "default" : "pointer",
                  opacity: selling.has(item.id) ? 0.5 : 1,
                  letterSpacing: "-0.1px",
                }}
              >
                {selling.has(item.id) ? "…" : "Mark sold"}
              </button>
            </div>
          </div>
        ))}
      </main>
    </div>
  );
}

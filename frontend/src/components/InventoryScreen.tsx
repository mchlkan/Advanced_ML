"use client";

import { useEffect, useState } from "react";
import type { InventoryItem } from "@/types/api";
import {
  BASE,
  deleteListing,
  fetchInventory,
  markAsSold,
  patchListingFields,
  syncWardrobe,
  type PatchFieldsResponse,
} from "@/api/inventory";
import SmallCaps from "./ui/SmallCaps";

interface Props {
  onBack: () => void;
  onOpenListing: (listingId: string) => void;
  onRelistListing: (listingId: string, platforms: ("vinted" | "kleinanzeigen")[]) => void;
}

const PLATFORM_ACCENT: Record<string, string> = {
  vinted: "oklch(0.55 0.08 195)",
  kleinanzeigen: "oklch(0.62 0.13 55)",
};

const PLATFORM_SOFT: Record<string, string> = {
  vinted: "oklch(0.97 0.02 195)",
  kleinanzeigen: "oklch(0.97 0.03 70)",
};

const FONT = '"Inter", -apple-system, system-ui, sans-serif';

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

function getPostedPlatforms(item: InventoryItem): ("vinted" | "kleinanzeigen")[] {
  const out: ("vinted" | "kleinanzeigen")[] = [];
  if (item.vinted?.status === "posted") out.push("vinted");
  if (item.kleinanzeigen?.status === "posted") out.push("kleinanzeigen");
  return out;
}

const STAT_COLOR = "#6b6c6a";

function EyeIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
      <path d="M0.75 6S2.75 2 6 2s5.25 4 5.25 4-2 4-5.25 4S0.75 6 0.75 6Z"
        stroke={STAT_COLOR} strokeWidth="1.1" strokeLinejoin="round" />
      <circle cx="6" cy="6" r="1.6" stroke={STAT_COLOR} strokeWidth="1.1" />
    </svg>
  );
}

function HeartIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
      <path d="M6 10.25 1.9 6.15a2.4 2.4 0 0 1 3.4-3.4l.7.7.7-.7a2.4 2.4 0 0 1 3.4 3.4L6 10.25Z"
        stroke={STAT_COLOR} strokeWidth="1.1" strokeLinejoin="round" />
    </svg>
  );
}

function RefreshIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
      <path d="M10.25 6a4.25 4.25 0 1 1-1.3-3.06" stroke={STAT_COLOR}
        strokeWidth="1.2" strokeLinecap="round" />
      <path d="M10.5 1v2.2H8.3" stroke={STAT_COLOR} strokeWidth="1.2"
        strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ---- per-card action icons (inline toolbar; replaces the kebab sheet) ----

const ICON_PROPS = {
  width: 15, height: 15, viewBox: "0 0 16 16", fill: "none",
  "aria-hidden": true,
} as const;
const STROKE = { stroke: "currentColor", strokeLinecap: "round", strokeLinejoin: "round" } as const;

function OpenIcon() {
  return (
    <svg {...ICON_PROPS}>
      <path d="M9.5 3H13v3.5" strokeWidth="1.5" {...STROKE} />
      <path d="M13 3l-5 5" strokeWidth="1.5" {...STROKE} />
      <path d="M11.5 9v2.5a1.5 1.5 0 0 1-1.5 1.5H4.5A1.5 1.5 0 0 1 3 11.5V6A1.5 1.5 0 0 1 4.5 4.5H7" strokeWidth="1.5" {...STROKE} />
    </svg>
  );
}
function PriceTagIcon() {
  return (
    <svg {...ICON_PROPS}>
      <path d="M8.4 2.6H3.5a.9.9 0 0 0-.9.9v4.9c0 .24.1.47.26.64l5.7 5.7a.9.9 0 0 0 1.28 0l4.9-4.9a.9.9 0 0 0 0-1.28l-5.7-5.7a.9.9 0 0 0-.64-.26Z" strokeWidth="1.4" {...STROKE} />
      <circle cx="5.6" cy="5.6" r="1.05" strokeWidth="1.3" stroke="currentColor" />
    </svg>
  );
}
function RelistIcon() {
  return (
    <svg {...ICON_PROPS}>
      <path d="M13 8a5 5 0 1 1-1.46-3.54" strokeWidth="1.5" {...STROKE} />
      <path d="M13 2.5V5.5H10" strokeWidth="1.5" {...STROKE} />
    </svg>
  );
}
function SoldIcon() {
  return (
    <svg {...ICON_PROPS}>
      <path d="M2.8 8.6l3.3 3.3L13.2 4.5" strokeWidth="1.7" {...STROKE} />
    </svg>
  );
}
function TrashIcon() {
  return (
    <svg {...ICON_PROPS}>
      <path d="M2.75 4.25h10.5" strokeWidth="1.5" {...STROKE} />
      <path d="M6 4.25V3a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1.25" strokeWidth="1.5" {...STROKE} />
      <path d="M4.25 4.25l.6 8.1a1.2 1.2 0 0 0 1.2 1.1h3.9a1.2 1.2 0 0 0 1.2-1.1l.6-8.1" strokeWidth="1.5" {...STROKE} />
      <path d="M6.6 7v3.6M9.4 7v3.6" strokeWidth="1.35" {...STROKE} />
    </svg>
  );
}

function IconBtn({
  label, onClick, destructive, children,
}: {
  label: string;
  onClick: () => void;
  destructive?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      style={{
        width: 32, height: 32, borderRadius: 9,
        border: `1px solid ${destructive ? "#ecc9c4" : "#e7e5e0"}`,
        background: destructive ? "#fdf6f5" : "#fff",
        color: destructive ? "#c0392b" : "#3a3b3a",
        cursor: "pointer", flexShrink: 0,
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        padding: 0, fontFamily: FONT,
      }}
    >
      {children}
    </button>
  );
}

function formatSyncedAgo(ms: number | null): string {
  if (!ms) return "never";
  const s = Math.max(0, Math.floor((Date.now() - ms) / 1000));
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export default function InventoryScreen({ onBack, onOpenListing, onRelistListing }: Props) {
  const [listings, setListings] = useState<InventoryItem[]>([]);
  const [lastSyncedAt, setLastSyncedAt] = useState<number | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [priceEdit, setPriceEdit] = useState<InventoryItem | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<InventoryItem | null>(null);

  useEffect(() => {
    fetchInventory()
      .then((res) => {
        setListings(res.items);
        setLastSyncedAt(res.last_synced_at);
      })
      .catch(() => setError("Could not load listings. Is the backend running?"))
      .finally(() => setLoading(false));
  }, []);

  function setBusyState(id: string, isBusy: boolean) {
    setBusy((s) => {
      const next = new Set(s);
      if (isBusy) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  async function refetch() {
    try {
      const res = await fetchInventory();
      setListings(res.items);
      setLastSyncedAt(res.last_synced_at);
    } catch {
      // Soft-fail; keep current state.
    }
  }

  async function handleSync() {
    setSyncing(true);
    setSyncMsg(null);
    try {
      await syncWardrobe();
      await refetch();
    } catch (e) {
      const code = e instanceof Error ? e.message : "";
      setSyncMsg(
        code.includes("409")
          ? "Connect Vinted to sync live stats."
          : code.includes("401")
          ? "Vinted session expired — reconnect."
          : code.includes("429")
          ? "Vinted is rate-limiting — try again shortly."
          : "Couldn't sync live stats. Try again.",
      );
    } finally {
      setSyncing(false);
    }
  }

  async function handleMarkSold(item: InventoryItem) {
    setBusyState(item.listing_id, true);
    try {
      await markAsSold(item.listing_id);
      setListings((prev) => prev.filter((it) => it.listing_id !== item.listing_id));
    } catch {
      // Surface in card; for now keep silent.
    } finally {
      setBusyState(item.listing_id, false);
    }
  }

  async function handleConfirmDelete(item: InventoryItem) {
    setDeleteConfirm(null);
    setBusyState(item.listing_id, true);
    try {
      await deleteListing(item.listing_id);
      setListings((prev) => prev.filter((it) => it.listing_id !== item.listing_id));
    } catch {
      // Stay; user can retry.
    } finally {
      setBusyState(item.listing_id, false);
    }
  }

  async function handleSavePrice(item: InventoryItem, newPrice: number): Promise<PatchFieldsResponse> {
    setBusyState(item.listing_id, true);
    try {
      const res = await patchListingFields(item.listing_id, { price_eur: newPrice });
      // Refresh inventory in the background so the card's title/brand/category
      // reflects any side effects, but don't block the modal on it.
      void refetch();
      return res;
    } finally {
      setBusyState(item.listing_id, false);
    }
  }

  function handleRelist(item: InventoryItem) {
    const platforms = getPostedPlatforms(item);
    if (platforms.length === 0) return;
    onRelistListing(item.listing_id, platforms);
  }

  function handleOpen(item: InventoryItem) {
    onOpenListing(item.listing_id);
  }

  return (
    <div
      style={{
        height: "100dvh",
        display: "flex",
        flexDirection: "column",
        backgroundColor: "#fafaf8",
        color: "#0e0f0e",
        fontFamily: FONT,
      }}
    >
      <header
        style={{
          position: "sticky",
          top: 0,
          backgroundColor: "#fafaf8",
          padding: "20px 24px 14px",
          display: "flex",
          flexDirection: "column",
          alignItems: "stretch",
          gap: 6,
          borderBottom: "1px solid #e7e5e0",
          zIndex: 10,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button
            onClick={onBack}
            style={{
              width: 36, height: 36, borderRadius: 18,
              border: "1px solid #e7e5e0", background: "#fff",
              cursor: "pointer", display: "flex",
              alignItems: "center", justifyContent: "center",
              padding: 0, flexShrink: 0,
            }}
            aria-label="Back"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M9 2L4 7l5 5" stroke="#0e0f0e" strokeWidth="1.6"
                strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          <span style={{ fontSize: 16, fontWeight: 600, letterSpacing: "-0.3px" }}>
            My Listings
          </span>
          <div style={{
            marginLeft: "auto", display: "flex", alignItems: "center", gap: 10,
          }}>
            <button
              onClick={handleSync}
              disabled={syncing}
              style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                height: 28, padding: "0 11px", borderRadius: 14,
                border: "1px solid #e7e5e0", background: "#fff",
                cursor: syncing ? "default" : "pointer",
                opacity: syncing ? 0.5 : 1,
                fontSize: 12, fontWeight: 500, color: "#0e0f0e",
                fontFamily: FONT,
              }}
            >
              <RefreshIcon />
              {syncing ? "Syncing…" : "Sync"}
            </button>
            {!loading && (
              <span style={{
                fontFamily: '"JetBrains Mono", ui-monospace, monospace',
                fontSize: 11, color: "#9b9c99",
                textTransform: "uppercase", letterSpacing: "1px",
              }}>
                {listings.length} item{listings.length !== 1 ? "s" : ""}
              </span>
            )}
          </div>
        </div>
        {(syncMsg || lastSyncedAt != null) && (
          <span style={{
            marginLeft: 48,
            fontFamily: syncMsg ? FONT : '"JetBrains Mono", ui-monospace, monospace',
            fontSize: 11,
            color: syncMsg ? "#c0392b" : "#9b9c99",
            textTransform: syncMsg ? "none" : "uppercase",
            letterSpacing: syncMsg ? "normal" : "0.06em",
          }}>
            {syncMsg ?? `Synced ${formatSyncedAgo(lastSyncedAt)}`}
          </span>
        )}
      </header>

      <main style={{ flex: 1, padding: "0 24px", overflowY: "auto" }}>
        {loading && (
          <>
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </>
        )}

        {error && (
          <p style={{ marginTop: 40, textAlign: "center", color: "#6b6c6a", fontSize: 14 }}>
            {error}
          </p>
        )}

        {!loading && !error && listings.length === 0 && (
          <div style={{ marginTop: 80, textAlign: "center", color: "#9b9c99" }}>
            <div style={{
              width: 48, height: 48, borderRadius: 12,
              border: "1.5px dashed #e7e5e0", display: "flex",
              alignItems: "center", justifyContent: "center",
              margin: "0 auto 16px",
            }}>
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path d="M10 4v12M4 10h12" stroke="#9b9c99" strokeWidth="1.6" strokeLinecap="round" />
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
          const priceVal =
            (fields.price_eur as number | undefined) ??
            item.prediction?.vinted?.q50 ??
            null;
          const publishedPlatforms = [
            item.vinted && "vinted",
            item.kleinanzeigen && "kleinanzeigen",
          ].filter(Boolean) as string[];
          const canRelist = getPostedPlatforms(item).length > 0;
          const isBusy = busy.has(item.listing_id);
          return (
            <div
              key={item.listing_id}
              style={{
                display: "flex", flexDirection: "column",
                padding: "16px 0",
                borderBottom: "1px solid #e7e5e0",
              }}
            >
              <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
                <button
                  onClick={() => handleOpen(item)}
                  style={{
                    background: "none", border: "none", padding: 0,
                    cursor: "pointer", flexShrink: 0,
                  }}
                  aria-label="Open listing"
                >
                  <img
                    src={`${BASE}${item.thumbnail_url}`}
                    alt={title ?? "listing"}
                    style={{
                      width: 64, height: 64, objectFit: "cover",
                      backgroundColor: "#efece6",
                      imageOrientation: "from-image",
                      borderRadius: 10, border: "1px solid #e7e5e0",
                      display: "block",
                    }}
                  />
                </button>

                <div
                  style={{ flex: 1, minWidth: 0, cursor: "pointer" }}
                  onClick={() => handleOpen(item)}
                >
                  <div style={{
                    display: "flex", alignItems: "baseline", gap: 8, marginBottom: 3,
                  }}>
                    <p style={{
                      margin: 0, flex: 1, minWidth: 0, fontSize: 14, fontWeight: 600,
                      letterSpacing: "-0.2px", whiteSpace: "nowrap",
                      overflow: "hidden", textOverflow: "ellipsis",
                    }}>
                      {title ?? "Untitled"}
                    </p>
                    {priceVal != null && (
                      <span style={{
                        flexShrink: 0,
                        fontFamily: '"JetBrains Mono", ui-monospace, monospace',
                        fontSize: 13.5, fontWeight: 600, color: "#0e0f0e",
                        letterSpacing: "-0.02em",
                      }}>
                        €{Math.round(priceVal)}
                      </span>
                    )}
                  </div>
                  <p style={{ margin: "0 0 6px", fontSize: 12, color: "#6b6c6a" }}>
                    {[brand, category].filter(Boolean).join(" · ") || "—"}
                  </p>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                    {publishedPlatforms.map((p) => (
                      <PlatformBadge key={p} platform={p} />
                    ))}
                    {publishedPlatforms.length === 0 && (
                      <SmallCaps size={10}>not published</SmallCaps>
                    )}
                    {item.vinted?.live && (
                      <span style={{
                        display: "inline-flex", alignItems: "center", gap: 8,
                        fontFamily: '"JetBrains Mono", ui-monospace, monospace',
                        fontSize: 11, color: STAT_COLOR,
                      }}>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}
                          title="views">
                          <EyeIcon /> {item.vinted.live.views ?? 0}
                        </span>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}
                          title="favourites">
                          <HeartIcon /> {item.vinted.live.favourites ?? 0}
                        </span>
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <div
                onClick={(e) => e.stopPropagation()}
                style={{
                  display: "flex", justifyContent: "flex-end", gap: 7,
                  marginTop: 11,
                  opacity: isBusy ? 0.4 : 1,
                  pointerEvents: isBusy ? "none" : "auto",
                }}
              >
                <IconBtn label="Open" onClick={() => handleOpen(item)}>
                  <OpenIcon />
                </IconBtn>
                <IconBtn label="Change price" onClick={() => setPriceEdit(item)}>
                  <PriceTagIcon />
                </IconBtn>
                {canRelist && (
                  <IconBtn label="Relist" onClick={() => handleRelist(item)}>
                    <RelistIcon />
                  </IconBtn>
                )}
                <IconBtn label="Mark sold" onClick={() => handleMarkSold(item)}>
                  <SoldIcon />
                </IconBtn>
                <IconBtn label="Delete" destructive onClick={() => setDeleteConfirm(item)}>
                  <TrashIcon />
                </IconBtn>
              </div>
            </div>
          );
        })}
      </main>

      {priceEdit && (
        <PriceEditModal
          item={priceEdit}
          onClose={() => setPriceEdit(null)}
          onSaveAsync={(p) => handleSavePrice(priceEdit, p)}
        />
      )}

      {deleteConfirm && (
        <ConfirmDialog
          title="Delete this listing?"
          body={
            getPostedPlatforms(deleteConfirm).length > 0
              ? "It will be removed from the platforms it was posted on."
              : "This cannot be undone."
          }
          confirmLabel="Delete"
          destructive
          onCancel={() => setDeleteConfirm(null)}
          onConfirm={() => handleConfirmDelete(deleteConfirm)}
        />
      )}
    </div>
  );
}

// ---------- inline modals ----------

function Backdrop({ onClick }: { onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      style={{
        position: "fixed", inset: 0,
        background: "rgba(14,15,14,0.45)",
        zIndex: 50,
      }}
    />
  );
}

const PLATFORM_LABELS_FULL: Record<string, string> = {
  vinted: "Vinted",
  kleinanzeigen: "Kleinanzeigen",
};

function PriceEditModal({
  item,
  onClose,
  onSaveAsync,
}: {
  item: InventoryItem;
  onClose: () => void;
  onSaveAsync: (price: number) => Promise<PatchFieldsResponse>;
}) {
  const currentPrice =
    (item.prediction?.english_fields?.price_eur as number | undefined) ??
    item.prediction?.vinted?.q50 ??
    null;
  const [value, setValue] = useState<string>(
    currentPrice != null ? String(Math.round(currentPrice)) : "",
  );
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<PatchFieldsResponse | null>(null);
  const [topError, setTopError] = useState<string | null>(null);
  const postedPlatforms = getPostedPlatforms(item);
  const parsed = parseFloat(value.replace(",", "."));
  const valid = Number.isFinite(parsed) && parsed > 0;

  async function doSave() {
    if (!valid) return;
    setSaving(true);
    setTopError(null);
    try {
      const res = await onSaveAsync(parsed);
      setResult(res);
      // Auto-close on full success; stay open if any platform push errored
      // so the user can read the message.
      if (Object.values(res.pushed).every((p) => p?.ok)) {
        setTimeout(onClose, 1200);
      }
    } catch (err) {
      setTopError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <Backdrop onClick={saving ? () => {} : onClose} />
      <div
        style={{
          position: "fixed", left: 24, right: 24, bottom: "30%",
          background: "#fff", borderRadius: 18,
          padding: "20px 22px",
          boxShadow: "0 12px 40px rgba(14,15,14,0.25)",
          zIndex: 51,
          fontFamily: FONT,
        }}
      >
        <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: "-0.3px", marginBottom: 4 }}>
          Change price
        </div>
        <div style={{ fontSize: 13, color: "#6b6c6a", marginBottom: 16 }}>
          {postedPlatforms.length === 0
            ? "Saved locally. Will be used the next time you publish."
            : `Pushes the new price live to ${postedPlatforms
                .map((p) => PLATFORM_LABELS_FULL[p])
                .join(" + ")}.`}
        </div>
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "10px 14px", border: "1.5px solid #e7e5e0",
          borderRadius: 12, background: "#fafaf8",
          opacity: saving ? 0.6 : 1,
        }}>
          <span style={{ fontSize: 18, color: "#6b6c6a", fontWeight: 500 }}>€</span>
          <input
            autoFocus
            type="number"
            inputMode="decimal"
            value={value}
            disabled={saving}
            onChange={(e) => setValue(e.target.value)}
            placeholder="0"
            style={{
              flex: 1, fontSize: 18, fontWeight: 600,
              border: "none", outline: "none", background: "transparent",
              fontFamily: FONT,
            }}
          />
        </div>

        {(saving || result || topError) && (
          <div style={{
            marginTop: 14, padding: "10px 12px", borderRadius: 10,
            background: "#fafaf8", border: "1px solid #efece6",
            fontSize: 13, lineHeight: 1.5, color: "#3a3b3a",
          }}>
            {saving && <div>Saving and pushing to live listings…</div>}
            {topError && (
              <div style={{ color: "#c0392b" }}>{topError}</div>
            )}
            {result && (
              <>
                <div style={{ color: "#0e0f0e", fontWeight: 500 }}>
                  ✓ Saved locally
                </div>
                {(["vinted", "kleinanzeigen"] as const).map((p) => {
                  const r = result.pushed[p];
                  if (!r) return null;
                  return r.ok ? (
                    <div key={p} style={{ color: "#0e0f0e" }}>
                      ✓ {PLATFORM_LABELS_FULL[p]} updated
                    </div>
                  ) : (
                    <div key={p} style={{ color: "#c0392b" }}>
                      ✗ {PLATFORM_LABELS_FULL[p]}: {r.error}
                    </div>
                  );
                })}
              </>
            )}
          </div>
        )}

        <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
          <button
            onClick={onClose}
            disabled={saving}
            style={{
              flex: 1, height: 46, borderRadius: 12,
              border: "1px solid #e7e5e0", background: "#fff",
              cursor: saving ? "default" : "pointer",
              opacity: saving ? 0.5 : 1,
              fontSize: 14, fontWeight: 500,
              color: "#0e0f0e", fontFamily: FONT,
            }}
          >
            {result ? "Done" : "Cancel"}
          </button>
          {!result && (
            <button
              onClick={doSave}
              disabled={!valid || saving}
              style={{
                flex: 1, height: 46, borderRadius: 12,
                border: "none",
                background: valid && !saving ? "oklch(0.62 0.15 145)" : "#9b9c99",
                cursor: valid && !saving ? "pointer" : "default",
                fontSize: 14, fontWeight: 600, color: "#fff", fontFamily: FONT,
              }}
            >
              {saving ? "Saving…" : "Save"}
            </button>
          )}
        </div>
      </div>
    </>
  );
}

function ConfirmDialog({
  title,
  body,
  confirmLabel,
  destructive,
  onCancel,
  onConfirm,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  destructive?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <>
      <Backdrop onClick={onCancel} />
      <div
        style={{
          position: "fixed", left: 24, right: 24, bottom: "32%",
          background: "#fff", borderRadius: 18,
          padding: "22px 22px",
          boxShadow: "0 12px 40px rgba(14,15,14,0.25)",
          zIndex: 51,
          fontFamily: FONT,
        }}
      >
        <div style={{ fontSize: 17, fontWeight: 600, letterSpacing: "-0.3px", marginBottom: 6 }}>
          {title}
        </div>
        <div style={{ fontSize: 13, color: "#6b6c6a", lineHeight: 1.4, marginBottom: 18 }}>
          {body}
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button
            onClick={onCancel}
            style={{
              flex: 1, height: 46, borderRadius: 12,
              border: "1px solid #e7e5e0", background: "#fff",
              cursor: "pointer", fontSize: 14, fontWeight: 500,
              color: "#0e0f0e", fontFamily: FONT,
            }}
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            style={{
              flex: 1, height: 46, borderRadius: 12,
              border: "none",
              background: destructive ? "#c0392b" : "oklch(0.62 0.15 145)",
              cursor: "pointer",
              fontSize: 14, fontWeight: 600, color: "#fff", fontFamily: FONT,
            }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </>
  );
}

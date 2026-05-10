"use client";

import { useEffect, useState } from "react";
import type { InventoryItem } from "@/types/api";
import {
  BASE,
  deleteListing,
  fetchInventory,
  markAsSold,
  patchListingFields,
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

export default function InventoryScreen({ onBack, onOpenListing, onRelistListing }: Props) {
  const [listings, setListings] = useState<InventoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [actionSheet, setActionSheet] = useState<InventoryItem | null>(null);
  const [priceEdit, setPriceEdit] = useState<InventoryItem | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<InventoryItem | null>(null);

  useEffect(() => {
    fetchInventory()
      .then((res) => setListings(res.items))
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
    } catch {
      // Soft-fail; keep current state.
    }
  }

  async function handleMarkSold(item: InventoryItem) {
    setActionSheet(null);
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
    setActionSheet(null);
    const platforms = getPostedPlatforms(item);
    if (platforms.length === 0) return;
    onRelistListing(item.listing_id, platforms);
  }

  function handleOpen(item: InventoryItem) {
    setActionSheet(null);
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
        {!loading && (
          <span style={{
            marginLeft: "auto",
            fontFamily: '"JetBrains Mono", ui-monospace, monospace',
            fontSize: 11, color: "#9b9c99",
            textTransform: "uppercase", letterSpacing: "1px",
          }}>
            {listings.length} item{listings.length !== 1 ? "s" : ""}
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
          const publishedPlatforms = [
            item.vinted && "vinted",
            item.kleinanzeigen && "kleinanzeigen",
          ].filter(Boolean) as string[];
          const isBusy = busy.has(item.listing_id);
          return (
            <div
              key={item.listing_id}
              style={{
                display: "flex", gap: 14, padding: "16px 0",
                borderBottom: "1px solid #e7e5e0", alignItems: "center",
              }}
            >
              <button
                onClick={() => handleOpen(item)}
                style={{
                  background: "none", border: "none", padding: 0, cursor: "pointer",
                }}
                aria-label="Open listing"
              >
                <img
                  src={`${BASE}${item.thumbnail_url}`}
                  alt={title ?? "listing"}
                  style={{
                    width: 64, height: 64, objectFit: "cover", flexShrink: 0,
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
                <p style={{
                  margin: "0 0 3px", fontSize: 14, fontWeight: 600,
                  letterSpacing: "-0.2px", whiteSpace: "nowrap",
                  overflow: "hidden", textOverflow: "ellipsis",
                }}>
                  {title ?? "Untitled"}
                </p>
                <p style={{ margin: "0 0 6px", fontSize: 12, color: "#6b6c6a" }}>
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

              <div style={{ flexShrink: 0, marginLeft: 8 }}>
                <button
                  onClick={() => setActionSheet(item)}
                  disabled={isBusy}
                  aria-label="More actions"
                  style={{
                    width: 36, height: 36, borderRadius: 18,
                    border: "1px solid #e7e5e0", background: "#fff",
                    cursor: isBusy ? "default" : "pointer",
                    opacity: isBusy ? 0.5 : 1,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    padding: 0,
                  }}
                >
                  {isBusy ? (
                    <span style={{ fontSize: 14, color: "#6b6c6a" }}>…</span>
                  ) : (
                    <svg width="4" height="14" viewBox="0 0 4 14" fill="none">
                      <circle cx="2" cy="2" r="1.6" fill="#0e0f0e" />
                      <circle cx="2" cy="7" r="1.6" fill="#0e0f0e" />
                      <circle cx="2" cy="12" r="1.6" fill="#0e0f0e" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
          );
        })}
      </main>

      {actionSheet && (
        <ActionSheet
          item={actionSheet}
          onClose={() => setActionSheet(null)}
          onOpen={() => handleOpen(actionSheet)}
          onChangePrice={() => {
            setActionSheet(null);
            setPriceEdit(actionSheet);
          }}
          onRelist={() => handleRelist(actionSheet)}
          onMarkSold={() => handleMarkSold(actionSheet)}
          onDelete={() => {
            setActionSheet(null);
            setDeleteConfirm(actionSheet);
          }}
        />
      )}

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

function ActionSheet({
  item,
  onClose,
  onOpen,
  onChangePrice,
  onRelist,
  onMarkSold,
  onDelete,
}: {
  item: InventoryItem;
  onClose: () => void;
  onOpen: () => void;
  onChangePrice: () => void;
  onRelist: () => void;
  onMarkSold: () => void;
  onDelete: () => void;
}) {
  const postedPlatforms = getPostedPlatforms(item);
  const canRelist = postedPlatforms.length > 0;
  return (
    <>
      <Backdrop onClick={onClose} />
      <div
        style={{
          position: "fixed", left: 0, right: 0, bottom: 0,
          background: "#fff", borderTopLeftRadius: 18, borderTopRightRadius: 18,
          padding: "8px 0 calc(20px + env(safe-area-inset-bottom))",
          boxShadow: "0 -8px 24px rgba(14,15,14,0.18)",
          zIndex: 51,
          fontFamily: FONT,
        }}
      >
        <div style={{
          width: 36, height: 4, borderRadius: 2,
          background: "#e7e5e0", margin: "8px auto 14px",
        }} />
        <SheetButton onClick={onOpen}>Open</SheetButton>
        <SheetButton onClick={onChangePrice}>Change price</SheetButton>
        {canRelist && <SheetButton onClick={onRelist}>Relist</SheetButton>}
        <Divider />
        <SheetButton onClick={onMarkSold}>Mark sold</SheetButton>
        <SheetButton onClick={onDelete} destructive>Delete</SheetButton>
      </div>
    </>
  );
}

function SheetButton({
  onClick,
  destructive,
  children,
}: {
  onClick: () => void;
  destructive?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "block", width: "100%",
        padding: "16px 24px", textAlign: "left",
        background: "none", border: "none", cursor: "pointer",
        fontSize: 16, fontWeight: 500,
        color: destructive ? "#c0392b" : "#0e0f0e",
        fontFamily: FONT,
      }}
    >
      {children}
    </button>
  );
}

function Divider() {
  return <div style={{ height: 1, background: "#efece6", margin: "4px 0" }} />;
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

"use client";

import { useEffect, useRef, useState } from "react";
import type { InventoryItem, InventorySummary } from "@/types/api";
import {
  BASE,
  deleteListing,
  fetchInventory,
  fetchInventorySummary,
  markAsSold,
  patchListingFields,
  syncWardrobe,
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

const PLATFORM_LABEL: Record<string, string> = {
  vinted: "Vinted",
  kleinanzeigen: "Kleinanzeigen",
};

const FONT = '"Inter", -apple-system, system-ui, sans-serif';
const MONO = '"JetBrains Mono", ui-monospace, monospace';

// User-facing error messages for /inventory/sync, keyed by HTTP status
// (syncWardrobe throws `sync <status>`).
const SYNC_ERRORS: Record<string, string> = {
  "409": "Connect Vinted to sync live stats.",
  "401": "Vinted session expired — reconnect.",
  "429": "Vinted is rate-limiting — try again shortly.",
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

function getPostedPlatforms(item: InventoryItem): ("vinted" | "kleinanzeigen")[] {
  const out: ("vinted" | "kleinanzeigen")[] = [];
  if (item.vinted?.status === "posted") out.push("vinted");
  if (item.kleinanzeigen?.status === "posted") out.push("kleinanzeigen");
  return out;
}

// ---- filtering & sorting ----

type SortKey = "newest" | "price-desc" | "price-asc" | "views-desc" | "title-asc";
type StatusKey = "all" | "vinted" | "kleinanzeigen" | "unpublished" | "failed";
type Filters = {
  status: StatusKey;
  brands: string[];
  categories: string[];
  priceMin: string;
  priceMax: string;
};
const DEFAULT_FILTERS: Filters = { status: "all", brands: [], categories: [], priceMin: "", priceMax: "" };

const itemPrice = (it: InventoryItem): number | null =>
  (it.prediction?.english_fields?.price_eur as number | undefined) ?? it.prediction?.vinted?.q50 ?? null;
const itemBrand = (it: InventoryItem): string | null =>
  (it.prediction?.english_fields?.brand as string | undefined) ?? null;
const itemCategory = (it: InventoryItem): string | null =>
  (it.prediction?.english_fields?.category as string | undefined) ?? null;
const itemTitle = (it: InventoryItem): string =>
  (it.prediction?.english_fields?.title as string | undefined) ?? "";
const itemViews = (it: InventoryItem): number => it.vinted?.live?.views ?? 0;

function matchesStatus(it: InventoryItem, s: StatusKey): boolean {
  if (s === "all") return true;
  if (s === "vinted") return it.vinted?.status === "posted";
  if (s === "kleinanzeigen") return it.kleinanzeigen?.status === "posted";
  if (s === "failed") return it.vinted?.status === "failed" || it.kleinanzeigen?.status === "failed";
  return !it.vinted && !it.kleinanzeigen; // "unpublished" — no publish attempt
}

function matchesFilters(it: InventoryItem, f: Filters): boolean {
  if (!matchesStatus(it, f.status)) return false;
  if (f.brands.length && !f.brands.includes(itemBrand(it) ?? "")) return false;
  if (f.categories.length && !f.categories.includes(itemCategory(it) ?? "")) return false;
  const p = itemPrice(it);
  const lo = parseFloat(f.priceMin.replace(",", "."));
  const hi = parseFloat(f.priceMax.replace(",", "."));
  if (Number.isFinite(lo) && (p == null || p < lo)) return false;
  if (Number.isFinite(hi) && (p == null || p > hi)) return false;
  return true;
}

const SORTERS: Record<SortKey, (a: InventoryItem, b: InventoryItem) => number> = {
  newest: (a, b) => b.created_at - a.created_at,
  "price-desc": (a, b) => (itemPrice(b) ?? -Infinity) - (itemPrice(a) ?? -Infinity),
  "price-asc": (a, b) => (itemPrice(a) ?? Infinity) - (itemPrice(b) ?? Infinity),
  "views-desc": (a, b) => itemViews(b) - itemViews(a),
  "title-asc": (a, b) => itemTitle(a).localeCompare(itemTitle(b)),
};
const SORT_LABELS: Record<SortKey, string> = {
  newest: "Newest",
  "price-desc": "Price ↓",
  "price-asc": "Price ↑",
  "views-desc": "Most views",
  "title-asc": "A → Z",
};

function toggleInArray(arr: string[], v: string): string[] {
  return arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v];
}

function countActiveFilters(f: Filters): number {
  return (
    (f.status !== "all" ? 1 : 0) +
    (f.brands.length ? 1 : 0) +
    (f.categories.length ? 1 : 0) +
    (f.priceMin || f.priceMax ? 1 : 0)
  );
}

// Sold/removed/expired on Vinted and not actively posted on Kleinanzeigen
// either — i.e. not live on any platform. Such listings drop out of the
// inventory list (the record still exists; it just isn't shown).
function isGoneFromAllPlatforms(it: InventoryItem): boolean {
  return it.vinted?.live?.is_sold_or_removed === true && it.kleinanzeigen?.status !== "posted";
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

// ---- per-card action toolbar (icons) ----

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

const ICON_BTN_VARIANTS = {
  default: { border: "#e7e5e0", bg: "#fff", fg: "#3a3b3a" },
  danger: { border: "#ecc9c4", bg: "#fdf6f5", fg: "#c0392b" },
  off: { border: "#eeece8", bg: "#fafaf8", fg: "#cac8c3" },
} as const;

function IconBtn({
  label, onClick, destructive, disabled, children,
}: {
  label: string;
  onClick: () => void;
  destructive?: boolean;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  const v = ICON_BTN_VARIANTS[disabled ? "off" : destructive ? "danger" : "default"];
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      style={{
        width: 30, height: 30, borderRadius: 8,
        border: `1px solid ${v.border}`,
        background: v.bg,
        color: v.fg,
        cursor: disabled ? "default" : "pointer", flexShrink: 0,
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

// Muted one-liner under the title: inventory totals + the last-sync state.
function SummaryStrip({
  summary, syncMsg, lastSyncedAt,
}: {
  summary: InventorySummary | null;
  syncMsg: string | null;
  lastSyncedAt: number | null;
}) {
  const parts: { text: string; danger?: boolean }[] = [];
  if (summary) {
    const c = summary.counts;
    // Buckets that have cards in the list — they sum to the item count.
    // (sold/removed listings drop out of the list, so they're not shown here.)
    parts.push({ text: `${c.posted} posted` });
    if (c.pending > 0) parts.push({ text: `${c.pending} pending` });
    if (c.unpublished > 0) parts.push({ text: `${c.unpublished} not published` });
    if (c.failed > 0) parts.push({ text: `${c.failed} need attention`, danger: true });
    if (summary.estimated_value_eur > 0) {
      parts.push({ text: `€${Math.round(summary.estimated_value_eur)} est.` });
    }
    if (summary.live_views + summary.live_favourites > 0) {
      parts.push({ text: `${summary.live_views} views` });
      parts.push({ text: `${summary.live_favourites} saved` });
    }
  }
  if (syncMsg) parts.push({ text: syncMsg, danger: true });
  else if (lastSyncedAt != null) parts.push({ text: `synced ${formatSyncedAgo(lastSyncedAt)}` });

  if (parts.length === 0) return null;
  return (
    <div style={{
      marginLeft: 48,
      display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: "2px 6px",
      fontFamily: MONO, fontSize: 11,
    }}>
      {parts.map((p, i) => (
        <span key={i} style={{ color: p.danger ? "#c0392b" : "#9b9c99", whiteSpace: "nowrap" }}>
          {i > 0 && <span style={{ color: "#cfcdc8" }}>· </span>}
          {p.text}
        </span>
      ))}
    </div>
  );
}

// ---- filter / sort bar ----

function ChevronDownIcon() {
  return (
    <svg width="9" height="9" viewBox="0 0 10 10" fill="none" aria-hidden>
      <path d="M2 3.5L5 6.5l3-3" stroke="currentColor" strokeWidth="1.5"
        strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Pill({
  label, selected, onClick, accent = "#3a3b3a",
}: {
  label: React.ReactNode;
  selected: boolean;
  onClick: () => void;
  accent?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        borderRadius: 999,
        padding: "5px 11px",
        fontSize: 12,
        fontWeight: 500,
        cursor: "pointer",
        fontFamily: FONT,
        whiteSpace: "nowrap",
        border: `1px solid ${selected ? `color-mix(in oklch, ${accent} 38%, transparent)` : "#e7e5e0"}`,
        background: selected ? `color-mix(in oklch, ${accent} 11%, transparent)` : "#fff",
        color: selected ? accent : "#6b6c6a",
      }}
    >
      {label}
    </button>
  );
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
      <SmallCaps size={10}>{label}</SmallCaps>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>{children}</div>
    </div>
  );
}

function PriceInput({
  value, placeholder, onChange,
}: {
  value: string;
  placeholder: string;
  onChange: (v: string) => void;
}) {
  return (
    <input
      type="text"
      inputMode="decimal"
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value.replace(/[^\d.,]/g, ""))}
      style={{
        width: 56, height: 28, borderRadius: 8, padding: "0 8px",
        border: "1px solid #e7e5e0", background: "#fff",
        fontSize: 12, fontFamily: MONO, color: "#0e0f0e", outline: "none",
      }}
    />
  );
}

function FilterSortBar({
  sortBy, onSortChange, activeFilterCount, filtersOpen, onToggleFilters, onClear,
}: {
  sortBy: SortKey;
  onSortChange: (s: SortKey) => void;
  activeFilterCount: number;
  filtersOpen: boolean;
  onToggleFilters: () => void;
  onClear: () => void;
}) {
  const filtersActive = activeFilterCount > 0;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "10px 24px",
      borderBottom: filtersOpen ? "none" : "1px solid #e7e5e0",
      backgroundColor: "#fafaf8",
      flexShrink: 0,
    }}>
      <div style={{ position: "relative", flexShrink: 0 }}>
        <select
          value={sortBy}
          onChange={(e) => onSortChange(e.target.value as SortKey)}
          aria-label="Sort listings"
          style={{
            appearance: "none", WebkitAppearance: "none", MozAppearance: "none",
            height: 30, borderRadius: 15, padding: "0 28px 0 11px",
            border: "1px solid #e7e5e0", background: "#fff",
            fontSize: 12, fontWeight: 500, color: "#0e0f0e", fontFamily: FONT,
            cursor: "pointer",
          }}
        >
          {(Object.keys(SORT_LABELS) as SortKey[]).map((k) => (
            <option key={k} value={k}>{`Sort: ${SORT_LABELS[k]}`}</option>
          ))}
        </select>
        <span style={{
          position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)",
          pointerEvents: "none", color: "#9b9c99", display: "inline-flex",
        }}>
          <ChevronDownIcon />
        </span>
      </div>

      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
        {filtersActive && (
          <button type="button" onClick={onClear} style={{
            background: "none", border: "none", cursor: "pointer",
            fontSize: 12, color: "#9b9c99", fontFamily: FONT, padding: "4px 2px",
          }}>
            Clear
          </button>
        )}
        <button type="button" onClick={onToggleFilters} aria-expanded={filtersOpen} style={{
          height: 30, borderRadius: 15, padding: "0 11px",
          display: "inline-flex", alignItems: "center", gap: 6,
          border: `1px solid ${filtersActive ? "oklch(0.62 0.15 145 / 0.4)" : "#e7e5e0"}`,
          background: filtersActive ? "oklch(0.96 0.04 145)" : "#fff",
          color: filtersActive ? "oklch(0.42 0.11 145)" : "#0e0f0e",
          fontSize: 12, fontWeight: 500, fontFamily: FONT, cursor: "pointer",
        }}>
          Filters{filtersActive ? ` · ${activeFilterCount}` : ""}
          <span style={{ display: "inline-flex", transform: filtersOpen ? "rotate(180deg)" : "none" }}>
            <ChevronDownIcon />
          </span>
        </button>
      </div>
    </div>
  );
}

const STATUS_OPTIONS: { key: StatusKey; label: string; accent?: string }[] = [
  { key: "all", label: "All" },
  { key: "vinted", label: "Vinted", accent: PLATFORM_ACCENT.vinted },
  { key: "kleinanzeigen", label: "Kleinanzeigen", accent: PLATFORM_ACCENT.kleinanzeigen },
  { key: "unpublished", label: "Not published" },
  { key: "failed", label: "Failed" },
];

function FilterPanel({
  filters, onChange, availableBrands, availableCategories,
}: {
  filters: Filters;
  onChange: (next: Filters) => void;
  availableBrands: string[];
  availableCategories: string[];
}) {
  const setStatus = (s: StatusKey) =>
    onChange({ ...filters, status: filters.status === s && s !== "all" ? "all" : s });
  return (
    <div style={{
      padding: "12px 24px 14px", borderBottom: "1px solid #e7e5e0",
      backgroundColor: "#fafaf8", display: "flex", flexDirection: "column", gap: 12,
      flexShrink: 0,
    }}>
      <FilterGroup label="Listing place">
        {STATUS_OPTIONS.map((o) => (
          <Pill key={o.key} label={o.label} accent={o.accent}
            selected={filters.status === o.key} onClick={() => setStatus(o.key)} />
        ))}
      </FilterGroup>
      {availableBrands.length >= 2 && (
        <FilterGroup label="Brand">
          {availableBrands.map((b) => (
            <Pill key={b} label={b} selected={filters.brands.includes(b)}
              onClick={() => onChange({ ...filters, brands: toggleInArray(filters.brands, b) })} />
          ))}
        </FilterGroup>
      )}
      {availableCategories.length >= 2 && (
        <FilterGroup label="Category">
          {availableCategories.map((c) => (
            <Pill key={c} label={c} selected={filters.categories.includes(c)}
              onClick={() => onChange({ ...filters, categories: toggleInArray(filters.categories, c) })} />
          ))}
        </FilterGroup>
      )}
      <FilterGroup label="Price (€)">
        <PriceInput value={filters.priceMin} placeholder="min"
          onChange={(v) => onChange({ ...filters, priceMin: v })} />
        <span style={{ color: "#9b9c99", fontSize: 13 }}>–</span>
        <PriceInput value={filters.priceMax} placeholder="max"
          onChange={(v) => onChange({ ...filters, priceMax: v })} />
      </FilterGroup>
    </div>
  );
}

export default function InventoryScreen({ onBack, onOpenListing, onRelistListing }: Props) {
  const [listings, setListings] = useState<InventoryItem[]>([]);
  const [lastSyncedAt, setLastSyncedAt] = useState<number | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [deleteConfirm, setDeleteConfirm] = useState<InventoryItem | null>(null);
  const [summary, setSummary] = useState<InventorySummary | null>(null);
  const [sortBy, setSortBy] = useState<SortKey>("newest");
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [filtersOpen, setFiltersOpen] = useState(false);

  function refetchSummary() {
    fetchInventorySummary().then(setSummary).catch(() => {});
  }

  useEffect(() => {
    fetchInventory()
      .then((res) => {
        setListings(res.items);
        setLastSyncedAt(res.last_synced_at);
      })
      .catch(() => setError("Could not load listings. Is the backend running?"))
      .finally(() => setLoading(false));
    refetchSummary();
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    refetchSummary();
  }

  async function handleSync() {
    setSyncing(true);
    setSyncMsg(null);
    try {
      await syncWardrobe();
      await refetch();
    } catch (e) {
      const status = /\b\d{3}\b/.exec(e instanceof Error ? e.message : "")?.[0] ?? "";
      setSyncMsg(SYNC_ERRORS[status] ?? "Couldn't sync live stats. Try again.");
    } finally {
      setSyncing(false);
    }
  }

  async function handleMarkSold(item: InventoryItem) {
    setBusyState(item.listing_id, true);
    try {
      await markAsSold(item.listing_id);
      setListings((prev) => prev.filter((it) => it.listing_id !== item.listing_id));
      refetchSummary();
    } catch {
      // Surface in card; for now keep silent.
    } finally {
      setBusyState(item.listing_id, false);
    }
  }

  async function handleConfirmDelete(item: InventoryItem) {
    setDeleteConfirm(null);
    setBusyState(item.listing_id, true);
    setSyncMsg(null);
    try {
      const res = await deleteListing(item.listing_id);
      setListings((prev) => prev.filter((it) => it.listing_id !== item.listing_id));
      const failed = Object.entries(res.platforms).filter(([, r]) => r && !r.ok);
      if (failed.length > 0) {
        // The local record is gone, but the listing may still be live there.
        setSyncMsg(
          "Removed from your list, but couldn't delete on " +
            failed.map(([p]) => PLATFORM_LABEL[p] ?? p).join(" & ") +
            " — check those listings manually.",
        );
      }
      refetchSummary();
    } catch {
      // Stay; user can retry.
    } finally {
      setBusyState(item.listing_id, false);
    }
  }

  async function handleSavePrice(item: InventoryItem, newPrice: number) {
    setBusyState(item.listing_id, true);
    try {
      await patchListingFields(item.listing_id, { price_eur: newPrice });
      // Reflect the new price on the card immediately — the patch only
      // touches the price, so there's nothing else to refetch.
      setListings((prev) =>
        prev.map((it) =>
          it.listing_id === item.listing_id && it.prediction
            ? {
                ...it,
                prediction: {
                  ...it.prediction,
                  english_fields: { ...it.prediction.english_fields, price_eur: newPrice },
                },
              }
            : it,
        ),
      );
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

  // Listings no longer live on any platform drop out of the list entirely.
  const listedItems = listings.filter((it) => !isGoneFromAllPlatforms(it));
  const availableBrands = Array.from(
    new Set(listedItems.map(itemBrand).filter(Boolean) as string[]),
  ).sort();
  const availableCategories = Array.from(
    new Set(listedItems.map(itemCategory).filter(Boolean) as string[]),
  ).sort();
  const activeFilterCount = countActiveFilters(filters);
  const visibleListings = listedItems
    .filter((it) => matchesFilters(it, filters))
    .sort(SORTERS[sortBy]);
  const showFilterBar = !loading && !error && listedItems.length > 0;

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
                fontFamily: MONO,
                fontSize: 11, color: "#9b9c99",
                textTransform: "uppercase", letterSpacing: "1px",
              }}>
                {visibleListings.length !== listedItems.length
                  ? `${visibleListings.length} of ${listedItems.length} items`
                  : `${listedItems.length} item${listedItems.length !== 1 ? "s" : ""}`}
              </span>
            )}
          </div>
        </div>
        <SummaryStrip summary={summary} syncMsg={syncMsg} lastSyncedAt={lastSyncedAt} />
      </header>

      {showFilterBar && (
        <>
          <FilterSortBar
            sortBy={sortBy}
            onSortChange={setSortBy}
            activeFilterCount={activeFilterCount}
            filtersOpen={filtersOpen}
            onToggleFilters={() => setFiltersOpen((o) => !o)}
            onClear={() => setFilters(DEFAULT_FILTERS)}
          />
          {filtersOpen && (
            <FilterPanel
              filters={filters}
              onChange={setFilters}
              availableBrands={availableBrands}
              availableCategories={availableCategories}
            />
          )}
        </>
      )}

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

        {!loading && !error && listedItems.length === 0 && (
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

        {!loading && !error && listedItems.length > 0 && visibleListings.length === 0 && (
          <div style={{ marginTop: 60, textAlign: "center" }}>
            <p style={{ fontSize: 14, margin: 0, color: "#6b6c6a" }}>
              No listings match these filters.
            </p>
            <button
              type="button"
              onClick={() => setFilters(DEFAULT_FILTERS)}
              style={{
                marginTop: 8, background: "none", border: "none", cursor: "pointer",
                fontSize: 13, color: "oklch(0.5 0.13 145)", fontFamily: FONT,
              }}
            >
              Clear filters
            </button>
          </div>
        )}

        {visibleListings.map((item) => {
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
                display: "flex", gap: 14, alignItems: "flex-start",
                padding: "16px 0",
                borderBottom: "1px solid #e7e5e0",
              }}
            >
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
                  display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
                  marginBottom: 4,
                }}>
                  <p style={{
                    margin: 0, flex: 1, minWidth: 96, fontSize: 14, fontWeight: 600,
                    letterSpacing: "-0.2px", whiteSpace: "nowrap",
                    overflow: "hidden", textOverflow: "ellipsis",
                  }}>
                    {title ?? "Untitled"}
                  </p>
                  <InlinePrice current={priceVal} onSave={(n) => handleSavePrice(item, n)} />
                  <div
                    onClick={(e) => e.stopPropagation()}
                    style={{
                      display: "flex", gap: 6, marginLeft: 4, flexShrink: 0,
                      cursor: "default",
                      opacity: isBusy ? 0.4 : 1,
                      pointerEvents: isBusy ? "none" : "auto",
                    }}
                  >
                    <IconBtn label="Open" onClick={() => handleOpen(item)}>
                      <OpenIcon />
                    </IconBtn>
                    <IconBtn label="Relist" disabled={!canRelist} onClick={() => handleRelist(item)}>
                      <RelistIcon />
                    </IconBtn>
                    <IconBtn label="Mark sold" onClick={() => handleMarkSold(item)}>
                      <SoldIcon />
                    </IconBtn>
                    <IconBtn label="Delete" destructive onClick={() => setDeleteConfirm(item)}>
                      <TrashIcon />
                    </IconBtn>
                  </div>
                </div>
                <p style={{ margin: "0 0 6px", fontSize: 12, color: "#6b6c6a" }}>
                  {[brand, category].filter(Boolean).join(" · ") || "—"}
                </p>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                  {publishedPlatforms.length > 0 ? (
                    publishedPlatforms.map((p) => <PlatformBadge key={p} platform={p} />)
                  ) : (
                    <SmallCaps size={10}>not published</SmallCaps>
                  )}
                  {item.vinted?.live && !item.vinted.live.is_sold_or_removed && (
                    <span style={{
                      display: "inline-flex", alignItems: "center", gap: 8,
                      fontFamily: MONO,
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
          );
        })}
      </main>

      {deleteConfirm && (
        <ConfirmDialog
          title="Delete this listing?"
          body={
            getPostedPlatforms(deleteConfirm).length > 0
              ? "We'll also try to delete it on the platforms it was posted on."
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

// Inline-editable price shown beside the listing title — tap the number,
// type a new one, Enter / blur to save (Esc to cancel). Saving patches the
// listing and pushes the new price to any live platform listings.
function InlinePrice({
  current,
  onSave,
}: {
  current: number | null;
  onSave: (n: number) => Promise<unknown>;
}) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState(false);
  const doneRef = useRef(false);

  const textStyle: React.CSSProperties = {
    fontFamily: MONO,
    fontSize: 13.5,
    fontWeight: 600,
    letterSpacing: "-0.02em",
  };

  function startEdit(e: React.MouseEvent) {
    e.stopPropagation();
    setVal(current != null ? String(Math.round(current)) : "");
    setErr(false);
    doneRef.current = false;
    setEditing(true);
  }

  async function commit() {
    if (doneRef.current) return;
    doneRef.current = true;
    const n = parseFloat(val.replace(",", "."));
    if (
      !Number.isFinite(n) ||
      n <= 0 ||
      (current != null && Math.round(current) === Math.round(n))
    ) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(n);
      setEditing(false);
    } catch {
      setErr(true);
      doneRef.current = false; // allow retry
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <button
        type="button"
        onClick={startEdit}
        title="Edit price"
        style={{
          ...textStyle,
          flexShrink: 0,
          minWidth: 44,
          textAlign: "right",
          display: "inline-block",
          color: current != null ? "#0e0f0e" : "#9b9c99",
          background: "none",
          border: "none",
          cursor: "pointer",
          padding: 0,
        }}
      >
        {current != null ? `€${Math.round(current)}` : "Set price"}
      </button>
    );
  }

  return (
    <span
      onClick={(e) => e.stopPropagation()}
      style={{
        ...textStyle,
        flexShrink: 0,
        minWidth: 44,
        display: "inline-flex",
        alignItems: "baseline",
        justifyContent: "flex-end",
        color: "#0e0f0e",
      }}
    >
      <span>€</span>
      <input
        autoFocus
        type="text"
        inputMode="decimal"
        value={val}
        disabled={saving}
        onChange={(e) => setVal(e.target.value.replace(/[^\d.,]/g, ""))}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          else if (e.key === "Escape") {
            doneRef.current = true;
            setEditing(false);
          }
        }}
        onBlur={commit}
        style={{
          ...textStyle,
          color: "#0e0f0e",
          width: `${Math.max(1, val.length || 1) + 1.2}ch`,
          minWidth: "2.6ch",
          maxWidth: "7ch",
          border: "none",
          borderBottom: `1.6px solid ${err ? "#c0392b" : "oklch(0.62 0.15 145)"}`,
          outline: "none",
          background: "transparent",
          padding: "0 1px 1px",
          opacity: saving ? 0.5 : 1,
        }}
      />
      {saving && (
        <span style={{ fontSize: 11, color: "#9b9c99", marginLeft: 3 }}>…</span>
      )}
    </span>
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

import type { Platform } from "@/types/api";

// Single source of truth for per-platform display constants — previously copy-
// pasted into every screen component.

export const PLATFORM_LABEL: Record<Platform, string> = {
  vinted: "Vinted",
  kleinanzeigen: "Kleinanzeigen",
};

/** Saturated brand accent — used for text, dots, slider thumbs, badges. */
export const PLATFORM_ACCENT: Record<Platform, string> = {
  vinted: "oklch(0.55 0.08 195)",
  kleinanzeigen: "oklch(0.62 0.13 55)",
};

/** Tinted background for soft fills (badges, cards). */
export const PLATFORM_SOFT: Record<Platform, string> = {
  vinted: "oklch(0.97 0.02 195)",
  kleinanzeigen: "oklch(0.97 0.03 70)",
};

/** Short positioning kicker shown on the platform recommendation card. */
export const PLATFORM_KICKER: Record<Platform, string> = {
  vinted: "EU · fashion",
  kleinanzeigen: "DE · local",
};

"use client";

/**
 * "Marketplaces" strip — where Resell Copilot publishes (Vinted,
 * Kleinanzeigen) and what's on the roadmap (Depop, Vestiaire
 * Collective, tagged "soon"). Live platforms show their app-icon mark
 * (self-hosted in /public/logos, sourced via Brandfetch) + a styled
 * wordmark; roadmap ones are wordmark-only with a "soon" tag. No emoji.
 * Designed to sit on the home (Pick) screen.
 */

const MONO = '"JetBrains Mono", ui-monospace, monospace';
const SERIF = 'Georgia, "Times New Roman", serif';

// Per-brand accent (text + border + glow). Tuned to each platform's real
// mark — Vinted's petrol teal, Kleinanzeigen's leaf green — rather than
// the amber the rest of the app uses for KA badges.
const VINTED = "oklch(0.46 0.075 201)";
const KA = "oklch(0.5 0.135 132)";

const MUTED = "#9b9c99";
const SOON_BG = "#efece6";
const DASH = "#d4d2cd";

type Platform = {
  key: string;
  live: boolean;
  /** brand-coloured wordmark, rendered inside the chip */
  word: React.ReactNode;
  /** path to the self-hosted app-icon mark (live platforms only) */
  logo?: string;
  /** brand accent — text colour, border, glow (live platforms only) */
  color?: string;
};

const PLATFORMS: Platform[] = [
  {
    key: "vinted",
    live: true,
    color: VINTED,
    logo: "/logos/vinted.jpg",
    word: (
      <span style={{ fontWeight: 700, letterSpacing: "-0.4px", fontSize: 14 }}>
        vinted
      </span>
    ),
  },
  {
    key: "kleinanzeigen",
    live: true,
    color: KA,
    logo: "/logos/kleinanzeigen.jpg",
    word: (
      <span style={{ fontWeight: 600, letterSpacing: "-0.15px", fontSize: 13 }}>
        kleinanzeigen
      </span>
    ),
  },
  {
    key: "depop",
    live: false,
    word: (
      <span style={{ fontWeight: 800, letterSpacing: "-0.35px", fontSize: 14 }}>
        Depop
      </span>
    ),
  },
  {
    key: "vestiaire",
    live: false,
    word: (
      <span style={{ fontFamily: SERIF, whiteSpace: "nowrap" }}>
        <span style={{ fontSize: 11, fontWeight: 500, letterSpacing: "1.4px" }}>
          VESTIAIRE
        </span>{" "}
        <span style={{ fontSize: 8, fontWeight: 400, letterSpacing: "1.2px", opacity: 0.78 }}>
          COLLECTIVE
        </span>
      </span>
    ),
  },
];

function LogoMark({ src }: { src: string }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt=""
      width={19}
      height={19}
      style={{
        borderRadius: 5,
        display: "block",
        flexShrink: 0,
        objectFit: "cover",
      }}
    />
  );
}

function Chip({ p }: { p: Platform }) {
  if (p.live) {
    return (
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 7,
          minHeight: 32,
          padding: "0 11px 0 6px",
          borderRadius: 9,
          color: p.color,
          background: "#fff",
          border: `1px solid color-mix(in oklch, ${p.color} 24%, transparent)`,
          boxShadow: `0 1px 7px color-mix(in oklch, ${p.color} 13%, transparent)`,
        }}
      >
        {p.logo && <LogoMark src={p.logo} />}
        {p.word}
      </span>
    );
  }
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 7,
        minHeight: 32,
        padding: "0 7px 0 11px",
        borderRadius: 9,
        color: MUTED,
        background: "#fff",
        border: `1px dashed ${DASH}`,
      }}
    >
      {p.word}
      <span
        style={{
          fontFamily: MONO,
          fontSize: 8.5,
          fontWeight: 700,
          letterSpacing: "0.16em",
          textTransform: "uppercase",
          color: "#8a8b88",
          background: SOON_BG,
          padding: "2px 5px",
          borderRadius: 4,
          lineHeight: 1,
        }}
      >
        soon
      </span>
    </span>
  );
}

export default function SupportedPlatforms() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
      <span
        style={{
          fontFamily: MONO,
          fontSize: 10.5,
          fontWeight: 600,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: MUTED,
        }}
      >
        Marketplaces
      </span>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {PLATFORMS.map((p) => (
          <Chip key={p.key} p={p} />
        ))}
      </div>
    </div>
  );
}

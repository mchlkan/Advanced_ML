"use client";

/**
 * "Marketplaces" strip — shows where Resell Copilot can publish (Vinted,
 * Kleinanzeigen) and what's on the roadmap (Depop, Vestiaire Collective,
 * tagged "soon"). Wordmarks are styled text in each brand's casing/colour
 * — no logo artwork, no emoji. Designed to sit on the home (Pick) screen.
 */

const MONO = '"JetBrains Mono", ui-monospace, monospace';
const SERIF = 'Georgia, "Times New Roman", serif';

// App brand tokens (kept in sync with globals.css @theme).
const VINTED = "oklch(0.5 0.09 196)";
const VINTED_SOFT = "oklch(0.975 0.02 196)";
const KA = "oklch(0.6 0.14 50)";
const KA_SOFT = "oklch(0.975 0.03 65)";

const MUTED = "#9b9c99";
const SOON_BG = "#efece6";
const DASH = "#d4d2cd";

type Platform = {
  key: string;
  live: boolean;
  /** brand-coloured wordmark, rendered inside the chip */
  word: React.ReactNode;
  /** brand text colour + soft tint — only used when live */
  color?: string;
  soft?: string;
};

const PLATFORMS: Platform[] = [
  {
    key: "vinted",
    live: true,
    color: VINTED,
    soft: VINTED_SOFT,
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
    soft: KA_SOFT,
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
      <span style={{ fontFamily: SERIF, color: "inherit", whiteSpace: "nowrap" }}>
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

function Chip({ p }: { p: Platform }) {
  if (p.live) {
    return (
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          minHeight: 30,
          padding: "0 11px",
          borderRadius: 9,
          color: p.color,
          background: p.soft,
          border: `1px solid color-mix(in oklch, ${p.color} 26%, transparent)`,
          boxShadow: `0 1px 7px color-mix(in oklch, ${p.color} 14%, transparent)`,
        }}
      >
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
        minHeight: 30,
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

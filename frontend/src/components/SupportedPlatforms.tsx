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

/** Small "app-icon" mark: a brand-coloured rounded square with a white
 * letterform. A stylized badge in the platform's colour — not the
 * companies' actual logo artwork. Matches the Resell Copilot header
 * mark (a rounded square with a white glyph). */
function IconMark({ bg, glyph }: { bg: string; glyph: React.ReactNode }) {
  return (
    <span
      aria-hidden
      style={{
        width: 17,
        height: 17,
        borderRadius: 5,
        background: bg,
        flexShrink: 0,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        color: "#fff",
        fontWeight: 800,
        fontSize: 11,
        letterSpacing: "-0.02em",
        lineHeight: 1,
        boxShadow: `inset 0 1px 0 rgba(255,255,255,0.22)`,
      }}
    >
      {glyph}
    </span>
  );
}

type Platform = {
  key: string;
  live: boolean;
  /** brand-coloured wordmark, rendered inside the chip */
  word: React.ReactNode;
  /** small app-icon mark, shown before the wordmark */
  logo?: React.ReactNode;
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
    logo: <IconMark bg="oklch(0.49 0.095 197)" glyph="v" />,
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
    logo: <IconMark bg="oklch(0.56 0.155 48)" glyph="k" />,
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
          gap: 7,
          minHeight: 32,
          padding: p.logo ? "0 11px 0 7px" : "0 11px",
          borderRadius: 9,
          color: p.color,
          background: p.soft,
          border: `1px solid color-mix(in oklch, ${p.color} 26%, transparent)`,
          boxShadow: `0 1px 7px color-mix(in oklch, ${p.color} 14%, transparent)`,
        }}
      >
        {p.logo}
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
        padding: p.logo ? "0 7px" : "0 7px 0 11px",
        borderRadius: 9,
        color: MUTED,
        background: "#fff",
        border: `1px dashed ${DASH}`,
      }}
    >
      {p.logo}
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

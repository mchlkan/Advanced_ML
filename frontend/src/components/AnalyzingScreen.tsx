"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  imageUrl: string;
  onCancel: () => void;
}

export default function AnalyzingScreen({ imageUrl, onCancel }: Props) {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());

  useEffect(() => {
    const id = setInterval(() => {
      setElapsed(Date.now() - startRef.current);
    }, 100);
    return () => clearInterval(id);
  }, []);

  const seconds = (elapsed / 1000).toFixed(1);

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
      <header style={{ padding: "20px 24px 0" }}>
        <button
          onClick={onCancel}
          style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontSize: 15, fontWeight: 600, letterSpacing: "-0.3px", color: "var(--color-ink)", minHeight: 44 }}
        >
          Resell Copilot
        </button>
      </header>

      {/* Main */}
      <main
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "0 24px",
          gap: 28,
        }}
      >
        {/* Photo thumbnail */}
        <div
          style={{
            width: 88,
            height: 88,
            overflow: "hidden",
            flexShrink: 0,
            backgroundColor: "var(--color-bg-card)",
          }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={imageUrl}
            alt="Your item"
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        </div>

        {/* Text */}
        <div style={{ textAlign: "center" }}>
          <h2
            style={{
              fontSize: 26,
              fontWeight: 590,
              letterSpacing: "-0.7px",
              margin: "0 0 8px",
            }}
          >
            Analyzing
          </h2>
          <p
            style={{
              fontSize: 15,
              color: "var(--color-ink-secondary)",
              margin: "0 0 6px",
            }}
          >
            Reading your piece…
          </p>
          <p
            style={{
              fontSize: 13,
              color: "var(--color-ink-tertiary)",
              margin: 0,
            }}
          >
            May take up to a minute. Don&apos;t switch apps.
          </p>
        </div>

        {/* Timer */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          {/* Pulsing dot */}
          <span
            style={{
              display: "inline-block",
              width: 7,
              height: 7,
              borderRadius: "50%",
              backgroundColor: "var(--color-accent)",
              animation: "pulse 1.2s ease-in-out infinite",
            }}
          />
          <span
            style={{
              fontSize: 14,
              fontFamily: "var(--font-mono)",
              color: "var(--color-ink-secondary)",
              letterSpacing: "0.5px",
            }}
          >
            {seconds}s
          </span>
        </div>
      </main>

      {/* Cancel */}
      <footer style={{ padding: "0 24px 36px", textAlign: "center" }}>
        <button
          onClick={onCancel}
          style={{
            background: "none",
            border: "none",
            fontSize: 14,
            color: "var(--color-ink-tertiary)",
            cursor: "pointer",
            padding: "12px 24px",
            minHeight: 44,
          }}
        >
          Cancel
        </button>
      </footer>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
}

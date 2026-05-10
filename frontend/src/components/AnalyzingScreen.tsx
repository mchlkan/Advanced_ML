"use client";

import { useEffect, useRef, useState } from "react";
import SmallCaps from "./ui/SmallCaps";

interface Props {
  imageUrl: string;
  labelImageUrl?: string;
  onCancel: () => void;
}

const ACCENT = "oklch(0.62 0.15 145)";

export default function AnalyzingScreen({ imageUrl, labelImageUrl, onCancel }: Props) {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());

  useEffect(() => {
    const id = setInterval(() => {
      const next = Date.now() - startRef.current;
      setElapsed(next);
      if (next > 5000) clearInterval(id);
    }, 100);
    return () => clearInterval(id);
  }, []);

  const elapsedSec = elapsed / 1000;

  function stepState(idx: number): "done" | "active" | "pending" {
    if (idx === 0) return elapsedSec > 2 ? "done" : "active";
    if (idx === 1) return elapsedSec > 5 ? "done" : elapsedSec > 2 ? "active" : "pending";
    return elapsedSec > 5 ? "active" : "pending";
  }

  const steps = [
    { label: "Reading the photo", detail: "VLM · Vision" },
    { label: "Pricing across platforms", detail: "Vinted · Kleinanzeigen" },
    { label: "Drafting your listing", detail: "Title · description" },
  ];

  return (
    <div
      style={{
        height: "100dvh",
        display: "flex",
        flexDirection: "column",
        backgroundColor: "#fafaf8",
        color: "#0e0f0e",
        fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
        boxSizing: "border-box",
      }}
    >
      {/* Photo preview */}
      <div style={{ padding: "20px 20px 0" }}>
        <div
          style={{
            position: "relative",
            borderRadius: 18,
            overflow: "hidden",
            border: "1px solid #e7e5e0",
          }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={imageUrl}
            alt="Your item"
            style={{ width: "100%", height: 260, objectFit: "cover", display: "block" }}
          />
          {/* Gradient overlay */}
          <div
            style={{
              position: "absolute",
              inset: 0,
              background:
                "linear-gradient(180deg, rgba(14,15,14,0) 0%, rgba(14,15,14,0.45) 100%)",
            }}
          />
          {/* Shimmer band */}
          <div
            style={{
              position: "absolute",
              inset: 0,
              background:
                "linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.2) 50%, transparent 100%)",
              mixBlendMode: "overlay",
            }}
          />
          {/* Status badge */}
          <div
            style={{
              position: "absolute",
              left: 16,
              bottom: 14,
              fontSize: 11,
              fontWeight: 600,
              color: "#fff",
              textTransform: "uppercase",
              letterSpacing: "0.12em",
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <div
              style={{
                width: 7,
                height: 7,
                borderRadius: 7,
                background: ACCENT,
                boxShadow: `0 0 0 4px oklch(0.62 0.15 145 / 0.3)`,
                animation: "rcPulse 1.2s ease-in-out infinite",
              }}
            />
            Analyzing
          </div>
          {/* Optional brand/size tag thumbnail */}
          {labelImageUrl && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={labelImageUrl}
              alt="Brand or size tag"
              style={{
                position: "absolute",
                right: 12,
                bottom: 12,
                width: 64,
                height: 64,
                objectFit: "cover",
                borderRadius: 10,
                border: "2px solid #fff",
                boxShadow: "0 2px 8px rgba(0,0,0,0.25)",
              }}
            />
          )}
        </div>
      </div>

      {/* Status text */}
      <div style={{ padding: "32px 24px 0" }}>
        <h2
          style={{
            margin: 0,
            fontSize: 24,
            fontWeight: 600,
            letterSpacing: "-0.6px",
            lineHeight: 1.15,
          }}
        >
          Reading your piece…
        </h2>
        <p style={{ margin: "8px 0 0", fontSize: 14, color: "#6b6c6a", lineHeight: 1.45 }}>
          Usually 3–10 seconds. Don&apos;t switch apps.
        </p>
      </div>

      {/* Steps */}
      <div
        style={{
          padding: "28px 24px 0",
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        {steps.map((s, i) => {
          const state = stepState(i);
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <div
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: 11,
                  flexShrink: 0,
                  background: state === "done" ? ACCENT : "#fff",
                  border:
                    state === "pending"
                      ? "1.5px dashed #e7e5e0"
                      : state === "active"
                      ? `1.5px solid ${ACCENT}`
                      : "none",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                {state === "done" && (
                  <svg width="11" height="11" viewBox="0 0 11 11" fill="none">
                    <path
                      d="M2 5.5l2.2 2.2L9 3"
                      stroke="#fff"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                )}
                {state === "active" && (
                  <div
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: 8,
                      background: ACCENT,
                      animation: "rcPulse 1.2s ease-in-out infinite",
                    }}
                  />
                )}
              </div>
              <div style={{ flex: 1 }}>
                <div
                  style={{
                    fontSize: 15,
                    fontWeight: state === "pending" ? 500 : 600,
                    color: state === "pending" ? "#9b9c99" : "#0e0f0e",
                  }}
                >
                  {s.label}
                </div>
                <SmallCaps style={{ display: "block", marginTop: 2 }}>
                  {s.detail}
                </SmallCaps>
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ flex: 1 }} />

      {/* Cancel */}
      <div style={{ padding: "0 24px 36px" }}>
        <button
          onClick={onCancel}
          style={{
            width: "100%",
            height: 48,
            borderRadius: 14,
            border: "1px solid #e7e5e0",
            cursor: "pointer",
            background: "transparent",
            color: "#6b6c6a",
            fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
            fontSize: 14,
            fontWeight: 500,
          }}
        >
          Cancel
        </button>
      </div>

      <style>{`
        @keyframes rcPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
}

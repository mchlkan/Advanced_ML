"use client";

import { useEffect, useRef, useState } from "react";
import { fetchVlmStatus } from "@/api/vlm";
import type { VlmStatus } from "@/types/api";
import SmallCaps from "./ui/SmallCaps";

interface Props {
  imageUrl: string;
  labelImageUrl?: string;
  onCancel: () => void;
}

const ACCENT = "oklch(0.62 0.15 145)";
const ACCENT_GLOW = "oklch(0.62 0.15 145 / 0.3)";
// Warm ochre — "the GPU is heating up", deliberately not the green "good" tone
// and not an alarming red. Reads as "be patient", not "broken".
const WARMING = "oklch(0.72 0.14 70)";
const WARMING_GLOW = "oklch(0.72 0.14 70 / 0.3)";
const WARMING_SOFT = "oklch(0.975 0.022 75)";
const WARMING_INK = "oklch(0.5 0.1 70)";

type GpuState = "ok" | "warming" | "busy" | "unknown";

function deriveGpuState(s: VlmStatus | null): GpuState {
  if (!s || s.backend !== "runpod_http" || s.error) return "unknown";
  const w = s.workers ?? {};
  const live = (w.ready ?? 0) + (w.running ?? 0);
  if (live > 0) return "ok";
  if (s.throttled || (w.throttled ?? 0) > 0) return "busy";
  // no live worker, not throttled — one is booting (or will be summoned by /run)
  return "warming";
}

const GPU_COPY: Record<"warming" | "busy", { badge: string; kicker: string; line: string }> = {
  warming: {
    badge: "Warming up",
    kicker: "GPU · spinning up",
    line: "First run after a quiet spell — the model server is booting. This usually takes one to three minutes; the photo is safe, just hold on.",
  },
  busy: {
    badge: "Queued",
    kicker: "GPU · queued",
    line: "The model server is behind other work right now. Your photo is in line and will go through — give it a few minutes.",
  },
};

function mmss(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function AnalyzingScreen({ imageUrl, labelImageUrl, onCancel }: Props) {
  const [elapsed, setElapsed] = useState(0);
  const [gpu, setGpu] = useState<GpuState>("unknown");
  const startRef = useRef(Date.now());

  // Elapsed clock, in whole seconds — runs the whole time the screen is up (a
  // cold start can legitimately last minutes). Integer seconds at 1 Hz: that's
  // the granularity of both consumers (the m:ss display and the 2 s/5 s step
  // thresholds), and React skips the re-render when the value is unchanged.
  useEffect(() => {
    const id = setInterval(
      () => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)),
      1000,
    );
    return () => clearInterval(id);
  }, []);

  // Poll the VLM serving status so we can tell the user *why* a slow run is
  // slow (cold boot vs. RunPod throttling us) instead of leaving them staring
  // at a stale "10–20 seconds".
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      const s = await fetchVlmStatus();
      if (!cancelled) setGpu(deriveGpuState(s));
    };
    tick();
    const id = setInterval(tick, 6000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const slow = gpu === "warming" || gpu === "busy";
  const gpuCopy = slow ? GPU_COPY[gpu === "busy" ? "busy" : "warming"] : null;
  const tone = slow ? WARMING : ACCENT;
  const toneGlow = slow ? WARMING_GLOW : ACCENT_GLOW;

  function stepState(idx: number): "done" | "active" | "pending" {
    // While the GPU is cold/queued the pipeline genuinely hasn't started —
    // hold the first step "active" rather than marching all three to done.
    if (slow) return idx === 0 ? "active" : "pending";
    if (idx === 0) return elapsed > 2 ? "done" : "active";
    if (idx === 1) return elapsed > 5 ? "done" : elapsed > 2 ? "active" : "pending";
    return elapsed > 5 ? "active" : "pending";
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
                background: tone,
                boxShadow: `0 0 0 4px ${toneGlow}`,
                animation: "rcPulse 1.2s ease-in-out infinite",
              }}
            />
            {gpuCopy ? gpuCopy.badge : "Analyzing"}
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
          {slow ? "Hang tight — waking the model up" : "Reading your piece…"}
        </h2>
        <p style={{ margin: "8px 0 0", fontSize: 14, color: "#6b6c6a", lineHeight: 1.45 }}>
          {gpuCopy ? gpuCopy.line : "Usually 10–20 seconds. Don’t switch apps."}
        </p>
      </div>

      {/* GPU status card — only when the serving GPU isn't hot */}
      {gpuCopy && (
        <div style={{ padding: "18px 24px 0" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 14,
              padding: "13px 16px",
              borderRadius: 14,
              background: WARMING_SOFT,
              border: `1px solid ${WARMING}`,
            }}
          >
            <div
              style={{
                position: "relative",
                width: 22,
                height: 22,
                flexShrink: 0,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {/* expanding ring */}
              <span
                style={{
                  position: "absolute",
                  inset: 0,
                  borderRadius: 11,
                  border: `1.5px solid ${WARMING}`,
                  animation: "rcRing 1.8s ease-out infinite",
                }}
              />
              <span style={{ width: 8, height: 8, borderRadius: 8, background: WARMING }} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <SmallCaps color={WARMING_INK} style={{ display: "block" }}>
                {gpuCopy.kicker}
              </SmallCaps>
              <div style={{ fontSize: 13, color: "#6b6c6a", marginTop: 3 }}>
                Workers are scaled to zero when idle. They&apos;ll come up — no need to retry.
              </div>
            </div>
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: WARMING_INK,
                fontVariantNumeric: "tabular-nums",
                flexShrink: 0,
              }}
            >
              {mmss(elapsed)}
            </div>
          </div>
        </div>
      )}

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
                      ? `1.5px solid ${tone}`
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
                      background: tone,
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
                  {i === 0 && slow ? "Waiting on the GPU" : s.detail}
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
        @keyframes rcRing {
          0%   { transform: scale(0.6); opacity: 0.9; }
          70%  { transform: scale(1.25); opacity: 0; }
          100% { transform: scale(1.25); opacity: 0; }
        }
      `}</style>
    </div>
  );
}

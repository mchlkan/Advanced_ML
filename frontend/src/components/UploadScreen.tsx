"use client";

import { useRef } from "react";

interface Props {
  onFileSelected: (file: File, imageUrl: string) => void;
  onInventory: () => void;
  error?: string | null;
}

export default function UploadScreen({ onFileSelected, onInventory, error }: Props) {
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const libraryInputRef = useRef<HTMLInputElement>(null);

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    onFileSelected(file, url);
    e.target.value = "";
  }

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
      {/* App header */}
      <header
        style={{
          padding: "20px 24px 0",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <div
          style={{
            width: 22,
            height: 22,
            borderRadius: 6,
            backgroundColor: "oklch(0.62 0.15 145)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <div style={{ width: 8, height: 8, borderRadius: 2, backgroundColor: "#fff" }} />
        </div>
        <span style={{ fontSize: 15, fontWeight: 600, letterSpacing: "-0.2px" }}>
          Resell Copilot
        </span>
        <button
          onClick={onInventory}
          style={{
            marginLeft: "auto",
            background: "none",
            border: "none",
            cursor: "pointer",
            fontSize: 13,
            fontWeight: 500,
            color: "#3a3b3a",
            padding: 0,
            minHeight: 44,
            fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
          }}
        >
          My Listings
        </button>
      </header>

      {/* Hero */}
      <div style={{ padding: "36px 24px 28px" }}>
        <h1
          style={{
            margin: 0,
            fontSize: 34,
            fontWeight: 600,
            letterSpacing: "-1.1px",
            lineHeight: 1.05,
          }}
        >
          Photo&nbsp;→ listing.
          <br />
          <span style={{ color: "#6b6c6a" }}>In seconds.</span>
        </h1>
        <p
          style={{
            margin: "14px 0 0",
            fontSize: 15,
            lineHeight: 1.45,
            color: "#3a3b3a",
            maxWidth: 320,
          }}
        >
          Snap a piece you want to sell. We identify it, price it across Vinted and
          Kleinanzeigen, and draft the listing.
        </p>
      </div>

      {/* Viewfinder zone */}
      <div style={{ padding: "0 20px", flex: 1, display: "flex", flexDirection: "column" }}>
        <div
          style={{
            flex: 1,
            position: "relative",
            background: "#fff",
            border: "1px solid #e7e5e0",
            borderRadius: 18,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            overflow: "hidden",
          }}
        >
          {/* Viewfinder grid */}
          <div
            style={{
              position: "absolute",
              inset: 18,
              backgroundImage: `
                linear-gradient(#efece6 1px, transparent 1px),
                linear-gradient(90deg, #efece6 1px, transparent 1px)
              `,
              backgroundSize: "33.33% 33.33%",
              opacity: 0.7,
            }}
          />

          {/* Helper text */}
          <div
            style={{
              position: "relative",
              zIndex: 1,
              textAlign: "center",
              padding: 20,
            }}
          >
            <div style={{ fontSize: 17, fontWeight: 600, color: "#0e0f0e", marginBottom: 6 }}>
              Center the item
            </div>
            <div
              style={{
                fontSize: 13,
                color: "#6b6c6a",
                maxWidth: 240,
                margin: "0 auto",
                lineHeight: 1.45,
              }}
            >
              Plain background · good light · one piece per photo
            </div>
          </div>
        </div>

        {/* Buttons */}
        <div style={{ padding: "20px 0 16px", display: "flex", flexDirection: "column", gap: 10 }}>
          {error && (
            <p
              style={{
                fontSize: 13,
                color: "#c0392b",
                margin: "0 0 4px",
                padding: "10px 12px",
                backgroundColor: "#fdf0ee",
                borderRadius: 10,
                border: "1px solid #f5c6c0",
              }}
            >
              {error}
            </p>
          )}
          <button
            onClick={() => cameraInputRef.current?.click()}
            style={{
              width: "100%",
              height: 54,
              borderRadius: 14,
              border: "none",
              cursor: "pointer",
              backgroundColor: "oklch(0.62 0.15 145)",
              color: "#fff",
              fontSize: 16,
              fontWeight: 600,
              letterSpacing: "-0.1px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 10,
              boxShadow:
                "0 1px 0 rgba(255,255,255,0.4) inset, 0 4px 12px oklch(0.62 0.15 145 / 0.25)",
              fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
            }}
          >
            <svg width="18" height="18" viewBox="0 0 26 26" fill="none">
              <path
                d="M3 8a2 2 0 012-2h2.5l1.5-2h8l1.5 2H21a2 2 0 012 2v11a2 2 0 01-2 2H5a2 2 0 01-2-2V8z"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinejoin="round"
              />
              <circle cx="13" cy="14" r="4.2" stroke="currentColor" strokeWidth="1.8" />
            </svg>
            Take a photo
          </button>
          <button
            onClick={() => libraryInputRef.current?.click()}
            style={{
              width: "100%",
              height: 50,
              borderRadius: 14,
              border: "1px solid #e7e5e0",
              cursor: "pointer",
              backgroundColor: "#fff",
              color: "#0e0f0e",
              fontSize: 15,
              fontWeight: 500,
              fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
            }}
          >
            Choose from library
          </button>
        </div>
      </div>

      {/* Footer */}
      <div
        style={{
          padding: "0 24px 36px",
          textAlign: "center",
          fontSize: 12,
          color: "#9b9c99",
        }}
      >
        No account · No clutter · You publish on the platform
      </div>

      <input
        ref={cameraInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        onChange={handleFile}
        style={{ position: "absolute", width: 1, height: 1, opacity: 0, overflow: "hidden" }}
      />
      <input
        ref={libraryInputRef}
        type="file"
        accept="image/*"
        onChange={handleFile}
        style={{ position: "absolute", width: 1, height: 1, opacity: 0, overflow: "hidden" }}
      />
    </div>
  );
}

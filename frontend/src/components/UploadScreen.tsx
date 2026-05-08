"use client";

import { useRef } from "react";

interface Props {
  onFileSelected: (file: File, imageUrl: string) => void;
  onInventory: () => void;
}

export default function UploadScreen({ onFileSelected, onInventory }: Props) {
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const libraryInputRef = useRef<HTMLInputElement>(null);

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    onFileSelected(file, url);
    // Reset so selecting the same file again still fires onChange
    e.target.value = "";
  }

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
      <header
        style={{
          padding: "20px 24px 0",
          display: "flex",
          alignItems: "baseline",
          gap: 10,
        }}
      >
        <span style={{ fontSize: 15, fontWeight: 600, letterSpacing: "-0.3px" }}>
          Resell Copilot
        </span>
        <span
          style={{
            fontSize: 11,
            color: "var(--color-ink-tertiary)",
            letterSpacing: "0.4px",
          }}
        >
          v0.1 · demo
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
            color: "var(--color-ink-secondary)",
            padding: 0,
            letterSpacing: "-0.1px",
          }}
        >
          My Listings
        </button>
      </header>

      {/* Main content */}
      <main
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "0 24px",
          gap: 0,
        }}
      >
        {/* Hero */}
        <div style={{ marginBottom: 20 }}>
          <h1
            style={{
              fontSize: 34,
              fontWeight: 590,
              letterSpacing: "-1.2px",
              lineHeight: 1.05,
              margin: 0,
            }}
          >
            Photo → listing.
            <br />
            In seconds.
          </h1>
        </div>

        <p
          style={{
            fontSize: 15,
            color: "var(--color-ink-secondary)",
            lineHeight: 1.5,
            margin: "0 0 36px",
          }}
        >
          Snap a piece you want to sell. We identify it, price it across Vinted
          and Kleinanzeigen, and draft the listing.
        </p>

        {/* Upload zone */}
        <div
          style={{
            backgroundColor: "var(--color-bg-card)",
            padding: "28px 24px",
            marginBottom: 24,
          }}
        >
          {/* Guideline */}
          <p
            style={{
              fontSize: 12,
              color: "var(--color-ink-tertiary)",
              letterSpacing: "0.5px",
              textTransform: "uppercase",
              margin: "0 0 20px",
            }}
          >
            Center the item · plain background · good light · one piece per
            photo
          </p>

          {/* Camera button */}
          <button
            onClick={() => cameraInputRef.current?.click()}
            style={{
              display: "block",
              width: "100%",
              padding: "16px 0",
              backgroundColor: "var(--color-ink)",
              color: "var(--color-bg)",
              fontSize: 15,
              fontWeight: 600,
              letterSpacing: "-0.2px",
              border: "none",
              cursor: "pointer",
              marginBottom: 10,
              minHeight: 52,
            }}
          >
            Take a photo
          </button>

          {/* Library button */}
          <button
            onClick={() => libraryInputRef.current?.click()}
            style={{
              display: "block",
              width: "100%",
              padding: "15px 0",
              backgroundColor: "transparent",
              color: "var(--color-ink)",
              fontSize: 15,
              fontWeight: 500,
              letterSpacing: "-0.2px",
              border: "1.5px solid var(--color-border)",
              cursor: "pointer",
              minHeight: 52,
            }}
          >
            Choose from library
          </button>
        </div>
      </main>

      {/* Footer */}
      <footer
        style={{
          padding: "0 24px 28px",
          textAlign: "center",
        }}
      >
        <p
          style={{
            fontSize: 12,
            color: "var(--color-ink-tertiary)",
            margin: 0,
          }}
        >
          No account · No clutter · You publish on the platform
        </p>
      </footer>

      {/* Visually hidden file inputs — position:absolute avoids the mobile crash
          that display:none triggers when programmatically opening a file picker */}
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

"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  onSubmit: (
    file: File,
    imageUrl: string,
    labelFile?: File,
    labelImageUrl?: string,
  ) => void;
  onInventory: () => void;
  error?: string | null;
}

const ACCENT = "oklch(0.62 0.15 145)";

const HIDDEN_INPUT_STYLE: React.CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  opacity: 0,
  overflow: "hidden",
};

export default function UploadScreen({ onSubmit, onInventory, error }: Props) {
  const mainCameraRef = useRef<HTMLInputElement>(null);
  const mainLibraryRef = useRef<HTMLInputElement>(null);
  const labelCameraRef = useRef<HTMLInputElement>(null);
  const labelLibraryRef = useRef<HTMLInputElement>(null);

  const [mainFile, setMainFile] = useState<File | null>(null);
  const [mainUrl, setMainUrl] = useState<string | null>(null);
  const [labelFile, setLabelFile] = useState<File | null>(null);
  const [labelUrl, setLabelUrl] = useState<string | null>(null);

  // Revoke any object URLs we created when the component unmounts so the
  // browser can release the underlying File-backed memory.
  useEffect(() => {
    return () => {
      if (mainUrl) URL.revokeObjectURL(mainUrl);
      if (labelUrl) URL.revokeObjectURL(labelUrl);
    };
    // We intentionally only revoke on unmount; replace flows revoke inline.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function pickMain(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (mainUrl) URL.revokeObjectURL(mainUrl);
    setMainFile(file);
    setMainUrl(URL.createObjectURL(file));
  }

  function pickLabel(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (labelUrl) URL.revokeObjectURL(labelUrl);
    setLabelFile(file);
    setLabelUrl(URL.createObjectURL(file));
  }

  function clearAll() {
    if (mainUrl) URL.revokeObjectURL(mainUrl);
    if (labelUrl) URL.revokeObjectURL(labelUrl);
    setMainFile(null);
    setMainUrl(null);
    setLabelFile(null);
    setLabelUrl(null);
  }

  function clearLabel() {
    if (labelUrl) URL.revokeObjectURL(labelUrl);
    setLabelFile(null);
    setLabelUrl(null);
  }

  function handleContinue() {
    if (!mainFile || !mainUrl) return;
    onSubmit(mainFile, mainUrl, labelFile ?? undefined, labelUrl ?? undefined);
  }

  const inReview = mainFile !== null && mainUrl !== null;

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
            backgroundColor: ACCENT,
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

      {inReview ? (
        <ReviewPhase
          mainUrl={mainUrl!}
          labelUrl={labelUrl}
          error={error}
          onReplaceMain={() => mainLibraryRef.current?.click()}
          onPickLabelLibrary={() => labelLibraryRef.current?.click()}
          onTakeLabelPhoto={() => labelCameraRef.current?.click()}
          onRemoveLabel={clearLabel}
          onStartOver={clearAll}
          onContinue={handleContinue}
        />
      ) : (
        <PickPhase
          error={error}
          onTakePhoto={() => mainCameraRef.current?.click()}
          onChooseLibrary={() => mainLibraryRef.current?.click()}
        />
      )}

      <input
        ref={mainCameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        onChange={pickMain}
        style={HIDDEN_INPUT_STYLE}
      />
      <input
        ref={mainLibraryRef}
        type="file"
        accept="image/*"
        onChange={pickMain}
        style={HIDDEN_INPUT_STYLE}
      />
      <input
        ref={labelCameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        onChange={pickLabel}
        style={HIDDEN_INPUT_STYLE}
      />
      <input
        ref={labelLibraryRef}
        type="file"
        accept="image/*"
        onChange={pickLabel}
        style={HIDDEN_INPUT_STYLE}
      />
    </div>
  );
}

function PickPhase({
  error,
  onTakePhoto,
  onChooseLibrary,
}: {
  error?: string | null;
  onTakePhoto: () => void;
  onChooseLibrary: () => void;
}) {
  return (
    <>
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
          <div style={{ position: "relative", zIndex: 1, textAlign: "center", padding: 20 }}>
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

        <div style={{ padding: "20px 0 16px", display: "flex", flexDirection: "column", gap: 10 }}>
          {error && <ErrorBanner>{error}</ErrorBanner>}
          <PrimaryButton onClick={onTakePhoto}>
            <CameraIcon />
            Take a photo
          </PrimaryButton>
          <SecondaryButton onClick={onChooseLibrary}>Choose from library</SecondaryButton>
        </div>
      </div>

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
    </>
  );
}

function ReviewPhase({
  mainUrl,
  labelUrl,
  error,
  onReplaceMain,
  onPickLabelLibrary,
  onTakeLabelPhoto,
  onRemoveLabel,
  onStartOver,
  onContinue,
}: {
  mainUrl: string;
  labelUrl: string | null;
  error?: string | null;
  onReplaceMain: () => void;
  onPickLabelLibrary: () => void;
  onTakeLabelPhoto: () => void;
  onRemoveLabel: () => void;
  onStartOver: () => void;
  onContinue: () => void;
}) {
  return (
    <>
      <div style={{ padding: "20px 24px 4px" }}>
        <h1
          style={{
            margin: 0,
            fontSize: 26,
            fontWeight: 600,
            letterSpacing: "-0.7px",
            lineHeight: 1.1,
          }}
        >
          Looks good?
        </h1>
        <p
          style={{
            margin: "8px 0 0",
            fontSize: 14,
            lineHeight: 1.45,
            color: "#6b6c6a",
            maxWidth: 320,
          }}
        >
          Add a brand or size tag photo to boost identification.
        </p>
      </div>

      <div
        style={{
          padding: "16px 20px 0",
          flex: 1,
          display: "flex",
          flexDirection: "column",
          gap: 14,
          overflow: "auto",
        }}
      >
        {/* Main photo preview */}
        <div
          style={{
            position: "relative",
            borderRadius: 18,
            overflow: "hidden",
            border: "1px solid #e7e5e0",
            background: "#fff",
          }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={mainUrl}
            alt="Item preview"
            style={{ width: "100%", height: 240, objectFit: "cover", display: "block" }}
          />
          <button
            onClick={onReplaceMain}
            style={{
              position: "absolute",
              top: 10,
              right: 10,
              padding: "6px 10px",
              borderRadius: 8,
              background: "rgba(14,15,14,0.78)",
              color: "#fff",
              fontSize: 11.5,
              fontWeight: 600,
              border: "none",
              cursor: "pointer",
              backdropFilter: "blur(8px)",
              fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
            }}
          >
            Replace
          </button>
        </div>

        {/* Label slot */}
        <div
          style={{
            borderRadius: 14,
            border: "1px solid #e7e5e0",
            background: "#fff",
            padding: "14px 14px",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: labelUrl ? 12 : 8,
            }}
          >
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: "#0e0f0e" }}>
                Brand / size tag
              </div>
              <div
                style={{
                  fontSize: 12,
                  color: "#6b6c6a",
                  marginTop: 2,
                  lineHeight: 1.4,
                }}
              >
                Optional · improves brand & size accuracy
              </div>
            </div>
            {labelUrl && (
              <button
                onClick={onRemoveLabel}
                style={{
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  fontSize: 12,
                  fontWeight: 500,
                  color: "#9b9c99",
                  padding: 4,
                  minHeight: 32,
                  fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
                }}
              >
                Remove
              </button>
            )}
          </div>
          {labelUrl ? (
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={labelUrl}
                alt="Brand or size tag"
                style={{
                  width: 72,
                  height: 72,
                  objectFit: "cover",
                  borderRadius: 10,
                  border: "1px solid #e7e5e0",
                  flexShrink: 0,
                }}
              />
              <div style={{ display: "flex", flexDirection: "column", gap: 6, flex: 1 }}>
                <button
                  onClick={onTakeLabelPhoto}
                  style={tagActionButtonStyle}
                >
                  Retake
                </button>
                <button
                  onClick={onPickLabelLibrary}
                  style={tagActionButtonStyle}
                >
                  Choose another
                </button>
              </div>
            </div>
          ) : (
            <div style={{ display: "flex", gap: 8 }}>
              <button
                onClick={onTakeLabelPhoto}
                style={{ ...addLabelButtonStyle, flex: 1 }}
              >
                <CameraIcon />
                Take photo
              </button>
              <button
                onClick={onPickLabelLibrary}
                style={{ ...addLabelButtonStyle, flex: 1 }}
              >
                Library
              </button>
            </div>
          )}
        </div>

        {error && <ErrorBanner>{error}</ErrorBanner>}
      </div>

      {/* Sticky CTAs */}
      <div
        style={{
          padding: "14px 20px calc(16px + env(safe-area-inset-bottom))",
          display: "flex",
          flexDirection: "column",
          gap: 10,
          background:
            "linear-gradient(180deg, rgba(250,250,248,0) 0%, rgba(250,250,248,1) 30%)",
          marginTop: -12,
        }}
      >
        <PrimaryButton onClick={onContinue}>
          Continue
          <ArrowIcon />
        </PrimaryButton>
        <button
          onClick={onStartOver}
          style={{
            width: "100%",
            height: 38,
            borderRadius: 10,
            border: "none",
            background: "transparent",
            cursor: "pointer",
            fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
            fontSize: 13,
            fontWeight: 500,
            color: "#6b6c6a",
          }}
        >
          Start over
        </button>
      </div>
    </>
  );
}

const addLabelButtonStyle: React.CSSProperties = {
  height: 50,
  borderRadius: 12,
  border: "1px solid #e7e5e0",
  cursor: "pointer",
  backgroundColor: "#fafaf8",
  color: "#0e0f0e",
  fontSize: 13.5,
  fontWeight: 500,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 8,
  fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
};

const tagActionButtonStyle: React.CSSProperties = {
  height: 32,
  borderRadius: 8,
  border: "1px solid #e7e5e0",
  background: "#fafaf8",
  color: "#3a3b3a",
  fontSize: 12.5,
  fontWeight: 500,
  cursor: "pointer",
  fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
};

function PrimaryButton({
  onClick,
  children,
}: {
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        width: "100%",
        height: 54,
        borderRadius: 14,
        border: "none",
        cursor: "pointer",
        backgroundColor: ACCENT,
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
      {children}
    </button>
  );
}

function SecondaryButton({
  onClick,
  children,
}: {
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
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
      {children}
    </button>
  );
}

function ErrorBanner({ children }: { children: React.ReactNode }) {
  return (
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
      {children}
    </p>
  );
}

function CameraIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 26 26" fill="none">
      <path
        d="M3 8a2 2 0 012-2h2.5l1.5-2h8l1.5 2H21a2 2 0 012 2v11a2 2 0 01-2 2H5a2 2 0 01-2-2V8z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <circle cx="13" cy="14" r="4.2" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path
        d="M3 7h8m0 0L7 3m4 4l-4 4"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

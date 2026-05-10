"use client";

import { useEffect, useState } from "react";
import type { Platform } from "@/types/api";
import { HTTPError, loginVinted } from "@/api/onboarding";

interface Props {
  platform: Platform | null;
  onClose: () => void;
  onSuccess: () => void;
}

const TITLE: Record<Platform, string> = {
  vinted: "Connect Vinted",
  kleinanzeigen: "Connect Kleinanzeigen",
};

function vintedErrorMessage(err: unknown): string {
  if (err instanceof HTTPError) {
    if (err.status === 401) return "Wrong email or password.";
    if (err.status === 429)
      return "Vinted is rate-limiting us. Try again in a few minutes.";
    if (err.status === 503)
      return "Backend is missing seed cookies — admin needs to refresh DataDome.";
    if (err.detail) return `Login failed: ${err.detail}`;
  }
  return "Login failed. Try again.";
}

export default function PlatformLoginModal({ platform, onClose, onSuccess }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset form whenever the modal is opened for a different platform.
  useEffect(() => {
    setEmail("");
    setPassword("");
    setSubmitting(false);
    setError(null);
  }, [platform]);

  if (platform === null) return null;

  // KA flow lands here in a later task — for now show a placeholder.
  const isVinted = platform === "vinted";

  async function handleVintedSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) return;
    setSubmitting(true);
    setError(null);
    try {
      await loginVinted(email.trim(), password);
      onSuccess();
    } catch (err) {
      setError(vintedErrorMessage(err));
      setSubmitting(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(14, 15, 14, 0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        zIndex: 50,
        fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          backgroundColor: "#fafaf8",
          borderRadius: 18,
          width: "min(440px, 100%)",
          padding: 28,
          boxShadow: "0 24px 60px -20px rgba(0,0,0,0.25)",
        }}
      >
        <header
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 18,
          }}
        >
          <h2
            style={{
              margin: 0,
              fontSize: 18,
              fontWeight: 600,
              color: "#0e0f0e",
              letterSpacing: "-0.3px",
            }}
          >
            {TITLE[platform]}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            style={{
              background: "none",
              border: "none",
              fontSize: 22,
              lineHeight: 1,
              color: "#6b6c69",
              cursor: "pointer",
              padding: 4,
            }}
          >
            ×
          </button>
        </header>

        {!isVinted ? (
          <p style={{ fontSize: 13, color: "#6b6c69", lineHeight: 1.5 }}>
            Kleinanzeigen login lands in the next iteration. For now, ask the
            admin to refresh KA out-of-band.
          </p>
        ) : (
          <form
            onSubmit={handleVintedSubmit}
            style={{ display: "flex", flexDirection: "column", gap: 14 }}
          >
            <p
              style={{
                margin: 0,
                fontSize: 13,
                color: "#6b6c69",
                lineHeight: 1.5,
              }}
            >
              Sign in with your Vinted email and password. Used once to refresh
              the session — never stored.
            </p>

            <label
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 6,
                fontSize: 11,
                fontWeight: 600,
                letterSpacing: "0.8px",
                textTransform: "uppercase",
                color: "#6b6c69",
                fontFamily: '"JetBrains Mono", ui-monospace, monospace',
              }}
            >
              Email
              <input
                name="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                autoComplete="username"
                autoFocus
                required
                style={inputStyle(false)}
              />
            </label>

            <label
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 6,
                fontSize: 11,
                fontWeight: 600,
                letterSpacing: "0.8px",
                textTransform: "uppercase",
                color: "#6b6c69",
                fontFamily: '"JetBrains Mono", ui-monospace, monospace',
              }}
            >
              Password
              <input
                name="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                style={inputStyle(false)}
              />
            </label>

            {error && (
              <p
                style={{
                  margin: 0,
                  fontSize: 13,
                  color: "#c0392b",
                  backgroundColor: "#fdf0ee",
                  border: "1px solid #f5c6c0",
                  borderRadius: 10,
                  padding: "10px 12px",
                }}
              >
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={submitting || !email.trim() || !password}
              style={{
                marginTop: 6,
                padding: "12px 14px",
                border: "none",
                borderRadius: 10,
                backgroundColor:
                  submitting || !email.trim() || !password
                    ? "oklch(0.85 0.05 145)"
                    : "oklch(0.62 0.15 145)",
                color: "#fff",
                fontSize: 14,
                fontWeight: 600,
                cursor:
                  submitting || !email.trim() || !password
                    ? "not-allowed"
                    : "pointer",
              }}
            >
              {submitting ? "Signing in…" : "Sign in"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

function inputStyle(hasError: boolean): React.CSSProperties {
  return {
    padding: "10px 12px",
    border: `1.5px solid ${hasError ? "oklch(0.55 0.20 25)" : "#d6d3cc"}`,
    borderRadius: 8,
    fontSize: 14,
    backgroundColor: "#fff",
    outline: "none",
    fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
  };
}

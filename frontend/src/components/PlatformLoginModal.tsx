"use client";

import { useEffect, useState } from "react";
import type { Platform } from "@/types/api";
import {
  HTTPError,
  initiateKaLogin,
  loginKaWithRefreshToken,
  loginVinted,
  verifyKaMfa,
} from "@/api/onboarding";
import SmallCaps from "./ui/SmallCaps";

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

function kaInitiateErrorMessage(err: unknown): string {
  if (err instanceof HTTPError) {
    if (err.status === 401) return "Wrong email or password.";
    if (err.status === 502)
      return "Kleinanzeigen login is being blocked. Try the refresh-token paste fallback.";
    if (err.status === 503) return "Backend not configured for Kleinanzeigen.";
    if (err.detail) return `Login failed: ${err.detail}`;
  }
  return "Login failed. Try again.";
}

function kaMfaErrorMessage(err: unknown): string {
  if (err instanceof HTTPError) {
    if (err.status === 401) return "Invalid or expired SMS code.";
    if (err.status === 502) return "Kleinanzeigen rejected the MFA submission.";
    if (err.detail) return `MFA failed: ${err.detail}`;
  }
  return "MFA failed. Try again.";
}

function kaRefreshErrorMessage(err: unknown): string {
  if (err instanceof HTTPError) {
    if (err.status === 401)
      return "refresh_token rejected — capture a fresh one via mitmproxy.";
    if (err.status === 502) return "Auth0 token endpoint failed.";
    if (err.detail) return `Login failed: ${err.detail}`;
  }
  return "Login failed. Try again.";
}

type KaPhase = "credentials" | "mfa" | "refresh-token";

export default function PlatformLoginModal({ platform, onClose, onSuccess }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // KA-only state
  const [kaPhase, setKaPhase] = useState<KaPhase>("credentials");
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [phoneHint, setPhoneHint] = useState<string>("your phone");
  const [smsCode, setSmsCode] = useState("");
  const [refreshToken, setRefreshToken] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset whenever the modal opens for a different platform.
  useEffect(() => {
    setEmail("");
    setPassword("");
    setKaPhase("credentials");
    setChallengeId(null);
    setPhoneHint("your phone");
    setSmsCode("");
    setRefreshToken("");
    setSubmitting(false);
    setError(null);
  }, [platform]);

  if (platform === null) return null;
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

  async function handleKaCredentialsSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await initiateKaLogin(email.trim(), password);
      if (res.status === "mfa_required" && res.challenge_id) {
        setChallengeId(res.challenge_id);
        setPhoneHint(res.phone_hint ?? "your phone");
        setKaPhase("mfa");
        setSubmitting(false);
      } else {
        // Auth0 skipped MFA — backend already saved the session.
        onSuccess();
      }
    } catch (err) {
      setError(kaInitiateErrorMessage(err));
      setSubmitting(false);
    }
  }

  async function handleKaMfaSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!challengeId || !smsCode.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await verifyKaMfa({
        challenge_id: challengeId,
        sms_code: smsCode.trim(),
        email: email.trim(),
      });
      onSuccess();
    } catch (err) {
      setError(kaMfaErrorMessage(err));
      setSubmitting(false);
    }
  }

  async function handleKaRefreshSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !refreshToken.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await loginKaWithRefreshToken({
        refresh_token: refreshToken.trim(),
        email: email.trim(),
      });
      onSuccess();
    } catch (err) {
      setError(kaRefreshErrorMessage(err));
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
            gap: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
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
            {!isVinted && kaPhase === "mfa" && <SmallCaps>Verify</SmallCaps>}
            {!isVinted && kaPhase === "refresh-token" && <SmallCaps>Fallback</SmallCaps>}
          </div>
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

        {isVinted && (
          <form
            onSubmit={handleVintedSubmit}
            style={{ display: "flex", flexDirection: "column", gap: 14 }}
          >
            <p style={pStyle}>
              Sign in with your Vinted email and password. Used once to refresh
              the session — never stored.
            </p>
            <Field label="Email">
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
            </Field>
            <Field label="Password">
              <input
                name="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                style={inputStyle(false)}
              />
            </Field>
            {error && <ErrorBox message={error} />}
            <SubmitButton
              disabled={submitting || !email.trim() || !password}
              label={submitting ? "Signing in…" : "Sign in"}
            />
          </form>
        )}

        {!isVinted && kaPhase === "credentials" && (
          <form
            onSubmit={handleKaCredentialsSubmit}
            style={{ display: "flex", flexDirection: "column", gap: 14 }}
          >
            <p style={pStyle}>
              Sign in with your Kleinanzeigen email and password. We&apos;ll send
              a one-time SMS code to the maintainer&apos;s phone next.
            </p>
            <Field label="Email">
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
            </Field>
            <Field label="Password">
              <input
                name="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                style={inputStyle(false)}
              />
            </Field>
            {error && <ErrorBox message={error} />}
            <SubmitButton
              disabled={submitting || !email.trim() || !password}
              label={submitting ? "Sending SMS…" : "Continue"}
            />
            <button
              type="button"
              onClick={() => {
                setError(null);
                setKaPhase("refresh-token");
              }}
              style={fallbackLinkStyle}
            >
              Having trouble? Paste a refresh_token instead
            </button>
          </form>
        )}

        {!isVinted && kaPhase === "mfa" && (
          <form
            onSubmit={handleKaMfaSubmit}
            style={{ display: "flex", flexDirection: "column", gap: 14 }}
          >
            <p style={pStyle}>
              SMS code sent to <strong>{phoneHint}</strong>. Enter it below.
              Whoever&apos;s holding the maintainer&apos;s phone needs to share it.
            </p>
            <Field label="SMS code">
              <input
                name="sms_code"
                inputMode="numeric"
                pattern="[0-9]*"
                value={smsCode}
                onChange={(e) => setSmsCode(e.target.value)}
                placeholder="000000"
                autoComplete="one-time-code"
                autoFocus
                required
                style={inputStyle(false)}
              />
            </Field>
            {error && <ErrorBox message={error} />}
            <SubmitButton
              disabled={submitting || !smsCode.trim()}
              label={submitting ? "Verifying…" : "Verify code"}
            />
            <button
              type="button"
              onClick={() => {
                setError(null);
                setSmsCode("");
                setChallengeId(null);
                setKaPhase("credentials");
              }}
              style={fallbackLinkStyle}
            >
              ← Back to credentials
            </button>
          </form>
        )}

        {!isVinted && kaPhase === "refresh-token" && (
          <form
            onSubmit={handleKaRefreshSubmit}
            style={{ display: "flex", flexDirection: "column", gap: 14 }}
          >
            <p style={pStyle}>
              Paste a refresh_token captured from the KA Android app via
              mitmproxy. The backend will exchange it for a working session.
              See <code style={codeStyle}>docs/ka_endpoints.md</code> for
              capture instructions.
            </p>
            <Field label="Email">
              <input
                name="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                autoComplete="username"
                required
                style={inputStyle(false)}
              />
            </Field>
            <Field label="refresh_token">
              <textarea
                name="refresh_token"
                value={refreshToken}
                onChange={(e) => setRefreshToken(e.target.value)}
                rows={3}
                required
                style={{ ...inputStyle(false), resize: "vertical", minHeight: 60 }}
              />
            </Field>
            {error && <ErrorBox message={error} />}
            <SubmitButton
              disabled={submitting || !email.trim() || !refreshToken.trim()}
              label={submitting ? "Submitting…" : "Submit token"}
            />
            <button
              type="button"
              onClick={() => {
                setError(null);
                setKaPhase("credentials");
              }}
              style={fallbackLinkStyle}
            >
              ← Back to email + password
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

const pStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 13,
  color: "#6b6c69",
  lineHeight: 1.5,
};

const codeStyle: React.CSSProperties = {
  fontFamily: '"JetBrains Mono", ui-monospace, monospace',
  fontSize: 12,
  background: "#f0eee8",
  padding: "1px 5px",
  borderRadius: 4,
};

const fallbackLinkStyle: React.CSSProperties = {
  background: "none",
  border: "none",
  padding: 0,
  marginTop: 4,
  fontSize: 12,
  color: "#6b6c69",
  textAlign: "center" as const,
  textDecoration: "underline",
  cursor: "pointer",
  fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <SmallCaps color="#6b6c69">{label}</SmallCaps>
      {children}
    </label>
  );
}

function ErrorBox({ message }: { message: string }) {
  return (
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
      {message}
    </p>
  );
}

function SubmitButton({ disabled, label }: { disabled: boolean; label: string }) {
  return (
    <button
      type="submit"
      disabled={disabled}
      style={{
        marginTop: 6,
        padding: "12px 14px",
        border: "none",
        borderRadius: 10,
        backgroundColor: disabled ? "oklch(0.85 0.05 145)" : "oklch(0.62 0.15 145)",
        color: "#fff",
        fontSize: 14,
        fontWeight: 600,
        cursor: disabled ? "not-allowed" : "pointer",
      }}
    >
      {label}
    </button>
  );
}

function inputStyle(hasError: boolean): React.CSSProperties {
  return {
    padding: "10px 12px",
    border: `1.5px solid ${hasError ? "oklch(0.55 0.20 25)" : "#d6d3cc"}`,
    borderRadius: 8,
    backgroundColor: "#fff",
    outline: "none",
    fontSize: 14,
    fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
  };
}

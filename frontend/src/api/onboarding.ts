import type {
  KleinanzeigenInitiateResponse,
  KleinanzeigenRefreshTokenRequest,
  KleinanzeigenVerifyMfaRequest,
  OnboardingLoginResponse,
  OnboardingStatus,
} from "@/types/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function fetchOnboardingStatus(): Promise<OnboardingStatus> {
  const res = await fetch(`${BASE}/onboarding/status`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Status check failed: ${res.status}`);
  return res.json() as Promise<OnboardingStatus>;
}

// HTTPError carries the backend's status code so the caller can map it to a
// user-friendly message (401 → wrong password, 429 → rate-limited, etc.)
// rather than leaking the raw backend detail string.
export class HTTPError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly detail?: string,
  ) {
    super(message);
    this.name = "HTTPError";
  }
}

async function _post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail: string | undefined;
    try {
      const j = await res.json();
      detail = typeof j?.detail === "string" ? j.detail : undefined;
    } catch {
      // ignore
    }
    throw new HTTPError(`Request failed: ${res.status}`, res.status, detail);
  }
  return res.json() as Promise<T>;
}

export async function loginVinted(
  email: string,
  password: string,
): Promise<OnboardingLoginResponse> {
  return _post<OnboardingLoginResponse>("/onboarding/login", {
    platform: "vinted",
    email,
    password,
  });
}

export async function initiateKaLogin(
  email: string,
  password: string,
): Promise<KleinanzeigenInitiateResponse> {
  return _post<KleinanzeigenInitiateResponse>(
    "/onboarding/kleinanzeigen/initiate",
    { email, password },
  );
}

export async function verifyKaMfa(
  req: KleinanzeigenVerifyMfaRequest,
): Promise<OnboardingLoginResponse> {
  return _post<OnboardingLoginResponse>(
    "/onboarding/kleinanzeigen/verify-mfa",
    req,
  );
}

export async function loginKaWithRefreshToken(
  req: KleinanzeigenRefreshTokenRequest,
): Promise<OnboardingLoginResponse> {
  return _post<OnboardingLoginResponse>("/onboarding/kleinanzeigen", req);
}

"""Kleinanzeigen mobile-API publish client.

Mirrors the structure of backend/integrations/vinted.py: load a session
from disk, refresh tokens transparently when near expiry, post a JAXB-XML
listing body to api.kleinanzeigen.de.

Auth is dual-layered (per docs/ka_endpoints.md):
- Tier-1 ``Authorization: Basic android:TaR60pEttY`` is the foundation
  (same for every install of the KA app)
- Tier-2 ``x-ecg-authorization-user: email=<email>,access=<JWT>`` layered
  on top for user-owned writes

The Tier-2 JWT comes from POST login.kleinanzeigen.de/oauth/token with
grant_type=refresh_token. Refresh tokens are single-use — we persist the
rotated token immediately on each refresh.

Login: two paths supported.
- ``login_with_refresh`` — bootstrap from a captured refresh_token (via
  mitmproxy on a real Android device). Used by /onboarding/kleinanzeigen.
- ``password_login_initiate`` + ``complete_mfa_login`` — full Auth0 PKCE
  flow with email, password, and SMS MFA. Ported from
  vinted-lister/src/kleinanzeigen/session.py and adapted to use the
  mobile OAuth client (so the resulting tokens are compatible with
  refresh_access_token below).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import secrets
import time
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import escape as _saxutils_escape

import httpx

logger = logging.getLogger(__name__)


TIER1_AUTH = "Basic YW5kcm9pZDpUYVI2MHBFdHRZ"   # android:TaR60pEttY
USER_AGENT = "Kleinanzeigen/2026.19.1 (Android 8.0.0; samsung SM-A320FL)"
ECG_USER_AGENT = "ebayk-android-app-2026.19.1"
ECG_USER_VERSION = "2026.19.1"

OAUTH_TOKEN_URL = "https://login.kleinanzeigen.de/oauth/token"
OAUTH_CLIENT_ID = "uV5j90myVPc2XzEOFuWUD2At17OACEGQ"
AUTH0_CLIENT_HEADER = (
    # Same blob the Android app sends; opaque to the server but required
    # ("auth0-client" header).
    "eyJuYW1lIjoiQXV0aDAuQW5kcm9pZCIsImVudiI6eyJhbmRyb2lkIjoiMjYifSwidmVyc2lvbiI6IjMuMTUuMCJ9"
)
AUTH0_BASE = "https://login.kleinanzeigen.de"
ANDROID_REDIRECT_URI = (
    "https://login.kleinanzeigen.de/android/com.ebay.kleinanzeigen/callback"
)
# Browser-shaped UA helps avoid trivially obvious bot rejection by Auth0 +
# its Akamai layer. Kept identical to vinted-lister/src/kleinanzeigen/session.py.
LOGIN_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)

API_BASE = "https://api.kleinanzeigen.de"

# Poster-type values are server-side enums; centralised here so schemas /
# session defaults / XML body all reference one source of truth.
POSTER_TYPE_PRIVATE = "PRIVATE"
POSTER_TYPE_COMMERCIAL = "COMMERCIAL"
PosterType = Literal["PRIVATE", "COMMERCIAL"]


class KAError(RuntimeError):
    """Base for all KA integration failures."""


class KANotConfigured(KAError):
    """Session file missing or unreadable."""


class KAAuthExpired(KAError):
    """Refresh token rejected — maintainer must re-seed via mitmproxy capture."""


@dataclass
class KASession:
    """Persisted KA session. ``imprint`` is required for COMMERCIAL accounts;
    omitted for PRIVATE. ``home_location_id`` is the numeric KA location id
    (e.g. 7615 = "85051 Ingolstadt") shown on every listing."""
    access_token: str
    refresh_token: str
    expires_at: float
    user_id: int
    email: str
    poster_type: PosterType = POSTER_TYPE_PRIVATE
    imprint: str = ""
    contact_name: str = ""
    home_location_id: int | None = None


def load_session(path: str | Path) -> KASession | None:
    p = Path(path).expanduser()
    if not p.exists():
        return None
    with p.open() as f:
        data = json.load(f)
    return KASession(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=float(data["expires_at"]),
        user_id=int(data["user_id"]),
        email=data["email"],
        poster_type=data.get("poster_type", "PRIVATE"),
        imprint=data.get("imprint", ""),
        contact_name=data.get("contact_name", ""),
        home_location_id=data.get("home_location_id"),
    )


def save_session(session: KASession, path: str | Path) -> None:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        json.dump(asdict(session), f, indent=2)


def is_configured() -> bool:
    path = os.environ.get("KA_SESSION_PATH")
    if not path:
        return False
    return Path(path).expanduser().exists()


def _session_path() -> Path:
    path = os.environ.get("KA_SESSION_PATH")
    if not path:
        raise KANotConfigured("KA_SESSION_PATH is not set")
    return Path(path).expanduser()


def try_load_or_refresh() -> tuple["KASession | None", str]:
    """Return (session, state) where state is 'ready' | 'needs_login' | 'not_configured'.
    Attempts a refresh if the loaded session is expired but has a refresh_token.
    Persists the rotated session to disk on successful refresh."""
    if not is_configured():
        return None, "not_configured"
    try:
        session = load_session(_session_path())
    except Exception:
        return None, "not_configured"
    if session is None:
        return None, "not_configured"
    if session.expires_at > time.time():
        return session, "ready"
    if not session.refresh_token:
        return None, "needs_login"
    try:
        refreshed = refresh_access_token(session)
        save_session(refreshed, _session_path())
        return refreshed, "ready"
    except Exception:
        logger.info("KA refresh failed; reporting needs_login", exc_info=True)
        return None, "needs_login"


from ._oauth import decode_jwt_payload as _decode_jwt_payload  # noqa: E402


def refresh_access_token(session: KASession) -> KASession:
    """Mint a fresh access_token via the refresh grant. Returns a new
    session with the rotated refresh_token; **callers must persist immediately**
    because refresh tokens are single-use on KA's Auth0 tenant."""
    headers = {
        "user-agent": "Kleinanzeigen Android 2026.19.1",
        "accept-language": "de_DE",
        "auth0-client": AUTH0_CLIENT_HEADER,
        "content-type": "application/json; charset=utf-8",
    }
    body = {
        "client_id": OAUTH_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": session.refresh_token,
    }
    resp = httpx.post(OAUTH_TOKEN_URL, json=body, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise KAAuthExpired(f"refresh failed: {resp.status_code} — {resp.text[:200]}")
    data = resp.json()
    payload = _decode_jwt_payload(data["access_token"])
    return KASession(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", session.refresh_token),
        expires_at=float(payload.get("exp", time.time() + 3599)),
        user_id=session.user_id,
        email=session.email,
        poster_type=session.poster_type,
        imprint=session.imprint,
        contact_name=session.contact_name,
        home_location_id=session.home_location_id,
    )


def login_with_refresh(
    *,
    refresh_token: str,
    email: str,
    poster_type: PosterType = POSTER_TYPE_PRIVATE,
    imprint: str = "",
    contact_name: str = "",
    home_location_id: int | None = None,
) -> KASession:
    """Bootstrap a KASession from a captured refresh_token. Performs an
    initial refresh round-trip to mint an access_token and decode user_id
    from its payload. Used by /onboarding/kleinanzeigen."""
    seed = KASession(
        access_token="",
        refresh_token=refresh_token,
        expires_at=0.0,
        user_id=0,
        email=email,
        poster_type=poster_type,
        imprint=imprint,
        contact_name=contact_name,
        home_location_id=home_location_id,
    )
    refreshed = refresh_access_token(seed)
    payload = _decode_jwt_payload(refreshed.access_token)
    user_id = payload.get("https://www.kleinanzeigen.de/user_id")
    if not user_id:
        raise KAError(f"could not extract user_id from access_token: {payload}")
    refreshed.user_id = int(user_id)
    return refreshed


# --- Auth0 PKCE login (email + password + SMS MFA) ---
#
# Ported from vinted-lister/src/kleinanzeigen/session.py. Adapted to use the
# mobile OAuth client_id (so the resulting access_token + refresh_token work
# with our refresh_access_token / submit_listing path) instead of lorry's web
# client which lands on cookie-based session auth.

# In-memory state for the multi-step MFA flow. Keyed by an opaque
# challenge_id we hand back to the FE; the FE returns it with the SMS code.
# Single-process FastAPI on EC2 makes this fine; if we ever scale to
# multiple workers this needs to move to Redis or similar.
_KA_LOGIN_CHALLENGES: dict[str, dict] = {}
_KA_LOGIN_CHALLENGE_TTL_S = 300


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) per RFC 7636 §4.2."""
    verifier = secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def _extract_form_state(html: str) -> str | None:
    """Pull <input name='state' value='...'> from an Auth0 form page."""
    m = re.search(r'name="state"\s+value="([^"]+)"', html)
    return m.group(1) if m else None


def _extract_form_error(html: str, fallback: str) -> str:
    """Pull a server-side error blurb from an Auth0 form page."""
    m = re.search(r'class="[^"]*error[^"]*"[^>]*>([^<]+)', html)
    return m.group(1).strip() if m else fallback


def _extract_oauth_code(url: str) -> str | None:
    """If `url` looks like the OAuth callback, return its `code` query param."""
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    codes = qs.get("code")
    return codes[0] if codes else None


def _gc_login_challenges() -> None:
    """Drop login-challenge entries older than the TTL. Runs on every initiate
    + complete call so we don't leak httpx clients."""
    now = time.time()
    expired = [
        k for k, v in _KA_LOGIN_CHALLENGES.items()
        if now - v["created_at"] > _KA_LOGIN_CHALLENGE_TTL_S
    ]
    for k in expired:
        chal = _KA_LOGIN_CHALLENGES.pop(k, None)
        if chal is not None:
            try:
                chal["client"].close()
            except Exception:
                pass


def _exchange_code_for_session(
    *,
    code: str,
    code_verifier: str,
    email: str,
    poster_type: PosterType,
    imprint: str,
    contact_name: str,
    home_location_id: int | None,
) -> KASession:
    """POST /oauth/token with grant_type=authorization_code, build a KASession.
    Mobile client → returns access_token + refresh_token in OAuth response."""
    headers = {
        "user-agent": "Kleinanzeigen Android 2026.19.1",
        "auth0-client": AUTH0_CLIENT_HEADER,
        "content-type": "application/json; charset=utf-8",
    }
    body = {
        "client_id": OAUTH_CLIENT_ID,
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
        "redirect_uri": ANDROID_REDIRECT_URI,
    }
    resp = httpx.post(OAUTH_TOKEN_URL, json=body, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise KAAuthExpired(
            f"OAuth token exchange failed: {resp.status_code} — {resp.text[:200]}"
        )
    data = resp.json()
    payload = _decode_jwt_payload(data["access_token"])
    user_id = payload.get("https://www.kleinanzeigen.de/user_id")
    if not isinstance(user_id, int):
        raise KAError(f"KA access_token missing user_id claim: {payload}")
    return KASession(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", ""),
        expires_at=float(payload.get("exp", time.time() + 3599)),
        user_id=user_id,
        email=email,
        poster_type=poster_type,
        imprint=imprint,
        contact_name=contact_name,
        home_location_id=home_location_id,
    )


def password_login_initiate(email: str, password: str) -> dict:
    """Walk the Auth0 PKCE login chain through the password POST. Three outcomes:

    - MFA required (SMS):
        returns {"status": "mfa_required", "challenge_id": str, "phone_hint": str}
        Call ``complete_mfa_login(challenge_id, sms_code, ...)`` next to finish.

    - Auth0 skipped MFA (rememberBrowser cookie chain):
        returns {"status": "ready", "code": str, "code_verifier": str}
        Caller should immediately ``_exchange_code_for_session(...)`` and
        persist. (In practice the FE always provides the metadata fields
        through the verify-mfa step, so this path is rare and the no-MFA
        session uses defaults.)

    - Bad credentials or upstream error: raises KAAuthExpired / KAError.
    """
    _gc_login_challenges()

    code_verifier, code_challenge = _pkce_pair()
    initial_state = secrets.token_urlsafe(16)

    client = httpx.Client(
        follow_redirects=True,
        timeout=30,
        headers={"user-agent": LOGIN_USER_AGENT},
    )
    # Single close path: only the MFA branch keeps the client open (so
    # complete_mfa_login can reuse it). All other exits (success-no-MFA,
    # auth failure, transport error) go through the finally and close.
    keep_client = False
    try:
        # Step 1: bootstrap the OAuth flow.
        r = client.get(
            f"{AUTH0_BASE}/authorize",
            params={
                "response_type": "code",
                "client_id": OAUTH_CLIENT_ID,
                "redirect_uri": ANDROID_REDIRECT_URI,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "scope": "openid offline_access",
                "state": initial_state,
            },
        )
        if r.status_code != 200:
            raise KAError(f"Auth0 /authorize failed: {r.status_code}")
        state = _extract_form_state(r.text) or initial_state

        # Step 2: submit identifier (email).
        r = client.post(
            f"{AUTH0_BASE}/u/login/identifier",
            params={"state": state},
            data={
                "state": state,
                "username": email,
                "js-available": "true",
                "webauthn-available": "true",
                "is-brave": "false",
                "webauthn-platform-available": "true",
                "action": "default",
            },
        )
        state = _extract_form_state(r.text) or state

        # Step 3: submit password.
        wenkse = re.search(r'name="ulp-wenkse-session-id"\s+value="([^"]+)"', r.text)
        wenkse_id = wenkse.group(1) if wenkse else ""
        r = client.post(
            f"{AUTH0_BASE}/u/login/password",
            params={"state": state},
            data={
                "state": state,
                "username": email,
                "password": password,
                "ulp-wenkse-session-id": wenkse_id,
                "action": "default",
            },
        )

        final_url = str(r.url)

        # Outcome A: MFA challenge.
        if "mfa-sms-challenge" in final_url:
            mfa_state = _extract_form_state(r.text) or state
            phone_match = re.search(
                r'authenticator-selector-text[^>]*>([^<]+)', r.text
            )
            phone_hint = phone_match.group(1).strip() if phone_match else "your phone"
            challenge_id = secrets.token_urlsafe(16)
            _KA_LOGIN_CHALLENGES[challenge_id] = {
                "client": client,
                "code_verifier": code_verifier,
                "state": mfa_state,
                "email": email,
                "created_at": time.time(),
            }
            keep_client = True
            return {
                "status": "mfa_required",
                "challenge_id": challenge_id,
                "phone_hint": phone_hint,
            }

        # Outcome B: skipped MFA — already at the OAuth callback.
        code = _extract_oauth_code(final_url)
        if code:
            return {
                "status": "ready",
                "code": code,
                "code_verifier": code_verifier,
            }

        # Outcome C: failure.
        raise KAAuthExpired(
            f"KA login failed: {_extract_form_error(r.text, 'Login rejected by Auth0')}"
        )
    except KAError:
        raise
    except Exception as exc:
        raise KAError(f"KA login transport error: {exc}") from exc
    finally:
        if not keep_client:
            client.close()


def complete_mfa_login(
    challenge_id: str,
    sms_code: str,
    *,
    email: str,
    poster_type: PosterType = POSTER_TYPE_PRIVATE,
    imprint: str = "",
    contact_name: str = "",
    home_location_id: int | None = None,
) -> KASession:
    """Submit the SMS code to complete an MFA-pending Auth0 login, exchange
    the resulting OAuth code for tokens, return a fully-formed KASession.

    Raises KAAuthExpired on bad / expired SMS code or expired challenge.
    """
    _gc_login_challenges()

    chal = _KA_LOGIN_CHALLENGES.pop(challenge_id, None)
    if chal is None:
        raise KAAuthExpired(
            "MFA challenge expired or unknown. Restart the login flow."
        )

    client: httpx.Client = chal["client"]
    state: str = chal["state"]
    code_verifier: str = chal["code_verifier"]

    try:
        r = client.post(
            f"{AUTH0_BASE}/u/mfa-sms-challenge",
            params={"state": state},
            data={
                "state": state,
                "code": sms_code.strip(),
                "rememberBrowser": "true",
            },
        )
    except Exception as exc:
        client.close()
        raise KAError(f"MFA submission transport error: {exc}") from exc

    final_url = str(r.url)
    if "mfa-sms-challenge" in final_url:
        client.close()
        raise KAAuthExpired(
            f"MFA failed: {_extract_form_error(r.text, 'Invalid or expired SMS code')}"
        )

    code = _extract_oauth_code(final_url)
    client.close()
    if not code:
        raise KAError(
            f"OAuth callback URL has no code after MFA submission: {final_url[:200]}"
        )

    return _exchange_code_for_session(
        code=code,
        code_verifier=code_verifier,
        email=email,
        poster_type=poster_type,
        imprint=imprint,
        contact_name=contact_name,
        home_location_id=home_location_id,
    )


# --- XML body construction ---


def _xml_escape(text: str) -> str:
    """Escape & < > " ' for XML element text + attributes. Stdlib's
    ``saxutils.escape`` handles & < > by default; we extend it for the two
    quote chars so it covers attribute values too."""
    return _saxutils_escape(text, {'"': "&quot;", "'": "&apos;"})


_XML_NS = (
    'xmlns:types="http://www.ebayclassifiedsgroup.com/schema/types/v1" '
    'xmlns:cat="http://www.ebayclassifiedsgroup.com/schema/category/v1" '
    'xmlns:ad="http://www.ebayclassifiedsgroup.com/schema/ad/v1" '
    'xmlns:loc="http://www.ebayclassifiedsgroup.com/schema/location/v1" '
    'xmlns:attr="http://www.ebayclassifiedsgroup.com/schema/attribute/v1" '
    'xmlns:pic="http://www.ebayclassifiedsgroup.com/schema/picture/v1" '
    'xmlns:medias="http://www.ebayclassifiedsgroup.com/schema/media/v1" '
    'xmlns:shipping="http://www.ebayclassifiedsgroup.com/schema/shipping/v1" '
    'xmlns:payment="http://www.ebayclassifiedsgroup.com/schema/payment/v1"'
)


def build_ad_xml(payload: dict, picture_links: list[dict]) -> str:
    """Build the JAXB-XML body for POST /api/users/{user_id}/ads.json.

    `payload` keys (all required unless noted):
      title, description, category_id, location_id, price_eur,
      poster_type ("PRIVATE"|"COMMERCIAL"), contact_name, email,
      imprint (optional, COMMERCIAL only),
      shipping_options (optional list of KA package-preset ids, e.g.
        ["HERMES_001", "HERMES_002", "DHL_001"]) — when the ad declares
        "Versand möglich" KA's submit endpoint rejects an empty
        <shipping:shipping-options> with 400 `shippingOptions`.

    `picture_links` is the list of {href, rel} dicts returned from
    upload_photo() — they're injected verbatim as <pic:link> blocks.
    """
    title = _xml_escape(payload["title"])
    description = _xml_escape(payload["description"])
    contact_name = _xml_escape(payload.get("contact_name", ""))
    email = _xml_escape(payload["email"])
    imprint = _xml_escape(payload.get("imprint", ""))
    poster_type = _xml_escape(payload.get("poster_type", "PRIVATE"))
    category_id = int(payload["category_id"])
    location_id = int(payload["location_id"])
    price = payload["price_eur"]

    pictures_xml = ""
    if picture_links:
        link_xml = "".join(
            f'<pic:link rel="{_xml_escape(lk.get("rel",""))}" href="{_xml_escape(lk.get("href",""))}" />'
            for lk in picture_links
        )
        pictures_xml = f"<pic:pictures><pic:picture>{link_xml}</pic:picture></pic:pictures>"

    attributes_xml = ""
    attrs = payload.get("attributes") or {}
    if attrs:
        items = "".join(
            f'<attr:attribute name="{_xml_escape(name)}"><attr:value>{_xml_escape(value)}</attr:value></attr:attribute>'
            for name, value in attrs.items()
            if value
        )
        attributes_xml = f"<attr:attributes>{items}</attr:attributes>"

    imprint_block = f"<ad:imprint>{imprint}</ad:imprint>" if imprint else ""
    contact_block = f"<ad:contact-name>{contact_name}</ad:contact-name>" if contact_name else ""

    ship_ids = payload.get("shipping_options") or []
    if ship_ids:
        opts = "".join(f'<shipping:shipping-option id="{_xml_escape(str(sid))}" />' for sid in ship_ids)
        shipping_block = f"<shipping:shipping-options>{opts}</shipping:shipping-options>"
    else:
        shipping_block = "<shipping:shipping-options />"

    return (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
        f"<ad:ad {_XML_NS} locale=\"en_US\" id=\"0\">"
        f"<ad:title>{title}</ad:title>"
        f"<ad:description>{description}</ad:description>"
        f"{contact_block}"
        f"{imprint_block}"
        f"<ad:email>{email}</ad:email>"
        f"<ad:poster-type><ad:value>{poster_type}</ad:value></ad:poster-type>"
        f"<ad:ad-type><ad:value>OFFERED</ad:value></ad:ad-type>"
        f'<cat:category id="{category_id}" />'
        f"<loc:locations><loc:location id=\"{location_id}\" /></loc:locations>"
        f"<ad:ad-address />"
        f"<ad:price>"
        f"<types:price-type><types:value>SPECIFIED_AMOUNT</types:value></types:price-type>"
        f"<types:amount>{price}</types:amount>"
        f"</ad:price>"
        f"<medias:medias />"
        f"{pictures_xml}"
        f"{attributes_xml}"
        f"{shipping_block}"
        f'<payment:buy-now selected="false" />'
        f"</ad:ad>"
    )


# --- HTTP client ---


_LOCATION_ID_RE = re.compile(r'/s-anzeige/[^/]+/(\d+)')


class KAClient:
    """Synchronous client for photo upload + listing submit."""

    def __init__(self, session: KASession):
        self.session = session
        self.http = httpx.Client(timeout=30)

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> "KAClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _ensure_fresh(self, margin_s: int = 300) -> None:
        if time.time() < self.session.expires_at - margin_s:
            return
        logger.info("refreshing KA access token (near expiry)")
        self.session = refresh_access_token(self.session)
        # Persist immediately — refresh tokens are single-use on KA's
        # Auth0 tenant, so a downstream failure must not leave the rotated
        # token unsaved.
        try:
            save_session(self.session, _session_path())
        except KANotConfigured:
            pass  # in-memory only path (tests)

    def _tier1_headers(self) -> dict:
        return {
            "user-agent": USER_AGENT,
            "x-ecg-user-agent": ECG_USER_AGENT,
            "x-ecg-user-version": ECG_USER_VERSION,
            "authorization": TIER1_AUTH,
            "accept-encoding": "gzip",
        }

    def _tier2_headers(self) -> dict:
        # Tier 2 = Tier 1 + the user JWT in x-ecg-authorization-user.
        h = self._tier1_headers()
        h["x-ecg-authorization-user"] = f"email={self.session.email},access={self.session.access_token}"
        return h

    def upload_photo(self, file_path: str | Path) -> list[dict]:
        """Returns a list of {href, rel} dicts for every size variant the
        server emitted. The full list goes back into the listing-submit XML."""
        self._ensure_fresh()
        path = Path(file_path)
        with path.open("rb") as f:
            data = f.read()
        suffix = path.suffix.lower().lstrip(".")
        content_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(suffix, "image/jpeg")
        boundary = "0x" + secrets.token_hex(6) + "-" * 32 + "dEaDfA11aC132"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="IMAGE_{secrets.token_hex(8)}.jpg"\r\n'
            f"Content-Type: {content_type}\r\n"
            f"Content-Transfer-Encoding: binary\r\n\r\n"
        ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
        headers = self._tier2_headers() | {"content-type": f"multipart/form-data; boundary={boundary}"}
        resp = self.http.post(f"{API_BASE}/api/pictures.json", content=body, headers=headers, timeout=60)
        if resp.status_code not in (200, 201):
            raise _classify_error(resp, "photo upload")
        body = resp.json()
        # JAXB-JSON envelope: top-level key is the namespaced "picture"
        picture = body.get("{http://www.ebayclassifiedsgroup.com/schema/picture/v1}picture", {}).get("value", {})
        links = picture.get("link", []) or []
        return [{"href": lk.get("href", ""), "rel": lk.get("rel", "")} for lk in links if lk.get("href")]

    def submit_listing(self, ad_xml: str) -> tuple[int, str]:
        self._ensure_fresh()
        headers = self._tier2_headers() | {"content-type": "application/json; charset=utf-8"}
        url = f"{API_BASE}/api/users/{self.session.user_id}/ads.json"
        resp = self.http.post(url, content=ad_xml.encode("utf-8"), headers=headers, timeout=60)
        if resp.status_code not in (200, 201):
            raise _classify_error(resp, "listing submit")

        # Try the Location header first (canonical place for created-resource ID)
        loc = resp.headers.get("location") or resp.headers.get("Location") or ""
        m = _LOCATION_ID_RE.search(loc)
        ad: dict = {}
        if m:
            listing_id = int(m.group(1))
        else:
            # Fall back to scraping the JAXB-JSON response for the listing id
            data = resp.json()
            ad = data.get("{http://www.ebayclassifiedsgroup.com/schema/ad/v1}ad", {}).get("value", {}) or {}
            raw_id = ad.get("id") or ad.get("@id") or ""
            try:
                listing_id = int(raw_id)
            except (TypeError, ValueError):
                listing_id = 0
        if not listing_id:
            raise KAError(
                f"listing submit: no listing id in response "
                f"(Location={loc!r}, body_keys={list(ad.keys()) or None})"
            )
        return listing_id, f"https://www.kleinanzeigen.de/s-anzeige/{listing_id}"

    def update_listing(self, ad_id: int | str, ad_xml: str) -> None:
        """Replace a live ad with the supplied JAXB body. Same body shape
        as ``submit_listing`` (build via ``build_ad_xml``); KA expects a
        full state, not a partial patch."""
        self._ensure_fresh()
        headers = self._tier2_headers() | {"content-type": "application/json; charset=utf-8"}
        url = f"{API_BASE}/api/users/{self.session.user_id}/ads/{ad_id}.json"
        resp = self.http.put(url, content=ad_xml.encode("utf-8"), headers=headers, timeout=60)
        if resp.status_code in (200, 204):
            return
        raise _classify_error(resp, "listing update")

    def delete_listing(self, ad_id: int | str) -> None:
        """Remove a live ad. Returns silently on 200/204/404 (already gone
        is fine)."""
        self._ensure_fresh()
        url = f"{API_BASE}/api/users/{self.session.user_id}/ads/{ad_id}.json"
        resp = self.http.delete(url, headers=self._tier2_headers(), timeout=30)
        if resp.status_code in (200, 204, 404):
            return
        raise _classify_error(resp, "listing delete")

    def get_listing_picture_links(self, ad_id: int | str) -> list[dict]:
        """GET the existing ad and extract its current picture link blocks
        in the shape ``build_ad_xml`` expects. Lets ``update_listing`` keep
        the original photos without re-uploading."""
        self._ensure_fresh()
        url = f"{API_BASE}/api/users/{self.session.user_id}/ads/{ad_id}.json"
        resp = self.http.get(url, headers=self._tier2_headers(), timeout=30)
        if resp.status_code != 200:
            raise _classify_error(resp, "listing fetch (for picture links)")
        body = resp.json()
        ad = (
            body.get("{http://www.ebayclassifiedsgroup.com/schema/ad/v1}ad", {})
            .get("value", {})
            or {}
        )
        pictures = ad.get("pictures", {})
        if isinstance(pictures, dict) and "picture" in pictures:
            entries = pictures["picture"]
            if isinstance(entries, dict):
                entries = [entries]
            out: list[dict] = []
            for pic in entries:
                links = pic.get("link", [])
                if isinstance(links, dict):
                    links = [links]
                for lk in links:
                    href = lk.get("href") or (lk.get("value", {}) if isinstance(lk.get("value"), dict) else None)
                    rel = lk.get("rel") or (lk.get("rel", {}).get("value") if isinstance(lk.get("rel"), dict) else None)
                    # Some fields are wrapped {"value": "..."} JAXB-style
                    if isinstance(href, dict):
                        href = href.get("value")
                    if isinstance(rel, dict):
                        rel = rel.get("value")
                    if href:
                        out.append({"href": href, "rel": rel or ""})
            return out
        return []


def _classify_error(resp: httpx.Response, step: str) -> KAError:
    text = resp.text[:300]
    if resp.status_code == 401:
        return KAAuthExpired(f"{step}: 401 Unauthorized — session likely expired")
    return KAError(f"{step}: HTTP {resp.status_code} — {text}")


# --- public async API for the runner ---


async def publish(image_path: str | Path, payload: dict) -> tuple[int, str]:
    """Publish one listing to Kleinanzeigen. Sync HTTP wrapped in
    asyncio.to_thread so the runner stays async."""
    return await asyncio.to_thread(_publish_sync, image_path, payload)


def _publish_sync(image_path: str | Path, payload: dict) -> tuple[int, str]:
    session = _load_session_or_raise()
    full_payload = _layer_session_defaults(payload, session)
    with KAClient(session) as client:
        picture_links = client.upload_photo(image_path)
        if not picture_links:
            raise KAError("photo upload returned no link blocks")
        ad_xml = build_ad_xml(full_payload, picture_links)
        return client.submit_listing(ad_xml)


async def update_listing(ad_id: int | str, payload: dict) -> None:
    """Push edits to a live KA ad. Same payload shape as ``publish`` —
    KA requires the full state on PUT. Picture links are fetched from the
    live ad so existing photos are preserved without re-upload."""
    return await asyncio.to_thread(_update_sync, ad_id, payload)


def _update_sync(ad_id: int | str, payload: dict) -> None:
    session = _load_session_or_raise()
    full_payload = _layer_session_defaults(payload, session)
    with KAClient(session) as client:
        picture_links = client.get_listing_picture_links(ad_id)
        if not picture_links:
            raise KAError(f"update: ad {ad_id} has no picture links to preserve")
        ad_xml = build_ad_xml(full_payload, picture_links)
        client.update_listing(ad_id, ad_xml)


async def delete_listing(ad_id: int | str) -> None:
    """Remove a live KA ad. Idempotent — already-gone ads return silently."""
    return await asyncio.to_thread(_delete_sync, ad_id)


def _delete_sync(ad_id: int | str) -> None:
    session = _load_session_or_raise()
    with KAClient(session) as client:
        client.delete_listing(ad_id)


def _load_session_or_raise() -> KASession:
    path = _session_path()
    session = load_session(path)
    if session is None:
        raise KANotConfigured(f"no session file at {path}")
    return session


def _layer_session_defaults(payload: dict, session: KASession) -> dict:
    """Layer session-derived defaults onto the payload so to_kleinanzeigen
    only has to populate the variable bits (title/description/etc.)."""
    full_payload = dict(payload)
    full_payload.setdefault("email", session.email)
    full_payload.setdefault("poster_type", session.poster_type)
    if session.imprint and not full_payload.get("imprint"):
        full_payload["imprint"] = session.imprint
    if session.contact_name and not full_payload.get("contact_name"):
        full_payload["contact_name"] = session.contact_name
    if session.home_location_id and not full_payload.get("location_id"):
        full_payload["location_id"] = session.home_location_id
    return full_payload

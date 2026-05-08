"""Vinted publish client — focused port of vinted-lister's mobile + draft path.

Phase 6a slim MVP: only what's needed to publish via the draft→complete flow,
which bypasses DataDome on the protected `/api/v2/item_upload/items`
endpoint.

Maintainer-side bootstrap (one-off):
    cd ~/Projekte/Vinted/vinted-lister
    python -m src.main login --mode password
    # writes session JSON; export VINTED_SESSION_PATH to point at it

Skipped vs vinted-lister: password login, web (Chrome cookie) client,
account creation, search/wallet/edit. All deferred to Phase 6b+.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import secrets
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


_BRAND_ID_CACHE: dict[str, int | None] = {}

DATADOME_SDK_URL = "https://api-sdk.datadome.co/sdk/"
DATADOME_KEY = "E6EAF460AA2A8322D66B42C85B62F9"
DEFAULT_DOMAIN = "www.vinted.fr"


# Hardcoded Galaxy A3 (2017) device fingerprint — matches what vinted-lister's
# initial cookie was extracted against, so the DataDome SDK's trust chain
# stays intact.
DEVICE = {
    "name": "Galaxy A3 (2017)",
    "manufacturer": "samsung",
    "model": "SM-A320FL",
    "device": "a3y17lte",
    "board": "universal7870",
    "hardware": "samsungexynos7870",
    "product": "a3y17ltexc",
    "fingerprint": "samsung/a3y17ltexc/a3y17lte:8.0.0/R16NW/A320FLXXS9CTK1:user/release-keys",
    "os_version": "8.0.0",
    "os_name": "N_MR1",
    "os_sdk": "26",
    "os_build_id": "R16NW",
    "build_tags": "release-keys",
    "build_type": "user",
    "app_version": "26.13.1",
    "app_build": "b261301",
    "screen_width": 720,
    "screen_height": 1280,
    "screen_density": 2.0,
    "screen_dpi": 320,
    "ui_type": "phone",
}


class VintedError(RuntimeError):
    """Base for all Vinted integration failures."""


class VintedNotConfigured(VintedError):
    """Session file missing or unreadable."""


class VintedAuthExpired(VintedError):
    """Refresh token rejected — maintainer must re-login externally."""


class VintedBlocked(VintedError):
    """DataDome 429 or captcha challenge on a protected endpoint."""


@dataclass
class VintedSession:
    access_token: str
    refresh_token: str
    expires_at: float
    datadome_cookie: str
    anon_id: str
    device_uuid: str
    device_token: str
    user_id: str = ""
    session_id: str = ""
    domain: str = DEFAULT_DOMAIN


def load_session(path: str | Path) -> VintedSession | None:
    p = Path(path).expanduser()
    if not p.exists():
        return None
    with p.open() as f:
        data = json.load(f)
    return VintedSession(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=float(data["expires_at"]),
        datadome_cookie=data["datadome_cookie"],
        anon_id=data["anon_id"],
        device_uuid=data["device_uuid"],
        device_token=data["device_token"],
        user_id=data.get("user_id", ""),
        session_id=data.get("session_id", ""),
        domain=data.get("domain", DEFAULT_DOMAIN),
    )


def save_session(session: VintedSession, path: str | Path) -> None:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        json.dump(asdict(session), f, indent=2)


def _ua() -> str:
    return f"vinted-android / fr.vinted v{DEVICE['app_version']} ({DEVICE['app_build']}; {DEVICE['os_version']}; {DEVICE['manufacturer']}; {DEVICE['model']})"


def _refresh_datadome(existing_cookie: str, request_url: str) -> str:
    """Refresh an existing high-trust DataDome cookie via the SDK endpoint.
    Trust chains indefinitely as long as we start from a phone-extracted seed."""
    params = {
        "cid": existing_cookie,
        "ddk": DATADOME_KEY,
        "request": request_url,
        "ua": _ua(),
        "events": json.dumps([{"id": 1, "message": "response validation", "source": "sdk", "date": int(time.time() * 1000)}]),
        "inte": "android-java-okhttp",
        "d_name": DEVICE["name"], "mnf": DEVICE["manufacturer"], "mdl": DEVICE["model"],
        "d_uii": DEVICE["ui_type"], "dev": DEVICE["device"], "d_board": DEVICE["board"],
        "fgp": DEVICE["fingerprint"], "hrd": DEVICE["hardware"], "prd": DEVICE["product"],
        "os": "Android", "osr": DEVICE["os_version"], "osn": DEVICE["os_name"], "osv": DEVICE["os_sdk"],
        "os_bid": DEVICE["os_build_id"], "tgs": DEVICE["build_tags"], "os_btype": DEVICE["build_type"],
        "camera": '{"auth":"false","info":"{}"}',
        "d_n_type": "w", "d_p_idle": "false", "d_p_save": "false",
        "d_s_is_w": str(DEVICE["screen_width"]), "d_s_is_h": str(DEVICE["screen_height"]),
        "screen_d": str(DEVICE["screen_density"]), "d_s_dpi": str(DEVICE["screen_dpi"]),
        "d_or": "portrait", "screen_x": str(DEVICE["screen_width"]), "screen_y": str(DEVICE["screen_height"]),
        "d_s_mrr": "59", "d_s_n": "Integrierter Bildschirm", "d_s_hdr": "false", "d_s_br": "0.5",
        "a_debuggable": "false", "a_debugger": "false", "a_debug": "false",
        "ddv": "1.15.3", "ddvv": DEVICE["app_version"],
        "r_up": str(int(time.time() * 1000) % 1000000),
        "d_b_state": "charging", "d_b_c": "0", "d_b_lvl": "72", "d_b_e": "0",
    }
    resp = httpx.post(
        DATADOME_SDK_URL,
        data=params,
        headers={"user-agent": "okhttp/5.3.2", "content-type": "application/x-www-form-urlencoded"},
        timeout=20,
    )
    cookie_str = resp.json().get("cookie", "")
    if "datadome=" in cookie_str:
        return cookie_str.split("datadome=")[1].split(";")[0]
    return existing_cookie


from ._oauth import decode_jwt_payload as _decode_jwt_payload  # noqa: E402


def _pre_auth_headers(seed: dict, dd_cookie: str) -> dict:
    """Mobile headers for endpoints called *before* we have an access token —
    OAuth password / refresh grants. No Authorization, no x-v-uid/sid."""
    return {
        "user-agent": _ua(),
        "x-anon-id": seed["anon_id"],
        "x-device-uuid": seed["device_uuid"],
        "x-v-udt": seed["device_token"],
        "x-platform": "android",
        "x-portal": "fr",
        "x-app-version": DEVICE["app_version"],
        "x-os-version": DEVICE["os_version"],
        "x-device-model": f"{DEVICE['manufacturer'].title()} {DEVICE['model']}",
        "x-screen-width": str(DEVICE["screen_width"]),
        "x-screen-height": str(DEVICE["screen_height"]),
        "x-local-time": str(int(time.time() * 1000)),
        "accept-language": "de-fr",
        "locale": "de-DE",
        "cookie": f"datadome={dd_cookie}",
    }


def password_login(
    *,
    email: str,
    password: str,
    seed: dict,
    domain: str = DEFAULT_DOMAIN,
) -> VintedSession:
    """OAuth password grant against /oauth/token.

    `seed` must include the four phone-extracted fields ``datadome_cookie``,
    ``anon_id``, ``device_uuid``, ``device_token``. The DataDome cookie is
    refreshed via the SDK before the request to maximise trust score.

    The seed values come from a one-time ADB extraction — see vinted-lister's
    ``extract-cookie`` CLI. Without a high-trust DD cookie, /oauth/token
    returns a DataDome challenge.
    """
    for key in ("datadome_cookie", "anon_id", "device_uuid", "device_token"):
        if not seed.get(key):
            raise VintedNotConfigured(f"missing seed field: {key}")

    base_url = f"https://{domain}"
    dd_cookie = _refresh_datadome(seed["datadome_cookie"], f"{base_url}/oauth/token")
    headers = _pre_auth_headers(seed, dd_cookie) | {"content-type": "application/x-www-form-urlencoded"}
    resp = httpx.post(
        f"{base_url}/oauth/token",
        data={
            "grant_type": "password",
            "client_id": "android",
            "scope": "user",
            "username": email,
            "password": password,
        },
        headers=headers,
        timeout=30,
    )
    body_preview = resp.text[:200]
    if resp.status_code != 200:
        if "captcha" in body_preview.lower() or "datadome" in body_preview.lower():
            raise VintedBlocked(f"password login: DataDome blocked at status {resp.status_code}")
        raise VintedAuthExpired(f"password login: {resp.status_code} — {body_preview}")

    dd_cookie = _extract_dd(resp, dd_cookie)
    data = resp.json()
    payload = _decode_jwt_payload(data["access_token"])
    return VintedSession(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", ""),
        expires_at=float(payload.get("exp", time.time() + 3599)),
        datadome_cookie=dd_cookie,
        anon_id=seed["anon_id"],
        device_uuid=seed["device_uuid"],
        device_token=seed["device_token"],
        user_id=payload.get("sub", ""),
        session_id=payload.get("sid", ""),
        domain=domain,
    )


def refresh_access_token(session: VintedSession) -> VintedSession:
    """Mint a new access token via the refresh grant. No password / phone needed."""
    base_url = f"https://{session.domain}"
    dd_cookie = _refresh_datadome(session.datadome_cookie, f"{base_url}/oauth/token")
    headers = _mobile_headers(session, dd_cookie) | {"content-type": "application/x-www-form-urlencoded"}
    resp = httpx.post(
        f"{base_url}/oauth/token",
        data={"grant_type": "refresh_token", "client_id": "android", "refresh_token": session.refresh_token},
        headers=headers,
        timeout=30,
    )
    if resp.status_code != 200:
        raise VintedAuthExpired(f"refresh failed: {resp.status_code} — {resp.text[:200]}")
    data = resp.json()
    payload = _decode_jwt_payload(data["access_token"])
    return VintedSession(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", session.refresh_token),
        expires_at=float(payload.get("exp", time.time() + 3599)),
        datadome_cookie=_extract_dd(resp, dd_cookie),
        anon_id=session.anon_id,
        device_uuid=session.device_uuid,
        device_token=session.device_token,
        user_id=payload.get("sub", session.user_id),
        session_id=payload.get("sid", session.session_id),
        domain=session.domain,
    )


def _mobile_headers(session: VintedSession, dd_cookie: str | None = None) -> dict:
    cookie = dd_cookie or session.datadome_cookie
    return {
        "user-agent": _ua(),
        "x-anon-id": session.anon_id,
        "x-device-uuid": session.device_uuid,
        "x-v-udt": session.device_token,
        "x-platform": "android",
        "x-portal": "fr",
        "x-app-version": DEVICE["app_version"],
        "x-os-version": DEVICE["os_version"],
        "x-device-model": f"{DEVICE['manufacturer'].title()} {DEVICE['model']}",
        "x-screen-width": str(DEVICE["screen_width"]),
        "x-screen-height": str(DEVICE["screen_height"]),
        "x-local-time": str(int(time.time() * 1000)),
        "accept-language": "de-fr",
        "locale": "de-DE",
        "authorization": f"Bearer {session.access_token}",
        "cookie": f"datadome={cookie}",
        "x-v-uid": session.user_id,
        "x-v-sid": session.session_id,
    }


def _extract_dd(resp: httpx.Response, fallback: str) -> str:
    for val in resp.headers.get("set-cookie", "").split(","):
        if "datadome=" in val:
            return val.split("datadome=")[1].split(";")[0]
    return fallback


class VintedClient:
    """Synchronous client for the draft-mode listing flow.

    Mutates `self.session.datadome_cookie` as the server rotates it across
    requests; callers should `save_session(...)` after a publish to persist
    the refreshed cookie for the next call.
    """

    def __init__(self, session: VintedSession):
        self.session = session
        self.base_url = f"https://{session.domain}"
        self.http = httpx.Client()

    def _ensure_fresh(self, margin_s: int = 300) -> None:
        if time.time() < self.session.expires_at - margin_s:
            return
        logger.info("refreshing Vinted access token (near expiry)")
        self.session = refresh_access_token(self.session)
        # Persist immediately. Refresh tokens are single-use — if we waited
        # until after a successful publish and the publish failed, the next
        # request would try to refresh with the now-revoked old token and
        # get 401 invalid_grant. Save now so the new refresh_token is on
        # disk regardless of what happens downstream.
        try:
            save_session(self.session, _session_path())
        except VintedNotConfigured:
            pass  # in-memory only path (e.g. tests)

    def _post(self, path: str, *, json_body: Any = None, data: Any = None, extra_headers: dict | None = None, timeout: int = 30) -> httpx.Response:
        headers = _mobile_headers(self.session)
        if extra_headers:
            headers.update(extra_headers)
        resp = self.http.post(f"{self.base_url}{path}", json=json_body, data=data, headers=headers, timeout=timeout)
        self.session.datadome_cookie = _extract_dd(resp, self.session.datadome_cookie)
        return resp

    def _put(self, path: str, *, json_body: Any, timeout: int = 30) -> httpx.Response:
        headers = _mobile_headers(self.session) | {"content-type": "application/json; charset=UTF-8"}
        resp = self.http.put(f"{self.base_url}{path}", json=json_body, headers=headers, timeout=timeout)
        self.session.datadome_cookie = _extract_dd(resp, self.session.datadome_cookie)
        return resp

    def _get(self, path: str, *, timeout: int = 30) -> httpx.Response:
        resp = self.http.get(f"{self.base_url}{path}", headers=_mobile_headers(self.session), timeout=timeout)
        self.session.datadome_cookie = _extract_dd(resp, self.session.datadome_cookie)
        return resp

    def get_wardrobe(self, *, per_page: int = 100, max_pages: int = 20) -> list[dict]:
        """Fetch all active items in the logged-in user's wardrobe via
        GET /api/v2/wardrobe/{user_id}/items. Paginates until an empty page
        or `max_pages` is hit. Returns the raw API item dicts."""
        self._ensure_fresh()
        user_id = self.session.user_id
        if not user_id:
            raise VintedAuthExpired("session has no user_id; re-login required")
        items: list[dict] = []
        for page in range(1, max_pages + 1):
            resp = self._get(
                f"/api/v2/wardrobe/{user_id}/items"
                f"?page={page}&per_page={per_page}&order=created_at_desc"
            )
            if resp.status_code != 200:
                raise _classify_error(resp, "wardrobe fetch")
            page_items = resp.json().get("items", []) or []
            if not page_items:
                break
            items.extend(page_items)
            if len(page_items) < per_page:
                break
        return items

    def delete_draft(self, item_id: int | str) -> None:
        """Delete a Vinted listing or draft. Same endpoint works for both
        published listings and unpublished drafts. Raises VintedError on any
        non-2xx response so callers can surface a meaningful failure."""
        self._ensure_fresh()
        resp = self.http.delete(
            f"{self.base_url}/api/v2/item_upload/drafts/{item_id}",
            headers=_mobile_headers(self.session),
            timeout=30,
        )
        self.session.datadome_cookie = _extract_dd(resp, self.session.datadome_cookie)
        if resp.status_code in (200, 204):
            return
        if resp.status_code == 404:
            raise VintedError(f"delete: item {item_id} not found")
        raise _classify_error(resp, "delete")

    def resolve_brand_id(self, brand: str) -> int | None:
        """Top hit from /api/v2/item_upload/brands?keyword=, cached per process.
        Returns None for blank input or no match — callers fall back to free-text
        brand, which Vinted accepts but doesn't link to the brand page."""
        if not brand or not brand.strip():
            return None
        key = brand.strip().lower()
        if key in _BRAND_ID_CACHE:
            return _BRAND_ID_CACHE[key]
        self._ensure_fresh()
        from urllib.parse import quote
        resp = self._get(f"/api/v2/item_upload/brands?keyword={quote(brand.strip())}")
        if resp.status_code != 200:
            return None
        brands = resp.json().get("brands", [])
        # Prefer an exact case-insensitive title match, otherwise top hit.
        for b in brands:
            if b.get("title", "").strip().lower() == key:
                _BRAND_ID_CACHE[key] = int(b["id"])
                return _BRAND_ID_CACHE[key]
        if brands:
            _BRAND_ID_CACHE[key] = int(brands[0]["id"])
            return _BRAND_ID_CACHE[key]
        _BRAND_ID_CACHE[key] = None
        return None

    def upload_photo(self, file_path: str | Path) -> int:
        self._ensure_fresh()
        path = Path(file_path)
        with path.open("rb") as f:
            photo_data = f.read()
        suffix = path.suffix.lower()
        content_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(suffix.lstrip("."), "image/jpeg")
        boundary = "----WebKitFormBoundary" + secrets.token_hex(8)
        temp_uuid = str(uuid.uuid4())
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="photo[type]"\r\n\r\nitem\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="photo[file]"; filename="{path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode() + photo_data + (
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="photo[temp_uuid]"\r\n\r\n'
            f"{temp_uuid}\r\n--{boundary}--\r\n"
        ).encode()
        resp = self._post(
            "/api/v2/photos",
            data=body,
            extra_headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        )
        if resp.status_code != 200:
            raise VintedError(f"photo upload failed: {resp.status_code} — {resp.text[:200]}")
        return int(resp.json()["id"])

    def submit_listing_via_draft(self, payload: dict, photo_ids: list[int]) -> tuple[int, str]:
        """Three-step draft flow that bypasses DataDome on the submission path:
            1. POST /drafts                              create empty draft
            2. PUT  /drafts/{id}                         attach full payload
            3. POST /drafts/{id}/completion              publish

        Returns (item_id, listing_url).
        """
        self._ensure_fresh()
        headers_json = {"content-type": "application/json; charset=UTF-8"}

        # Step 1: create draft
        resp = self._post(
            "/api/v2/item_upload/drafts",
            json_body={"draft": {"title": payload["title"]}},
            extra_headers=headers_json,
        )
        if resp.status_code != 200:
            raise _classify_error(resp, "draft create")
        draft_id = resp.json()["draft"]["id"]

        # Step 2: attach payload
        full = _build_item_payload(payload, photo_ids)
        resp = self._put(f"/api/v2/item_upload/drafts/{draft_id}", json_body={"draft": full})
        if resp.status_code != 200:
            raise _classify_error(resp, "draft update")

        # Read back to grab server-side photo ids
        resp = self._get(f"/api/v2/items/{draft_id}/details")
        server_photo_ids: list[str] = []
        if resp.status_code == 200:
            for p in resp.json().get("item", {}).get("photos", []):
                server_photo_ids.append(str(p["id"]))

        # Step 3: complete (publish)
        complete = dict(full)
        if server_photo_ids:
            complete["assigned_photos"] = [{"id": pid, "orientation": 0} for pid in server_photo_ids]
        resp = self._post(
            f"/api/v2/item_upload/drafts/{draft_id}/completion",
            json_body={"draft": complete, "upload_session_id": str(uuid.uuid4()), "push_up": False},
            extra_headers={
                "content-type": "application/json; charset=UTF-8",
                "x-upload-form": "true",
                "x-enable-dynamic-attribute-condition": "true",
                "x-enable-dynamic-attribute-video-game-rating": "true",
            },
        )
        if resp.status_code != 200:
            raise _classify_error(resp, "draft complete")

        body = resp.json()
        item_id = int(body.get("item", body.get("draft", {})).get("id", draft_id))
        listing_url = f"{self.base_url}/items/{item_id}"
        return item_id, listing_url


def _classify_error(resp: httpx.Response, step: str) -> VintedError:
    text = resp.text[:300]
    if resp.status_code in (403, 429) and ("captcha" in text.lower() or "datadome" in text.lower()):
        return VintedBlocked(f"{step}: DataDome blocked at status {resp.status_code}")
    if resp.status_code == 401:
        return VintedAuthExpired(f"{step}: 401 Unauthorized — session likely expired")
    return VintedError(f"{step}: HTTP {resp.status_code} — {text}")


def _build_item_payload(p: dict, photo_ids: list[int]) -> dict:
    """Map our hardened canon English fields to the Vinted item-payload shape.
    `p` keys: title, description, price_eur, catalog_id, condition_id,
    optional brand, size, color_ids, etc. Caller ensures catalog_id and
    condition_id are present (see src/listing_mappings.py:to_vinted)."""
    return {
        "title": p["title"],
        "description": p["description"],
        "catalog_id": str(p["catalog_id"]),
        "brand_id": str(p["brand_id"]) if p.get("brand_id") else None,
        "brand": p.get("brand"),
        "size_id": str(p["size_id"]) if p.get("size_id") else None,
        "price": p["price"],
        "currency": p.get("currency", "EUR"),
        "color_ids": [str(c) for c in p.get("color_ids", [])],
        "assigned_photos": [{"id": str(pid)} for pid in photo_ids],
        "package_size_id": p.get("package_size_id", 1),
        "measurement_length": 0,
        "measurement_width": 0,
        "item_attributes": [
            {"code": "brand", "ids": []},
            {"code": "size", "ids": []},
            {"code": "measurements", "ids": []},
            {"code": "condition", "ids": [p["condition_id"]] if p.get("condition_id") else []},
            {"code": "color", "ids": []},
            {"code": "material", "ids": [p["material_id"]] if p.get("material_id") else []},
        ],
    }


# ---------- public API for the route ----------


def is_configured() -> bool:
    """True if VINTED_SESSION_PATH points at a readable session file."""
    path = os.environ.get("VINTED_SESSION_PATH")
    if not path:
        return False
    return Path(path).expanduser().exists()


def is_session_ready() -> bool:
    """True if the persisted session loads cleanly and hasn't expired.
    Single source of truth for "is Vinted usable right now" — both onboarding
    /status and the inventory routes consult this."""
    if not is_configured():
        return False
    try:
        session = load_session(_session_path())
    except Exception:
        return False
    return session is not None and session.expires_at > time.time()


def seed_from_env() -> dict | None:
    """Read the four phone-extracted seed values from env vars.
    Returns None if any are missing — used by /onboarding/login."""
    seed = {
        "datadome_cookie": os.environ.get("VINTED_DATADOME_SEED", ""),
        "anon_id": os.environ.get("VINTED_ANON_ID", ""),
        "device_uuid": os.environ.get("VINTED_DEVICE_UUID", ""),
        "device_token": os.environ.get("VINTED_DEVICE_TOKEN", ""),
    }
    if not all(seed.values()):
        return None
    return seed


async def delete_listing(item_id: int | str) -> None:
    """Async wrapper around VintedClient.delete_draft. Reads the persisted
    session and writes back the rotated DataDome cookie afterward."""

    def _do() -> None:
        path = _session_path()
        session = load_session(path)
        if session is None:
            raise VintedNotConfigured(f"no session file at {path}")
        client = VintedClient(session)
        client.delete_draft(item_id)
        save_session(client.session, path)

    await asyncio.to_thread(_do)


async def login(email: str, password: str) -> VintedSession:
    """Async wrapper around password_login. Reads the seed from env vars and
    persists the resulting session to VINTED_SESSION_PATH so subsequent
    /publish calls can use it."""
    seed = seed_from_env()
    if seed is None:
        raise VintedNotConfigured(
            "VINTED_DATADOME_SEED / VINTED_ANON_ID / VINTED_DEVICE_UUID / "
            "VINTED_DEVICE_TOKEN must all be set (extract once via "
            "vinted-lister's `extract-cookie` CLI)"
        )

    def _do() -> VintedSession:
        session = password_login(email=email, password=password, seed=seed)
        save_session(session, _session_path())
        return session

    return await asyncio.to_thread(_do)


def _session_path() -> Path:
    path = os.environ.get("VINTED_SESSION_PATH")
    if not path:
        raise VintedNotConfigured("VINTED_SESSION_PATH is not set")
    return Path(path).expanduser()


async def publish(image_path: str | Path, payload: dict) -> tuple[int, str]:
    """Publish one item to Vinted. Sync HTTP wrapped in asyncio.to_thread.

    Returns (vinted_item_id, listing_url). Raises VintedError subclasses on
    failure — caller is expected to translate them into the response shape.
    """
    return await asyncio.to_thread(_publish_sync, image_path, payload)


def normalize_wardrobe_item(item: dict) -> dict:
    """Map a raw wardrobe API item to the column set in wardrobe_snapshots,
    plus a 'raw' key holding the full original blob for forward-compatibility.
    Returns a dict with keys consumed by db.insert_wardrobe_snapshots."""
    photos = item.get("photos") or []
    price = item.get("price") or {}
    raw_amount = price.get("amount") if isinstance(price, dict) else None
    return {
        "platform_listing_id": str(item["id"]),
        "title": item.get("title"),
        "price_eur": float(raw_amount) if raw_amount is not None else None,
        "currency": price.get("currency_code") if isinstance(price, dict) else None,
        "views": item.get("view_count"),
        "favourites": item.get("favourite_count"),
        "url": item.get("url"),
        "primary_photo_url": (photos[0].get("url") if photos and isinstance(photos[0], dict) else None),
        "raw": item,
    }


async def fetch_wardrobe() -> list[dict]:
    """Async wrapper around VintedClient.get_wardrobe. Reads the persisted
    session, fetches all wardrobe items, and writes back the rotated DataDome
    cookie. Returns the raw API item dicts."""

    def _do() -> list[dict]:
        path = _session_path()
        session = load_session(path)
        if session is None:
            raise VintedNotConfigured(f"no session file at {path}")
        client = VintedClient(session)
        items = client.get_wardrobe()
        save_session(client.session, path)
        return items

    return await asyncio.to_thread(_do)


def _publish_sync(image_path: str | Path, payload: dict) -> tuple[int, str]:
    path = _session_path()
    session = load_session(path)
    if session is None:
        raise VintedNotConfigured(f"no session file at {path}")
    client = VintedClient(session)
    # Resolve free-text brand → brand_id so the listing links to the brand
    # page. If the lookup misses, free-text brand still goes through.
    if payload.get("brand") and not payload.get("brand_id"):
        bid = client.resolve_brand_id(payload["brand"])
        if bid is not None:
            payload = {**payload, "brand_id": bid}
    photo_id = client.upload_photo(image_path)
    item_id, url = client.submit_listing_via_draft(payload, [photo_id])
    save_session(client.session, path)
    return item_id, url

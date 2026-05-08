"""Tests for the /onboarding routes."""

from __future__ import annotations

import json
import time

import httpx
import pytest
import respx


def _set_seed(monkeypatch):
    monkeypatch.setenv("VINTED_DATADOME_SEED", "seed-cookie")
    monkeypatch.setenv("VINTED_ANON_ID", "anon-uuid")
    monkeypatch.setenv("VINTED_DEVICE_UUID", "device-uuid")
    monkeypatch.setenv("VINTED_DEVICE_TOKEN", "device-token")


def _fake_jwt(exp: float, ka: bool = False) -> str:
    """Build a deterministic JWT payload with the given exp timestamp.
    Header and signature are placeholders — both integrations only decode
    the payload. Pass ka=True to include the KA-specific user_id claim."""
    import base64

    claims: dict = {"sub": "12345", "sid": "session-1", "exp": exp}
    if ka:
        claims["https://www.kleinanzeigen.de/user_id"] = 45852425
        claims["https://www.kleinanzeigen.de/user_uuid"] = "3fd1d48b-660f-4080-9da1-10989bb49e6b"
    payload = json.dumps(claims).encode()
    b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"header.{b64}.signature"


def test_status_all_not_configured(app_client, monkeypatch):
    """No env vars set → both platforms report their default unconfigured state."""
    monkeypatch.delenv("VINTED_SESSION_PATH", raising=False)
    monkeypatch.delenv("KA_SESSION_PATH", raising=False)
    r = app_client.get("/onboarding/status")
    assert r.status_code == 200
    body = r.json()
    assert body["vinted"]["state"] == "not_configured"
    assert body["kleinanzeigen"]["state"] == "not_configured"


def test_status_vinted_ready_with_session(app_client, monkeypatch, tmp_path):
    """A valid session file with a future expiry → state='ready'."""
    session_path = tmp_path / "vinted-session.json"
    session_path.write_text(json.dumps({
        "access_token": "atok",
        "refresh_token": "rtok",
        "expires_at": time.time() + 3600,
        "datadome_cookie": "cookie",
        "anon_id": "anon",
        "device_uuid": "duuid",
        "device_token": "dtok",
        "user_id": "42",
        "session_id": "sid",
        "domain": "www.vinted.fr",
    }))
    monkeypatch.setenv("VINTED_SESSION_PATH", str(session_path))

    r = app_client.get("/onboarding/status")
    body = r.json()
    assert body["vinted"]["state"] == "ready"
    assert body["vinted"]["user_id"] == "42"


def test_status_vinted_expired(app_client, monkeypatch, tmp_path):
    session_path = tmp_path / "vinted-session.json"
    session_path.write_text(json.dumps({
        "access_token": "atok",
        "refresh_token": "rtok",
        "expires_at": time.time() - 60,
        "datadome_cookie": "cookie",
        "anon_id": "anon",
        "device_uuid": "duuid",
        "device_token": "dtok",
    }))
    monkeypatch.setenv("VINTED_SESSION_PATH", str(session_path))

    r = app_client.get("/onboarding/status")
    assert r.json()["vinted"]["state"] == "expired"


def test_login_kleinanzeigen_password_returns_501(app_client):
    """Email+password login isn't viable for KA (Akamai BMP + MFA SMS).
    The /onboarding/login route still 501s for that platform; users go
    through /onboarding/kleinanzeigen with a captured refresh_token."""
    r = app_client.post("/onboarding/login", json={
        "platform": "kleinanzeigen", "email": "a@b.com", "password": "x",
    })
    assert r.status_code == 501


@respx.mock
def test_onboarding_kleinanzeigen_happy_path(app_client, monkeypatch, tmp_path):
    """POST /onboarding/kleinanzeigen with a valid refresh_token → 200,
    session persisted to KA_SESSION_PATH, /status reports ready."""
    session_path = tmp_path / "ka-session.json"
    monkeypatch.setenv("KA_SESSION_PATH", str(session_path))

    respx.post("https://login.kleinanzeigen.de/oauth/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": _fake_jwt(time.time() + 3600, ka=True),
                "refresh_token": "rotated-refresh",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "openid profile email offline_access urn:ebay-kleinanzeigen:user",
            },
        )
    )

    r = app_client.post("/onboarding/kleinanzeigen", json={
        "refresh_token": "captured-from-mitmproxy",
        "email": "demo@example.com",
        "poster_type": "PRIVATE",
        "home_location_id": 7615,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready"
    assert body["user_id"] == 45852425
    assert body["platform"] == "kleinanzeigen"

    saved = json.loads(session_path.read_text())
    assert saved["refresh_token"] == "rotated-refresh"
    assert saved["email"] == "demo@example.com"
    assert saved["home_location_id"] == 7615

    r = app_client.get("/onboarding/status")
    assert r.json()["kleinanzeigen"]["state"] == "ready"


def test_onboarding_kleinanzeigen_missing_session_path(app_client, monkeypatch):
    """No KA_SESSION_PATH set → 503 with a clear hint."""
    monkeypatch.delenv("KA_SESSION_PATH", raising=False)
    r = app_client.post("/onboarding/kleinanzeigen", json={
        "refresh_token": "x", "email": "a@b.com",
    })
    assert r.status_code == 503


@respx.mock
def test_onboarding_kleinanzeigen_bad_refresh_token(app_client, monkeypatch, tmp_path):
    """Auth0 returns 401 → /onboarding/kleinanzeigen returns 401."""
    monkeypatch.setenv("KA_SESSION_PATH", str(tmp_path / "ka.json"))
    respx.post("https://login.kleinanzeigen.de/oauth/token").mock(
        return_value=httpx.Response(401, json={"error": "invalid_grant"}),
    )
    r = app_client.post("/onboarding/kleinanzeigen", json={
        "refresh_token": "stale", "email": "a@b.com",
    })
    assert r.status_code == 401


def test_login_without_seed_returns_503(app_client, monkeypatch):
    """Seed env vars missing → 503 with a clear hint about extract-cookie."""
    for var in ("VINTED_DATADOME_SEED", "VINTED_ANON_ID", "VINTED_DEVICE_UUID", "VINTED_DEVICE_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    r = app_client.post("/onboarding/login", json={
        "platform": "vinted", "email": "a@b.com", "password": "x",
    })
    assert r.status_code == 503
    assert "extract-cookie" in r.json()["detail"].lower() or "device" in r.json()["detail"].lower()


@respx.mock
def test_login_happy_path(app_client, monkeypatch, tmp_path):
    """All env vars set + Vinted returns 200 → session JSON written, response
    has status='ready' and user_id from the JWT."""
    _set_seed(monkeypatch)
    session_path = tmp_path / "vinted-session.json"
    monkeypatch.setenv("VINTED_SESSION_PATH", str(session_path))

    # Mock the DataDome SDK refresh
    respx.post("https://api-sdk.datadome.co/sdk/").mock(
        return_value=httpx.Response(200, json={"cookie": "datadome=refreshed; Path=/; ..."})
    )
    # Mock the OAuth password grant
    respx.post("https://www.vinted.fr/oauth/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": _fake_jwt(time.time() + 3600),
                "refresh_token": "new-refresh-token",
                "token_type": "bearer",
                "expires_in": 3600,
            },
            headers={"set-cookie": "datadome=after-login; Path=/; HttpOnly"},
        )
    )

    r = app_client.post("/onboarding/login", json={
        "platform": "vinted", "email": "demo@example.com", "password": "secret",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["platform"] == "vinted"
    assert body["status"] == "ready"
    assert body["user_id"] == "12345"
    assert body["expires_at"] > time.time()

    # Session was persisted
    assert session_path.exists()
    saved = json.loads(session_path.read_text())
    assert saved["access_token"].startswith("header.")
    assert saved["refresh_token"] == "new-refresh-token"
    assert saved["datadome_cookie"] == "after-login"

    # And /status now reports ready
    r = app_client.get("/onboarding/status")
    assert r.json()["vinted"]["state"] == "ready"


@respx.mock
def test_login_bad_credentials_returns_401(app_client, monkeypatch, tmp_path):
    """Vinted returns 401 with a non-DataDome body → /onboarding/login 401s."""
    _set_seed(monkeypatch)
    monkeypatch.setenv("VINTED_SESSION_PATH", str(tmp_path / "should-not-be-written.json"))

    respx.post("https://api-sdk.datadome.co/sdk/").mock(
        return_value=httpx.Response(200, json={"cookie": "datadome=refreshed"})
    )
    respx.post("https://www.vinted.fr/oauth/token").mock(
        return_value=httpx.Response(401, json={"error": "invalid_grant"})
    )

    r = app_client.post("/onboarding/login", json={
        "platform": "vinted", "email": "demo@example.com", "password": "wrong",
    })
    assert r.status_code == 401


@respx.mock
def test_login_datadome_block_returns_429(app_client, monkeypatch, tmp_path):
    """Vinted returns a captcha challenge → /onboarding/login 429s."""
    _set_seed(monkeypatch)
    monkeypatch.setenv("VINTED_SESSION_PATH", str(tmp_path / "x.json"))

    respx.post("https://api-sdk.datadome.co/sdk/").mock(
        return_value=httpx.Response(200, json={"cookie": "datadome=refreshed"})
    )
    respx.post("https://www.vinted.fr/oauth/token").mock(
        return_value=httpx.Response(403, text="captcha challenge required")
    )

    r = app_client.post("/onboarding/login", json={
        "platform": "vinted", "email": "demo@example.com", "password": "x",
    })
    assert r.status_code == 429
    assert "datadome" in r.json()["detail"].lower()

"""Onboarding routes — login + session-status check.

POST /onboarding/login
  Take an email + password, run the platform's password-grant login flow,
  and persist the resulting session for /publish to consume. Password is
  used once and never logged or persisted.

GET /onboarding/status
  Per-platform: ready / needs_login / not_configured. Attempts to refresh
  expired sessions before reporting state — only escalates to needs_login
  when refresh actually fails. The frontend uses this to decide whether
  to show the per-platform Connect button.
"""

from __future__ import annotations

import asyncio
import logging
import os

from fastapi import APIRouter, HTTPException

from backend.integrations import kleinanzeigen as ka_integration
from backend.integrations import vinted as vinted_integration
from backend.schemas import (
    KleinanzeigenOnboardingRequest,
    KleinanzeigenOnboardingResponse,
    OnboardingLoginRequest,
    OnboardingLoginResponse,
    OnboardingStatusResponse,
    PlatformStatus,
)


router = APIRouter(prefix="/onboarding")
logger = logging.getLogger(__name__)


@router.post(
    "/login",
    response_model=OnboardingLoginResponse,
    responses={
        401: {"description": "credentials rejected by the platform"},
        429: {"description": "DataDome / anti-bot challenge — try again later"},
        501: {"description": "password login not implemented for this platform (use the platform-specific onboarding route)"},
        502: {"description": "upstream platform error"},
        503: {"description": "platform integration not configured (missing seed env vars)"},
    },
)
async def login(body: OnboardingLoginRequest) -> OnboardingLoginResponse:
    if body.platform != "vinted":
        raise HTTPException(
            status_code=501,
            detail=f"login for platform {body.platform!r} is not implemented (Phase 6c)",
        )

    try:
        session = await vinted_integration.login(body.email, body.password)
    except vinted_integration.VintedNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except vinted_integration.VintedAuthExpired as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except vinted_integration.VintedBlocked as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except vinted_integration.VintedError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return OnboardingLoginResponse(
        platform="vinted",
        status="ready",
        user_id=session.user_id,
        expires_at=session.expires_at,
    )


@router.post(
    "/kleinanzeigen",
    response_model=KleinanzeigenOnboardingResponse,
    responses={
        401: {"description": "refresh_token rejected — re-capture via mitmproxy"},
        502: {"description": "upstream KA / Auth0 error"},
        503: {"description": "KA_SESSION_PATH env var not set"},
    },
)
async def kleinanzeigen_onboarding(
    body: KleinanzeigenOnboardingRequest,
) -> KleinanzeigenOnboardingResponse:
    """Seed a KA session from a captured refresh_token. Persists the result
    to KA_SESSION_PATH so the runner picks it up on the next publish.

    login_with_refresh is sync (uses httpx.post); wrapped in to_thread so
    it doesn't block the event loop.
    """
    if not os.environ.get("KA_SESSION_PATH"):
        raise HTTPException(
            status_code=503,
            detail="KA_SESSION_PATH is not set in the backend env",
        )

    def _login_blocking() -> ka_integration.KASession:
        return ka_integration.login_with_refresh(
            refresh_token=body.refresh_token,
            email=body.email,
            poster_type=body.poster_type,
            imprint=body.imprint,
            contact_name=body.contact_name,
            home_location_id=body.home_location_id,
        )

    try:
        session = await asyncio.to_thread(_login_blocking)
    except ka_integration.KAAuthExpired as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ka_integration.KAError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    ka_integration.save_session(
        session, ka_integration._session_path()
    )
    return KleinanzeigenOnboardingResponse(
        status="ready",
        user_id=session.user_id,
        expires_at=session.expires_at,
    )


@router.get("/status", response_model=OnboardingStatusResponse)
async def status() -> OnboardingStatusResponse:
    return OnboardingStatusResponse(
        vinted=_vinted_status(),
        kleinanzeigen=_kleinanzeigen_status(),
    )


def _kleinanzeigen_status() -> PlatformStatus:
    session, state = ka_integration.try_load_or_refresh()
    return PlatformStatus(
        state=state,
        expires_at=session.expires_at if session else None,
        user_id=str(session.user_id) if session and session.user_id else None,
    )


def _vinted_status() -> PlatformStatus:
    session, state = vinted_integration.try_load_or_refresh()
    return PlatformStatus(
        state=state,
        expires_at=session.expires_at if session else None,
        user_id=session.user_id if session and session.user_id else None,
    )

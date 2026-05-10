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
    KleinanzeigenInitiateRequest,
    KleinanzeigenInitiateResponse,
    KleinanzeigenOnboardingRequest,
    KleinanzeigenOnboardingResponse,
    KleinanzeigenVerifyMfaRequest,
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


@router.post(
    "/kleinanzeigen/initiate",
    response_model=KleinanzeigenInitiateResponse,
    responses={
        401: {"description": "credentials rejected by Auth0"},
        502: {"description": "upstream KA / Auth0 transport error"},
        503: {"description": "KA_SESSION_PATH env var not set"},
    },
)
async def kleinanzeigen_initiate(
    body: KleinanzeigenInitiateRequest,
) -> KleinanzeigenInitiateResponse:
    """Walk the Auth0 PKCE login chain through the password POST. Returns an
    MFA challenge_id (the FE then collects the SMS code and calls
    /verify-mfa) or — rarely — a complete session if Auth0 skipped MFA.

    The whole chain is sync (uses httpx.Client); wrapped in a thread so it
    doesn't stall the event loop.
    """
    if not os.environ.get("KA_SESSION_PATH"):
        raise HTTPException(
            status_code=503,
            detail="KA_SESSION_PATH is not set in the backend env",
        )

    try:
        result = await asyncio.to_thread(
            ka_integration.password_login_initiate, body.email, body.password
        )
    except ka_integration.KAAuthExpired as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ka_integration.KAError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if result["status"] == "mfa_required":
        return KleinanzeigenInitiateResponse(
            status="mfa_required",
            challenge_id=result["challenge_id"],
            phone_hint=result.get("phone_hint"),
        )

    # status == "ready" — Auth0 skipped MFA. Exchange code → session
    # immediately, persist with default metadata. The FE never collected
    # poster_type / imprint / etc, so we use safe defaults; user can edit
    # them via a future settings page if needed.
    try:
        session = await asyncio.to_thread(
            ka_integration._exchange_code_for_session,
            code=result["code"],
            code_verifier=result["code_verifier"],
            email=body.email,
            poster_type=ka_integration.POSTER_TYPE_PRIVATE,
            imprint="",
            contact_name="",
            home_location_id=None,
        )
    except ka_integration.KAAuthExpired as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ka_integration.KAError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    ka_integration.save_session(session, ka_integration._session_path())
    return KleinanzeigenInitiateResponse(
        status="ready",
        user_id=session.user_id,
        expires_at=session.expires_at,
    )


@router.post(
    "/kleinanzeigen/verify-mfa",
    response_model=KleinanzeigenOnboardingResponse,
    responses={
        401: {"description": "SMS code rejected, expired, or challenge not found"},
        502: {"description": "upstream KA / Auth0 transport error"},
        503: {"description": "KA_SESSION_PATH env var not set"},
    },
)
async def kleinanzeigen_verify_mfa(
    body: KleinanzeigenVerifyMfaRequest,
) -> KleinanzeigenOnboardingResponse:
    """Complete an MFA-pending Auth0 login by submitting the SMS code +
    the optional metadata fields the user filled in while waiting."""
    if not os.environ.get("KA_SESSION_PATH"):
        raise HTTPException(
            status_code=503,
            detail="KA_SESSION_PATH is not set in the backend env",
        )

    try:
        session = await asyncio.to_thread(
            ka_integration.complete_mfa_login,
            body.challenge_id,
            body.sms_code,
            email=body.email,
            poster_type=body.poster_type,
            imprint=body.imprint,
            contact_name=body.contact_name,
            home_location_id=body.home_location_id,
        )
    except ka_integration.KAAuthExpired as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ka_integration.KAError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    ka_integration.save_session(session, ka_integration._session_path())
    return KleinanzeigenOnboardingResponse(
        status="ready",
        user_id=session.user_id,
        expires_at=session.expires_at,
    )


@router.get("/status", response_model=OnboardingStatusResponse)
async def status() -> OnboardingStatusResponse:
    # Both helpers do sync I/O (file read + optional refresh HTTP call).
    # Run them concurrently in worker threads so /onboarding/status latency
    # is max(vinted, ka) instead of vinted + ka, and we don't block the
    # event loop while either platform's refresh is in flight.
    vinted, ka = await asyncio.gather(
        asyncio.to_thread(_vinted_status),
        asyncio.to_thread(_kleinanzeigen_status),
    )
    return OnboardingStatusResponse(vinted=vinted, kleinanzeigen=ka)


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

"""Background runner that drains `pending` rows from `publishes` and posts
to the configured platform integration.

The runner FSM:

    pending  ─claim─▶  running  ─success─▶  posted   (terminal)
                          │
                          ├─retryable error─▶  pending (retry_count++, backoff)
                          │                    or failed if budget exhausted
                          │
                          └─permanent error──▶  failed   (terminal)

Tests drive `process_one_job()` directly, which does a single
claim → integration call → status update cycle. The `run()` method is the
asyncio loop wrapper that keeps calling process_one_job and sleeping when
nothing is ready.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

# backend/__init__.py adds repo/src to sys.path.
from listing_mappings import NEW_LISTING_URLS, to_vinted

from backend import db, integrations
from backend.integrations import vinted as vinted_integration


logger = logging.getLogger(__name__)


def _parse_backoff() -> tuple[float, ...]:
    raw = os.environ.get("PUBLISH_RETRY_BACKOFF", "5,30,120")
    try:
        return tuple(float(x.strip()) for x in raw.split(",") if x.strip())
    except ValueError:
        return (5.0, 30.0, 120.0)


def classify_error(exc: BaseException) -> str:
    """retryable | permanent. Determines whether the runner schedules another
    attempt or marks the job failed."""
    if isinstance(exc, vinted_integration.VintedAuthExpired):
        return "permanent"  # needs /onboarding/login, runner can't fix
    if isinstance(exc, vinted_integration.VintedNotConfigured):
        return "permanent"
    if isinstance(exc, vinted_integration.VintedBlocked):
        return "retryable"  # DataDome 429/captcha clears within minutes
    if isinstance(exc, asyncio.TimeoutError):
        return "retryable"
    if isinstance(exc, vinted_integration.VintedError):
        # Generic VintedError covers HTTP 4xx (validation, etc.) — those are
        # bad payload, retry won't help. The retryable HTTP statuses (429,
        # 5xx) get raised as VintedBlocked or come via TimeoutError.
        msg = str(exc).lower()
        if "http 5" in msg or "timeout" in msg:
            return "retryable"
        return "permanent"
    return "retryable"  # unknown → conservative: retry once or twice then fail


class PublishRunner:
    def __init__(
        self,
        db_path: Path | None = None,
        backoff_schedule: tuple[float, ...] | None = None,
        idle_sleep: float = 1.0,
    ):
        self.db_path = db_path
        self.backoff_schedule = backoff_schedule if backoff_schedule is not None else _parse_backoff()
        self.idle_sleep = idle_sleep
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    @property
    def max_retries(self) -> int:
        return len(self.backoff_schedule)

    async def process_one_job(self) -> bool:
        """Claim and process the next ready job. Returns True if a job was
        processed (even if it failed), False if the queue is empty.
        Synchronously useful in tests."""
        job = await db.claim_next_pending_job(self.db_path)
        if job is None:
            return False

        platform = job["platform"]
        listing_id = job["listing_id"]
        final_fields = job["final_fields"]

        # Re-do the publish path the route used to do synchronously: look up
        # the listing's image, build the platform-native payload, dispatch
        # to the right integration.
        try:
            await self._dispatch(platform, job, listing_id, final_fields)
        except BaseException as exc:  # noqa: BLE001
            await self._record_failure(job, exc)
            return True
        return True

    async def _dispatch(self, platform: str, job: dict, listing_id: str, final_fields: dict) -> None:
        if platform != "vinted":
            await db.update_publish_job(
                job["id"], db_path=self.db_path,
                status="failed",
                error=f"direct publishing on {platform!r} not implemented (Phase 6c)",
            )
            return

        if not integrations.is_configured("vinted"):
            await db.update_publish_job(
                job["id"], db_path=self.db_path,
                status="failed",
                error="Vinted integration not configured (set VINTED_SESSION_PATH)",
            )
            return

        # Look up the listing's image_path on disk.
        rec = await db.get_listing(listing_id, db_path=self.db_path)
        if rec is None:
            await db.update_publish_job(
                job["id"], db_path=self.db_path,
                status="failed",
                error=f"listing {listing_id} not found",
            )
            return

        payload = to_vinted(final_fields)
        if "catalog_id" not in payload:
            await db.update_publish_job(
                job["id"], db_path=self.db_path,
                status="failed",
                error=f"category {final_fields.get('category')!r} has no Vinted catalog mapping",
            )
            return
        if not payload.get("title") or not payload.get("description") or not payload.get("price"):
            await db.update_publish_job(
                job["id"], db_path=self.db_path,
                status="failed",
                error="title, description, and price are required for Vinted",
            )
            return

        item_id, url = await vinted_integration.publish(rec["image_path"], payload)
        await db.update_publish_job(
            job["id"], db_path=self.db_path,
            status="posted",
            platform_listing_id=str(item_id),
            platform_listing_url=url,
            error=None,
        )

    async def _record_failure(self, job: dict, exc: BaseException) -> None:
        """Either schedule a retry with backoff or mark the job failed,
        based on classify_error and the current retry_count."""
        kind = classify_error(exc)
        msg = f"{type(exc).__name__}: {exc}"
        retry_count = int(job["retry_count"])
        if kind == "retryable" and retry_count + 1 <= self.max_retries:
            backoff_s = self.backoff_schedule[retry_count]
            next_at = db.now_ms() + int(backoff_s * 1000)
            await db.update_publish_job(
                job["id"], db_path=self.db_path,
                status="pending",
                retry_count=retry_count + 1,
                next_attempt_at=next_at,
                error=msg,
            )
            logger.info(
                "publish job %d retrying (%d/%d) in %.0fs: %s",
                job["id"], retry_count + 1, self.max_retries, backoff_s, msg,
            )
            return

        await db.update_publish_job(
            job["id"], db_path=self.db_path,
            status="failed",
            error=msg,
        )
        logger.warning("publish job %d failed (%s): %s", job["id"], kind, msg)

    async def run(self) -> None:
        """Async loop. Cancellable; one task per backend process."""
        logger.info("PublishRunner starting (backoff=%s)", self.backoff_schedule)
        try:
            while not self._stop.is_set():
                try:
                    did_work = await self.process_one_job()
                except Exception:
                    logger.exception("PublishRunner: unhandled exception in process_one_job")
                    did_work = False
                if not did_work:
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=self.idle_sleep)
                    except asyncio.TimeoutError:
                        pass
        finally:
            logger.info("PublishRunner stopped")

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except (asyncio.CancelledError, Exception):
                    pass
            self._task = None

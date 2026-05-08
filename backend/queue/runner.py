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
asyncio loop wrapper that calls process_one_job and waits on `notify()`
when nothing is ready.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Literal

# backend/__init__.py adds repo/shared to sys.path.
from listing_mappings import to_kleinanzeigen, to_vinted

from backend import db, integrations
from backend.integrations import kleinanzeigen as ka_integration
from backend.integrations import vinted as vinted_integration


logger = logging.getLogger(__name__)


# Single source of truth for publish-job status strings; keep aligned with
# `JobStatus` Literal in backend/schemas.py.
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_POSTED = "posted"
STATUS_FAILED = "failed"


def _parse_backoff() -> tuple[float, ...]:
    raw = os.environ.get("PUBLISH_RETRY_BACKOFF", "5,30,120")
    try:
        return tuple(float(x.strip()) for x in raw.split(",") if x.strip())
    except ValueError:
        logger.warning(
            "PUBLISH_RETRY_BACKOFF=%r could not be parsed as comma-separated floats; "
            "falling back to default (5, 30, 120)",
            raw,
        )
        return (5.0, 30.0, 120.0)


def classify_error(exc: BaseException) -> Literal["retryable", "permanent"]:
    """Determines whether the runner schedules another attempt or marks
    the job failed."""
    # Permanent — needs human intervention (re-login, fix config, fix payload)
    if isinstance(exc, (vinted_integration.VintedAuthExpired, ka_integration.KAAuthExpired)):
        return "permanent"
    if isinstance(exc, (vinted_integration.VintedNotConfigured, ka_integration.KANotConfigured)):
        return "permanent"
    # DataDome challenge clears within minutes — retry
    if isinstance(exc, vinted_integration.VintedBlocked):
        return "retryable"
    if isinstance(exc, asyncio.TimeoutError):
        return "retryable"
    # Generic platform errors: HTTP 5xx → retryable transient, HTTP 4xx → permanent
    if isinstance(exc, (vinted_integration.VintedError, ka_integration.KAError)):
        msg = str(exc).lower()
        if "http 5" in msg or "timeout" in msg:
            return "retryable"
        return "permanent"
    return "retryable"


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
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    @property
    def max_retries(self) -> int:
        return len(self.backoff_schedule)

    def notify(self) -> None:
        """Wake the runner if it's waiting on the idle-sleep. Called by the
        route after enqueueing a job so the runner picks it up immediately
        instead of waiting for the next poll tick."""
        self._wake.set()

    async def process_one_job(self) -> bool:
        """Claim and process the next ready job. Returns True if a job was
        processed (success or failure), False if the queue is empty."""
        job = await db.claim_next_pending_job(self.db_path)
        if job is None:
            return False
        try:
            await self._dispatch(job)
        except Exception as exc:
            await self._record_failure(job, exc)
        return True

    async def _mark_failed(self, job_id: int, error: str) -> None:
        await db.update_publish_job(
            job_id, db_path=self.db_path, status=STATUS_FAILED, error=error,
        )

    async def _dispatch(self, job: dict) -> None:
        platform = job["platform"]

        rec = await db.get_listing(job["listing_id"], db_path=self.db_path)
        if rec is None:
            await self._mark_failed(job["id"], f"listing {job['listing_id']} not found")
            return

        if platform == "vinted":
            err = self._validate_vinted(job["final_fields"])
            if err:
                await self._mark_failed(job["id"], err)
                return
            payload = to_vinted(job["final_fields"])
            item_id, url = await vinted_integration.publish(rec["image_path"], payload)
        elif platform == "kleinanzeigen":
            err = self._validate_kleinanzeigen(job["final_fields"])
            if err:
                await self._mark_failed(job["id"], err)
                return
            payload = to_kleinanzeigen(job["final_fields"])
            item_id, url = await ka_integration.publish(rec["image_path"], payload)
        else:
            await self._mark_failed(
                job["id"], f"direct publishing on {platform!r} not implemented",
            )
            return

        await db.update_publish_job(
            job["id"], db_path=self.db_path,
            status=STATUS_POSTED,
            platform_listing_id=str(item_id),
            platform_listing_url=url,
            error=None,
        )

    @staticmethod
    def _validate_vinted(fields: dict) -> str | None:
        if not integrations.is_configured("vinted"):
            return "Vinted integration not configured (set VINTED_SESSION_PATH)"
        payload = to_vinted(fields)
        if "catalog_id" not in payload:
            return f"category {fields.get('category')!r} has no Vinted catalog mapping"
        if not payload.get("title") or not payload.get("description") or not payload.get("price"):
            return "title, description, and price are required for Vinted"
        return None

    @staticmethod
    def _validate_kleinanzeigen(fields: dict) -> str | None:
        if not integrations.is_configured("kleinanzeigen"):
            return "Kleinanzeigen integration not configured (set KA_SESSION_PATH)"
        payload = to_kleinanzeigen(fields)
        if "category_id" not in payload:
            return f"category {fields.get('category')!r} has no Kleinanzeigen category mapping"
        if not payload.get("title") or not payload.get("description") or payload.get("price_eur") is None:
            return "title, description, and price are required for Kleinanzeigen"
        return None

    async def _record_failure(self, job: dict, exc: Exception) -> None:
        kind = classify_error(exc)
        msg = f"{type(exc).__name__}: {exc}"
        retry_count = int(job["retry_count"])
        if kind == "retryable" and retry_count + 1 <= self.max_retries:
            backoff_s = self.backoff_schedule[retry_count]
            next_at = db.now_ms() + int(backoff_s * 1000)
            await db.update_publish_job(
                job["id"], db_path=self.db_path,
                status=STATUS_PENDING,
                retry_count=retry_count + 1,
                next_attempt_at=next_at,
                error=msg,
            )
            logger.info(
                "publish job %d retrying (%d/%d) in %.0fs: %s",
                job["id"], retry_count + 1, self.max_retries, backoff_s, msg,
            )
            return
        await self._mark_failed(job["id"], msg)
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
                    self._wake.clear()
                    # Wake on either an explicit notify() or the idle timeout —
                    # whichever comes first. Stop event also cancels the wait.
                    awakened = asyncio.create_task(self._wake.wait())
                    stopped = asyncio.create_task(self._stop.wait())
                    done, pending = await asyncio.wait(
                        {awakened, stopped},
                        timeout=self.idle_sleep,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for t in pending:
                        t.cancel()
        finally:
            logger.info("PublishRunner stopped")

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._wake.clear()
            self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()  # unblock the wait() if idle
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
